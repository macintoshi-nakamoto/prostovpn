package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// Snapshot — всё, что агент видит на узле за один заход.
//
// Сырые выводы (`awg show … dump`, ответы `xray api …`) уезжают как есть:
// у панели уже есть разборщики ровно этих форматов, и пока агент живёт
// рядом с обходом по SSH, цифры с двух путей должны совпадать буква в букву.
type Snapshot struct {
	Agent      string              `json:"agent"`
	At         int64               `json:"at"`
	Hostname   string              `json:"hostname"`
	UptimeS    int64               `json:"uptime_s"`
	Load       [3]float64          `json:"load"`
	MemTotalKB int64               `json:"mem_total_kb"`
	MemAvailKB int64               `json:"mem_avail_kb"`
	AWG        map[string]AWGIface `json:"awg"`
	Xray       XrayState           `json:"xray"`
	Hy2        Hy2State            `json:"hy2"`
	Services   map[string]string   `json:"services"`
	TookMS     int64               `json:"took_ms"`
}

type AWGIface struct {
	OK    bool   `json:"ok"`
	Port  int    `json:"port"`
	Peers int    `json:"peers"`
	Dump  string `json:"dump"`
	Error string `json:"error,omitempty"`
}

type XrayState struct {
	OK          bool   `json:"ok"`
	ListenOK    bool   `json:"listen_ok"`
	APIOK       bool   `json:"api_ok"`
	OnlineCount int    `json:"online_count"`
	Stats       string `json:"stats"`
	Online      string `json:"online"`
	IPs         string `json:"ips"`
	Error       string `json:"error,omitempty"`
}

type Hy2State struct {
	OK      bool            `json:"ok"`
	Port    int             `json:"port"`
	Traffic json.RawMessage `json:"traffic,omitempty"`
	Online  json.RawMessage `json:"online,omitempty"`
	Error   string          `json:"error,omitempty"`
}

const execTimeout = 10 * time.Second

func collect(ctx context.Context, cfg *Config) *Snapshot {
	started := time.Now()
	snap := &Snapshot{
		Agent:    version,
		At:       started.Unix(),
		AWG:      map[string]AWGIface{},
		Services: map[string]string{},
	}
	snap.Hostname, _ = os.Hostname()
	readSystem(snap)

	ifaces := awgInterfaces(ctx)
	for _, name := range ifaces {
		snap.AWG[name] = collectAWG(ctx, name)
	}
	snap.Xray = collectXray(ctx, cfg)
	snap.Hy2 = collectHy2(ctx, cfg)

	units := []string{"prosto-xray", "prosto-hy2", "prosto-extra-ports", "prosto-node-watchdog.timer"}
	for _, name := range ifaces {
		units = append(units, "awg-quick@"+name)
	}
	for _, unit := range units {
		snap.Services[unit] = unitState(ctx, unit)
	}

	snap.TookMS = time.Since(started).Milliseconds()
	return snap
}

// ───────────────────────── система

func readSystem(snap *Snapshot) {
	if raw, err := os.ReadFile("/proc/loadavg"); err == nil {
		fields := strings.Fields(string(raw))
		for i := 0; i < 3 && i < len(fields); i++ {
			snap.Load[i], _ = strconv.ParseFloat(fields[i], 64)
		}
	}
	if raw, err := os.ReadFile("/proc/uptime"); err == nil {
		if fields := strings.Fields(string(raw)); len(fields) > 0 {
			seconds, _ := strconv.ParseFloat(fields[0], 64)
			snap.UptimeS = int64(seconds)
		}
	}
	if raw, err := os.ReadFile("/proc/meminfo"); err == nil {
		scanner := bufio.NewScanner(bytes.NewReader(raw))
		for scanner.Scan() {
			key, rest, ok := strings.Cut(scanner.Text(), ":")
			if !ok {
				continue
			}
			fields := strings.Fields(rest)
			if len(fields) == 0 {
				continue
			}
			value, _ := strconv.ParseInt(fields[0], 10, 64)
			switch key {
			case "MemTotal":
				snap.MemTotalKB = value
			case "MemAvailable":
				snap.MemAvailKB = value
			}
		}
	}
}

// ───────────────────────── AmneziaWG

func awgInterfaces(ctx context.Context) []string {
	out, err := runCmd(ctx, "awg", "show", "interfaces")
	if err != nil {
		return nil
	}
	return strings.Fields(out)
}

func collectAWG(ctx context.Context, name string) AWGIface {
	state := AWGIface{}
	dump, err := runCmd(ctx, "awg", "show", name, "dump")
	if err != nil {
		state.Error = err.Error()
		return state
	}
	state.Dump = dump
	lines := strings.Count(strings.TrimSpace(dump), "\n")
	if strings.TrimSpace(dump) != "" {
		state.Peers = lines // первая строка — сам интерфейс, остальные — пиры
	}
	if port, err := runCmd(ctx, "awg", "show", name, "listen-port"); err == nil {
		state.Port, _ = strconv.Atoi(strings.TrimSpace(port))
	}
	state.OK = strings.TrimSpace(dump) != "" && state.Port > 0
	return state
}

// ───────────────────────── xray

var userLabel = regexp.MustCompile(`user>>>([^>"\s]+)`)

func collectXray(ctx context.Context, cfg *Config) XrayState {
	state := XrayState{}
	if _, err := os.Stat(cfg.XrayBin); err != nil {
		state.Error = "нет бинарника xray: " + cfg.XrayBin
		return state
	}

	state.ListenOK = true
	for _, port := range cfg.XrayPorts {
		if !listening(port) {
			state.ListenOK = false
			state.Error = fmt.Sprintf("порт %d не слушается", port)
		}
	}

	stats, err := runCmd(ctx, cfg.XrayBin, "api", "statsquery", "--server="+cfg.XrayAPI,
		"-pattern", "user>>>", "-reset=false")
	if err != nil {
		state.Error = joinErr(state.Error, "statsquery: "+err.Error())
		return state
	}
	state.APIOK = true
	state.Stats = stats

	online, err := runCmd(ctx, cfg.XrayBin, "api", "statsgetallonlineusers", "--server="+cfg.XrayAPI)
	if err != nil {
		state.Error = joinErr(state.Error, "online: "+err.Error())
	} else {
		state.Online = online
	}

	// Адреса каждой живой учётки — тем же способом, каким это делал скрипт
	// по SSH, только без SSH: цикл крутится здесь, на узле.
	seen := map[string]bool{}
	var ips strings.Builder
	for _, match := range userLabel.FindAllStringSubmatch(state.Online, -1) {
		label := match[1]
		if seen[label] {
			continue
		}
		seen[label] = true
		list, err := runCmd(ctx, cfg.XrayBin, "api", "statsonlineiplist", "--server="+cfg.XrayAPI, "-email", label)
		if err != nil {
			continue
		}
		ips.WriteString("@@U@@" + label + "\n")
		ips.WriteString(list)
		if !strings.HasSuffix(list, "\n") {
			ips.WriteString("\n")
		}
	}
	state.OnlineCount = len(seen)
	state.IPs = ips.String()
	state.OK = state.ListenOK && state.APIOK
	return state
}

// ───────────────────────── Hysteria2

func collectHy2(ctx context.Context, cfg *Config) Hy2State {
	state := Hy2State{Port: 10086}
	secretRaw, err := os.ReadFile(cfg.Hy2Dir + "/stats.secret")
	if err != nil {
		state.Error = "нет stats.secret: " + err.Error()
		return state
	}
	secret := strings.TrimSpace(string(secretRaw))
	if port := hy2StatsPort(cfg.Hy2Dir + "/config.yaml"); port > 0 {
		state.Port = port
	}

	client := &http.Client{Timeout: 8 * time.Second}
	get := func(path string) (json.RawMessage, error) {
		req, err := http.NewRequestWithContext(ctx, http.MethodGet,
			fmt.Sprintf("http://127.0.0.1:%d%s", state.Port, path), nil)
		if err != nil {
			return nil, err
		}
		req.Header.Set("Authorization", secret)
		resp, err := client.Do(req)
		if err != nil {
			return nil, err
		}
		defer resp.Body.Close()
		body, err := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
		if err != nil {
			return nil, err
		}
		if resp.StatusCode != http.StatusOK {
			return nil, fmt.Errorf("%s: HTTP %d", path, resp.StatusCode)
		}
		if !json.Valid(body) {
			return nil, fmt.Errorf("%s: не JSON", path)
		}
		return json.RawMessage(body), nil
	}

	// Без clear=1: счётчики только читаем. Обнулять их — работа обхода,
	// пока он ещё ходит по SSH; два обнуляющих читателя разворовали бы
	// друг у друга трафик людей.
	traffic, err := get("/traffic")
	if err != nil {
		state.Error = err.Error()
		return state
	}
	online, err := get("/online")
	if err != nil {
		state.Error = err.Error()
		return state
	}
	state.Traffic = traffic
	state.Online = online
	state.OK = true
	return state
}

// hy2StatsPort — порт из блока trafficStats в config.yaml. Разбор построчный
// и нарочно простой: нам нужен один адрес, а не весь YAML.
func hy2StatsPort(path string) int {
	raw, err := os.ReadFile(path)
	if err != nil {
		return 0
	}
	inBlock := false
	for _, line := range strings.Split(string(raw), "\n") {
		trimmed := strings.TrimSpace(line)
		if strings.HasPrefix(trimmed, "trafficStats:") {
			inBlock = true
			continue
		}
		if inBlock {
			if !strings.HasPrefix(line, " ") && trimmed != "" {
				break
			}
			if strings.HasPrefix(trimmed, "listen:") {
				value := strings.Trim(strings.TrimSpace(strings.TrimPrefix(trimmed, "listen:")), `"'`)
				if _, portText, ok := strings.Cut(value, ":"); ok {
					port, _ := strconv.Atoi(portText)
					return port
				}
			}
		}
	}
	return 0
}

// ───────────────────────── общее

func listening(port int) bool {
	conn, err := net.DialTimeout("tcp", fmt.Sprintf("127.0.0.1:%d", port), 2*time.Second)
	if err != nil {
		return false
	}
	conn.Close()
	return true
}

func unitState(ctx context.Context, unit string) string {
	out, _ := runCmd(ctx, "systemctl", "is-active", unit)
	state := strings.TrimSpace(out)
	if state == "" {
		return "unknown"
	}
	return state
}

func runCmd(ctx context.Context, name string, args ...string) (string, error) {
	ctx, cancel := context.WithTimeout(ctx, execTimeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, name, args...)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		msg := strings.TrimSpace(stderr.String())
		if msg == "" {
			msg = err.Error()
		}
		if len(msg) > 300 {
			msg = msg[:300]
		}
		return stdout.String(), fmt.Errorf("%s: %s", name, msg)
	}
	return stdout.String(), nil
}

func joinErr(a, b string) string {
	if a == "" {
		return b
	}
	return a + "; " + b
}
