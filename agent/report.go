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
// или реже, не трогая настройки на узле.
type reply struct {
	OK       bool   `json:"ok"`
	Interval int    `json:"interval"`
	Error    string `json:"error,omitempty"`
}

var httpClient = &http.Client{Timeout: 20 * time.Second}

func send(ctx context.Context, cfg *Config, snap *Snapshot) (int, error) {
	body, err := json.Marshal(snap)
	if err != nil {
		return 0, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, cfg.PanelURL+"/api/v1/node/report", bytes.NewReader(body))
	if err != nil {
		return 0, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+cfg.Token)
	req.Header.Set("User-Agent", "prosto-node/"+version)

	resp, err := httpClient.Do(req)
	if err != nil {
		return 0, err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 64<<10))
	if resp.StatusCode != http.StatusOK {
		return 0, fmt.Errorf("HTTP %d: %s", resp.StatusCode, trim(raw))
	}
	var answer reply
	if err := json.Unmarshal(raw, &answer); err != nil {
		return 0, fmt.Errorf("ответ панели не разобран: %s", trim(raw))
	}
	if !answer.OK {
		return 0, fmt.Errorf("панель отказала: %s", answer.Error)
	}
	return answer.Interval, nil
}

func trim(raw []byte) string {
	s := string(bytes.TrimSpace(raw))
	if len(s) > 200 {
		return s[:200] + "…"
	}
	return s
}
