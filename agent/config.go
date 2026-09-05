package main

import (
	"bufio"
	"fmt"
	"os"
	"strconv"
	"strings"
)

// Config — настройки агента. Файл вида KEY=VALUE, как .env: его пишет
// install.sh, а править руками можно любым редактором.
type Config struct {
	PanelURL string // https://prostovpn.cc
	Token    string // токен этого узла из панели
	Interval int    // секунд между снимками

	XrayBin   string // /opt/prosto-xray/xray
	XrayAPI   string // 127.0.0.1:10085
	XrayPorts []int  // порты входа, которые должны слушаться (Reality)

	Hy2Dir string // /opt/prosto-hy2 — config.yaml и stats.secret
}

func defaults() *Config {
	return &Config{
		Interval:  15,
		XrayBin:   "/opt/prosto-xray/xray",
		XrayAPI:   "127.0.0.1:10085",
		XrayPorts: []int{443},
		Hy2Dir:    "/opt/prosto-hy2",
	}
}

func loadConfig(path string) (*Config, error) {
	cfg := defaults()
	file, err := os.Open(path)
	if err != nil {
		if os.IsNotExist(err) {
			// Без файла агент годится только для --once: посмотреть, что
			// он видит на узле, ещё до того как заводить его в панели.
			return cfg, nil
		}
		return nil, err
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	line := 0
	for scanner.Scan() {
		line++
		raw := strings.TrimSpace(scanner.Text())
		if raw == "" || strings.HasPrefix(raw, "#") {
			continue
		}
		key, value, ok := strings.Cut(raw, "=")
		if !ok {
			return nil, fmt.Errorf("%s:%d: ожидалось KEY=VALUE", path, line)
		}
		key = strings.TrimSpace(key)
		value = strings.Trim(strings.TrimSpace(value), `"'`)
		switch key {
		case "PANEL_URL":
			cfg.PanelURL = strings.TrimRight(value, "/")
		case "TOKEN":
			cfg.Token = value
		case "INTERVAL":
			n, err := strconv.Atoi(value)
			if err != nil || n < 5 || n > 300 {
				return nil, fmt.Errorf("%s:%d: INTERVAL — секунды от 5 до 300", path, line)
			}
			cfg.Interval = n
		case "XRAY_BIN":
			cfg.XrayBin = value
		case "XRAY_API":
			cfg.XrayAPI = value
		case "XRAY_PORTS":
			cfg.XrayPorts = cfg.XrayPorts[:0]
			for _, part := range strings.Split(value, ",") {
				part = strings.TrimSpace(part)
				if part == "" {
					continue
				}
				n, err := strconv.Atoi(part)
				if err != nil || n < 1 || n > 65535 {
					return nil, fmt.Errorf("%s:%d: XRAY_PORTS — порты через запятую", path, line)
				}
				cfg.XrayPorts = append(cfg.XrayPorts, n)
			}
		case "HY2_DIR":
			cfg.Hy2Dir = strings.TrimRight(value, "/")
		default:
			return nil, fmt.Errorf("%s:%d: незнакомый ключ %s", path, line, key)
		}
	}
	return cfg, scanner.Err()
}
