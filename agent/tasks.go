package main

// Задания панели (третий шаг агента). Панель кладёт их в ответ на снимок,
// агент исполняет по очереди и подтверждает в следующем снимке. Каждый вид
// задания — фиксированный набор полей, никакого shell: команды собираются
// из аргументов, пути проверяются на свои каталоги, имена интерфейсов и
// ключи — на форму. Всё идемпотентно: панель, не дождавшись подтверждения,
// делает то же по SSH, и повтор не должен ничего испортить.

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/exec"
	"os/user"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"syscall"
	"time"
)

type Task struct {
	ID      int64           `json:"id"`
	Kind    string          `json:"kind"`
	Payload json.RawMessage `json:"payload"`
}

type Ack struct {
	ID    int64  `json:"id"`
	OK    bool   `json:"ok"`
	Out   string `json:"out,omitempty"`
	Error string `json:"error,omitempty"`
}

const (
	awgDir  = "/etc/amnezia/amneziawg"
	xrayDir = "/opt/prosto-xray"
)

var (
	ifaceRe  = regexp.MustCompile(`^awg([0-9]|[1-9][0-9])$`)
	pubkeyRe = regexp.MustCompile(`^[A-Za-z0-9+/]{43}=$`)
	labelRe  = regexp.MustCompile(`^[A-Za-z0-9._@-]{1,64}$`)
	apiRe    = regexp.MustCompile(`^127\.0\.0\.1:[0-9]{2,5}$`)
	tagRe    = regexp.MustCompile(`^[A-Za-z0-9._-]{1,64}$`)

	allowedUnits = map[string]bool{"prosto-xray": true, "prosto-hy2": true}
)

func runTasks(ctx context.Context, cfg *Config, tasks []Task) []Ack {
	acks := make([]Ack, 0, len(tasks))
	for _, task := range tasks {
		out, err := runTask(ctx, cfg, task)
		ack := Ack{ID: task.ID, OK: err == nil, Out: clip(out, 4000)}
		if err != nil {
			ack.Error = clip(err.Error(), 1000)
			log.Printf("задание #%d %s: %v", task.ID, task.Kind, err)
		}
		acks = append(acks, ack)
	}
	return acks
}

func runTask(ctx context.Context, cfg *Config, task Task) (string, error) {
	switch task.Kind {
	case "awg_add":
		return awgAdd(ctx, task.Payload)
	case "awg_remove":
		return awgRemove(ctx, task.Payload)
	case "xray_write":
		return xrayWrite(ctx, task.Payload)
	case "xray_adu":
		return xrayAdu(ctx, cfg, task.Payload)
	case "xray_rmu":
		return xrayRmu(ctx, cfg, task.Payload)
	case "hy2_kick":
		return hy2Kick(ctx, cfg, task.Payload)
	case "restart":
		return restartUnit(ctx, task.Payload)
	}
	return "", fmt.Errorf("неизвестное задание %q", task.Kind)
}

// ───────────────────────── AmneziaWG

type awgPeerIn struct {
	Iface     string `json:"iface"`
	PublicKey string `json:"public_key"`
	Address   string `json:"address"`
}

func (p *awgPeerIn) check(needAddress bool) error {
	if !ifaceRe.MatchString(p.Iface) {
		return fmt.Errorf("недопустимое имя интерфейса %q", p.Iface)
	}
	if !pubkeyRe.MatchString(p.PublicKey) {
		return errors.New("недопустимый публичный ключ")
	}
	if needAddress {
		if _, _, err := net.ParseCIDR(p.Address); err != nil {
			return fmt.Errorf("недопустимый адрес %q", p.Address)
		}
	}
	return nil
}

func awgConf(iface string) string { return awgDir + "/" + iface + ".conf" }
func awgLock(iface string) string { return awgDir + "/." + iface + ".conf.lock" }

// awgAdd — тот же порядок, что у панели по SSH: блок [Peer] в конфиг (под
// замком, чтобы на диске пир пережил перезагрузку), потом awg set в живой
// интерфейс. Уже записанный ключ второй раз не дописываем.
func awgAdd(ctx context.Context, raw json.RawMessage) (string, error) {
	var p awgPeerIn
	if err := json.Unmarshal(raw, &p); err != nil {
		return "", err
	}
	if err := p.check(true); err != nil {
		return "", err
	}
	unlock, err := flock(awgLock(p.Iface))
	if err != nil {
		return "", err
	}
	defer unlock()

	conf := awgConf(p.Iface)
	text, err := os.ReadFile(conf)
	if err != nil {
		return "", err
	}
	if !strings.Contains(string(text), p.PublicKey) {
		block := "\n[Peer]\nPublicKey = " + p.PublicKey + "\nAllowedIPs = " + p.Address + "\n"
		f, err := os.OpenFile(conf, os.O_APPEND|os.O_WRONLY, 0)
		if err != nil {
			return "", err
		}
		if _, err := f.WriteString(block); err != nil {
			f.Close()
			return "", err
		}
		if err := f.Sync(); err != nil {
			f.Close()
			return "", err
		}
		f.Close()
	}
	return runCmd(ctx, "awg", "set", p.Iface, "peer", p.PublicKey, "allowed-ips", p.Address)
}

// awgRemove — вырезает блок [Peer] с этим ключом из конфига (та же
// регулярка, что у панели) и снимает пир с живого интерфейса.
func awgRemove(ctx context.Context, raw json.RawMessage) (string, error) {
	var p awgPeerIn
	if err := json.Unmarshal(raw, &p); err != nil {
		return "", err
	}
	if err := p.check(false); err != nil {
		return "", err
	}
	unlock, err := flock(awgLock(p.Iface))
	if err != nil {
		return "", err
	}
	defer unlock()

	conf := awgConf(p.Iface)
	text, err := os.ReadFile(conf)
	if err != nil {
		return "", err
	}
	re := regexp.MustCompile(`\n\[Peer\][^\[]*` + regexp.QuoteMeta(p.PublicKey) + `[^\[]*`)
	next := re.ReplaceAllString(string(text), "\n")
	if next != string(text) {
		if err := writeAtomic(conf, []byte(next), 0, -1, -1); err != nil {
			return "", err
		}
	}
	out, err := runCmd(ctx, "awg", "set", p.Iface, "peer", p.PublicKey, "remove")
	if err != nil && strings.Contains(err.Error(), "No such peer") {
		// Пира уже нет — снято. Так бывает, когда панель сделала то же по SSH.
		return out, nil
	}
	return out, err
}

// ───────────────────────── xray

type xrayWriteIn struct {
	Path    string `json:"path"`
	Content string `json:"content"`
	Mode    string `json:"mode"`
	Owner   string `json:"owner"`
	Lock    string `json:"lock"`
	Restart string `json:"restart"`
}

// xrayWrite — конфиг xray на диск: проверка JSON до подмены (битый файл
// демон не переживёт), права и владелец как у прежнего файла, атомарная
// замена, потом перезапуск, если панель просила.
func xrayWrite(ctx context.Context, raw json.RawMessage) (string, error) {
	var in xrayWriteIn
	if err := json.Unmarshal(raw, &in); err != nil {
		return "", err
	}
	path := filepath.Clean(in.Path)
	if !strings.HasPrefix(path, xrayDir+"/") {
		return "", fmt.Errorf("путь %q вне %s", in.Path, xrayDir)
	}
	if !json.Valid([]byte(in.Content)) {
		return "", errors.New("конфиг — не JSON, не пишем")
	}
	lock := in.Lock
	if lock == "" || !strings.HasPrefix(filepath.Clean(lock), xrayDir+"/") {
		lock = xrayDir + "/.config.lock"
	}
	unlock, err := flock(lock)
	if err != nil {
		return "", err
	}
	defer unlock()

	mode := os.FileMode(0o640)
	if in.Mode != "" {
		if parsed, err := strconv.ParseUint(in.Mode, 8, 32); err == nil {
			mode = os.FileMode(parsed)
		}
	}
	uid, gid := -1, -1
	if info, err := os.Stat(path); err == nil {
		if st, ok := info.Sys().(*syscall.Stat_t); ok {
			uid, gid = int(st.Uid), int(st.Gid)
		}
	} else if in.Owner != "" {
		uid, gid = lookupOwner(in.Owner)
	}
	if err := writeAtomic(path, []byte(in.Content), mode, uid, gid); err != nil {
		return "", err
	}
	if in.Restart != "" {
		if !allowedUnits[in.Restart] {
			return "", fmt.Errorf("перезапуск %q не разрешён", in.Restart)
		}
		return runCmd(ctx, "systemctl", "restart", in.Restart)
	}
	return "", nil
}

type xrayAduIn struct {
	API     string `json:"api"`
	Payload string `json:"payload"`
}

// xrayAdu — дослать учётки в живой xray через его API. Код выхода не
// считаем ошибкой, как и по SSH: панель сама разбирает вывод («Added N»,
// «already exists»).
func xrayAdu(ctx context.Context, cfg *Config, raw json.RawMessage) (string, error) {
	var in xrayAduIn
	if err := json.Unmarshal(raw, &in); err != nil {
		return "", err
	}
	if !apiRe.MatchString(in.API) {
		return "", fmt.Errorf("недопустимый адрес API %q", in.API)
	}
	if !json.Valid([]byte(in.Payload)) {
		return "", errors.New("учётки — не JSON")
	}
	tmp, err := os.CreateTemp("", "prosto-adu-*.json")
	if err != nil {
		return "", err
	}
	defer os.Remove(tmp.Name())
	if _, err := tmp.WriteString(in.Payload); err != nil {
		tmp.Close()
		return "", err
	}
	tmp.Close()
	return runCmdAll(ctx, cfg.XrayBin, "api", "adu", "-s", in.API, "-t", "5", tmp.Name()), nil
}

type xrayRmuIn struct {
	API    string   `json:"api"`
	Tags   []string `json:"tags"`
	Emails []string `json:"emails"`
}

func xrayRmu(ctx context.Context, cfg *Config, raw json.RawMessage) (string, error) {
	var in xrayRmuIn
	if err := json.Unmarshal(raw, &in); err != nil {
		return "", err
	}
	if !apiRe.MatchString(in.API) {
		return "", fmt.Errorf("недопустимый адрес API %q", in.API)
	}
	for _, e := range in.Emails {
		if !labelRe.MatchString(e) {
			return "", fmt.Errorf("недопустимая учётка %q", e)
		}
	}
	var out strings.Builder
	for _, tag := range in.Tags {
		if !tagRe.MatchString(tag) {
			return "", fmt.Errorf("недопустимый tag %q", tag)
		}
		args := append([]string{"api", "rmu", "-s", in.API, "-t", "5", "-tag=" + tag}, in.Emails...)
		out.WriteString(runCmdAll(ctx, cfg.XrayBin, args...))
		out.WriteString("\n")
	}
	return out.String(), nil
}

// ───────────────────────── Hysteria2

type hy2KickIn struct {
	Labels []string `json:"labels"`
}

func hy2Kick(ctx context.Context, cfg *Config, raw json.RawMessage) (string, error) {
	var in hy2KickIn
	if err := json.Unmarshal(raw, &in); err != nil {
		return "", err
	}
	labels := make([]string, 0, len(in.Labels))
	for _, l := range in.Labels {
		if l == "" {
			continue
		}
		if !labelRe.MatchString(l) {
			return "", fmt.Errorf("недопустимая учётка %q", l)
		}
		labels = append(labels, l)
	}
	if len(labels) == 0 {
		return "", nil
	}
	secretRaw, err := os.ReadFile(cfg.Hy2Dir + "/stats.secret")
	if err != nil {
		return "", fmt.Errorf("нет stats.secret: %w", err)
	}
	port := hy2StatsPort(cfg.Hy2Dir + "/config.yaml")
	if port <= 0 {
		port = 10086
	}
	body, _ := json.Marshal(labels)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost,
		fmt.Sprintf("http://127.0.0.1:%d/kick", port), bytes.NewReader(body))
	if err != nil {
		return "", err
	}
	req.Header.Set("Authorization", strings.TrimSpace(string(secretRaw)))
	req.Header.Set("Content-Type", "application/json")
	client := &http.Client{Timeout: 8 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	answer, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("/kick: HTTP %d: %s", resp.StatusCode, clip(string(answer), 200))
	}
	return fmt.Sprintf("kicked %d", len(labels)), nil
}

// ───────────────────────── systemd

type restartIn struct {
	Unit string `json:"unit"`
}

func restartUnit(ctx context.Context, raw json.RawMessage) (string, error) {
	var in restartIn
	if err := json.Unmarshal(raw, &in); err != nil {
		return "", err
	}
	if !allowedUnits[in.Unit] {
		return "", fmt.Errorf("перезапуск %q не разрешён", in.Unit)
	}
	return runCmd(ctx, "systemctl", "restart", in.Unit)
}

// ───────────────────────── общее

func flock(path string) (func(), error) {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		return nil, err
	}
	if err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX); err != nil {
		f.Close()
		return nil, err
	}
	return func() {
		syscall.Flock(int(f.Fd()), syscall.LOCK_UN)
		f.Close()
	}, nil
}

// writeAtomic — во временный файл рядом, fsync, права и владелец, rename,
// fsync каталога. mode 0 или uid/gid < 0 — взять у прежнего файла
// (нет прежнего — 0600 и владелец процесса).
func writeAtomic(path string, data []byte, mode os.FileMode, uid, gid int) error {
	dir := filepath.Dir(path)
	if info, err := os.Stat(path); err == nil {
		if mode == 0 {
			mode = info.Mode().Perm()
		}
		if st, ok := info.Sys().(*syscall.Stat_t); ok && (uid < 0 || gid < 0) {
			uid, gid = int(st.Uid), int(st.Gid)
		}
	}
	if mode == 0 {
		mode = 0o600
	}
	tmp, err := os.CreateTemp(dir, ".prosto-*.tmp")
	if err != nil {
		return err
	}
	name := tmp.Name()
	cleanup := func() { os.Remove(name) }
	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		cleanup()
		return err
	}
	if err := tmp.Sync(); err != nil {
		tmp.Close()
		cleanup()
		return err
	}
	if err := tmp.Close(); err != nil {
		cleanup()
		return err
	}
	if err := os.Chmod(name, mode); err != nil {
		cleanup()
		return err
	}
	if uid >= 0 && gid >= 0 {
		if err := os.Chown(name, uid, gid); err != nil {
			cleanup()
			return err
		}
	}
	if err := os.Rename(name, path); err != nil {
		cleanup()
		return err
	}
	if d, err := os.Open(dir); err == nil {
		d.Sync()
		d.Close()
	}
	return nil
}

func lookupOwner(spec string) (int, int) {
	uid, gid := -1, -1
	userName, groupName, _ := strings.Cut(spec, ":")
	if u, err := user.Lookup(userName); err == nil {
		uid, _ = strconv.Atoi(u.Uid)
		gid, _ = strconv.Atoi(u.Gid)
	}
	if groupName != "" {
		if g, err := user.LookupGroup(groupName); err == nil {
			gid, _ = strconv.Atoi(g.Gid)
		}
	}
	return uid, gid
}

// runCmdAll — объединённый вывод без ошибки по коду выхода: для команд, чей
// результат панель разбирает по тексту.
func runCmdAll(ctx context.Context, name string, args ...string) string {
	ctx, cancel := context.WithTimeout(ctx, execTimeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, name, args...)
	var out bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &out
	_ = cmd.Run()
	return out.String()
}

func clip(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "…"
}
