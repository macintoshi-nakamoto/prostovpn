package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// Ответ панели на снимок. interval — панель может попросить ходить чаще
// или реже, не трогая настройки на узле. account — панель зачисляет
// трафик по нашим снимкам, значит счётчики Hysteria2 можно обнулять и
// слать дельты; старая панель этого поля не знает — тогда false.
type reply struct {
	OK       bool   `json:"ok"`
	Interval int    `json:"interval"`
	Account  bool   `json:"account"`
	Error    string `json:"error,omitempty"`
}

var httpClient = &http.Client{Timeout: 20 * time.Second}

func send(ctx context.Context, cfg *Config, snap *Snapshot) (reply, error) {
	body, err := json.Marshal(snap)
	if err != nil {
		return reply{}, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, cfg.PanelURL+"/api/v1/node/report", bytes.NewReader(body))
	if err != nil {
		return reply{}, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+cfg.Token)
	req.Header.Set("User-Agent", "prosto-node/"+version)

	resp, err := httpClient.Do(req)
	if err != nil {
		return reply{}, err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 64<<10))
	if resp.StatusCode != http.StatusOK {
		return reply{}, fmt.Errorf("HTTP %d: %s", resp.StatusCode, trim(raw))
	}
	var answer reply
	if err := json.Unmarshal(raw, &answer); err != nil {
		return reply{}, fmt.Errorf("ответ панели не разобран: %s", trim(raw))
	}
	if !answer.OK {
		return reply{}, fmt.Errorf("панель отказала: %s", answer.Error)
	}
	return answer, nil
}

func trim(raw []byte) string {
	s := string(bytes.TrimSpace(raw))
	if len(s) > 200 {
		return s[:200] + "…"
	}
	return s
}
