// prosto-node — агент на узле Prosto VPN.
//
// Агент смотрит на узел и рассказывает панели. Раз в несколько секунд он
// снимает то же, за чем панель раньше ходила по SSH, — пиры AmneziaWG,
// счётчики и онлайн xray, счётчики Hysteria2, живость каждой службы — и
// отправляет снимок панели по HTTPS с токеном. По снимкам панель зачисляет
// трафик и считает узел живым; обход по SSH остаётся запасным путём на
// случай, если агент замолчит.
//
// На узле агент меняет ровно то, что раньше панель делала по SSH, и ровно
// по её заданиям (tasks.go): ставит и снимает пиры AmneziaWG, дописывает
// учётки в xray, пишет его конфиг, выкидывает сессии Hysteria2. Задание
// приезжает в ответе на снимок (панель держит ответ, пока задания нет),
// исполняется сразу и подтверждается следующим снимком без ожидания
// интервала. Ещё агент обнуляет счётчики Hysteria2 (/traffic?clear=1),
// когда панель ответила account=true. Откат — выключить службу: панель
// вернётся к SSH сама.
//
// Только стандартная библиотека: бинарник должен быть таким, чтобы его
// можно было прочитать целиком и понять, что он делает на узле от root.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"
)

const version = "0.3.0"

func main() {
	confPath := flag.String("config", "/etc/prosto-node/agent.conf", "файл настроек")
	once := flag.Bool("once", false, "снять снимок, напечатать JSON и выйти")
	showVersion := flag.Bool("version", false, "версия и выход")
	flag.Parse()

	if *showVersion {
		fmt.Println("prosto-node", version)
		return
	}

	log.SetFlags(0) // journald сам ставит время

	cfg, err := loadConfig(*confPath)
	if err != nil {
		log.Fatalf("настройки: %v", err)
	}

	if *once {
		snap := collect(context.Background(), cfg, false)
		enc := json.NewEncoder(os.Stdout)
		enc.SetIndent("", "  ")
		if err := enc.Encode(snap); err != nil {
			log.Fatalf("вывод: %v", err)
		}
		return
	}

	if cfg.PanelURL == "" || cfg.Token == "" {
		log.Fatal("в настройках нужны PANEL_URL и TOKEN")
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	log.Printf("prosto-node %s: панель %s, интервал %ds", version, cfg.PanelURL, cfg.Interval)
	run(ctx, cfg)
	log.Print("остановлен")
}

// run — один цикл за раз: снял, отправил, подождал. Если сбор занял больше
// интервала (узел под нагрузкой), следующий начинается сразу, без очереди.
func run(ctx context.Context, cfg *Config) {
	interval := time.Duration(cfg.Interval) * time.Second
	failures := 0
	lastSummary := time.Time{}
	// account — панель зачисляет по нашим снимкам (её последний ответ).
	// pending — дельты Hysteria2, уже снятые с обнулением, но панелью ещё не
	// принятые: пока она молчит, копим и шлём накопленное, чтобы не терять.
	account := false
	pending := hy2Deltas{}
	// acks — подтверждения выполненных заданий, ещё не доставленные панели.
	var acks []Ack

	for {
		// Следующий снимок отсчитываем от начала этого: панель держит ответ
		// до появления задания, и это ожидание не должно сдвигать ритм.
		next := time.Now().Add(interval)
		cycleCtx, cancel := context.WithTimeout(ctx, 45*time.Second)
		snap := collect(cycleCtx, cfg, account)
		if snap.Hy2.Cleared {
			pending.add(snap.Hy2.Traffic)
			snap.Hy2.Traffic = pending.json()
		}
		snap.Acks = acks
		answer, err := send(cycleCtx, cfg, snap)
		cancel()

		ranTasks := false
		if err != nil {
			failures++
			// Первую ошибку и каждую десятую — в журнал; остальные молча,
			// иначе лежащая панель заспамит journald за полчаса.
			if failures == 1 || failures%10 == 0 {
				log.Printf("панель не приняла снимок (%d подряд): %v", failures, err)
			}
		} else {
			if failures > 0 {
				log.Printf("панель снова принимает снимки (после %d сбоев)", failures)
				failures = 0
			}
			if snap.Hy2.Cleared {
				pending = hy2Deltas{}
			}
			acks = nil
			if len(answer.Tasks) > 0 {
				taskCtx, cancelTasks := context.WithTimeout(ctx, 60*time.Second)
				acks = runTasks(taskCtx, cfg, answer.Tasks)
				cancelTasks()
				ranTasks = true
				failed := 0
				for _, a := range acks {
					if !a.OK {
						failed++
					}
				}
				log.Printf("заданий панели: %d, с ошибкой: %d", len(acks), failed)
			}
			if answer.Account != account {
				account = answer.Account
				if account {
					log.Print("панель зачисляет трафик по снимкам: счётчики Hysteria2 обнуляем сами")
				} else {
					log.Print("панель больше не зачисляет по снимкам: счётчики Hysteria2 только читаем")
					pending = hy2Deltas{}
				}
			}
			got := answer.Interval
			if got >= 5 && got <= 300 && time.Duration(got)*time.Second != interval {
				interval = time.Duration(got) * time.Second
				log.Printf("панель просит интервал %ds", got)
			}
		}

		if time.Since(lastSummary) >= 10*time.Minute {
			lastSummary = time.Now()
			log.Print(summary(snap))
		}

		// Выполнили задания — подтверждаем сразу, следующим снимком.
		if ranTasks {
			continue
		}
		wait := time.Until(next)
		if wait < 0 {
			wait = 0
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(wait):
		}
	}
}

// summary — одна строка о состоянии узла для журнала: что видно с первого взгляда.
func summary(s *Snapshot) string {
	peers := 0
	for _, iface := range s.AWG {
		peers += iface.Peers
	}
	return fmt.Sprintf(
		"снимок: awg %d интерфейс(ов), %d пиров; xray %s, онлайн %d; hy2 %s; сбор %d мс",
		len(s.AWG), peers, okWord(s.Xray.OK), s.Xray.OnlineCount, okWord(s.Hy2.OK), s.TookMS,
	)
}

func okWord(ok bool) string {
	if ok {
		return "ok"
	}
	return "ПРОБЛЕМА"
}

// hy2Deltas — накопленные дельты Hysteria2 по учёткам: ответ /traffic —
// {"<label>": {"tx": N, "rx": M}, …}. Складываем, пока панель не приняла.
type hy2Deltas map[string]map[string]int64

func (d hy2Deltas) add(raw json.RawMessage) {
	if len(raw) == 0 {
		return
	}
	var fresh map[string]map[string]int64
	if err := json.Unmarshal(raw, &fresh); err != nil {
		return
	}
	for label, pair := range fresh {
		sum := d[label]
		if sum == nil {
			sum = map[string]int64{}
			d[label] = sum
		}
		for key, value := range pair {
			sum[key] += value
		}
	}
}

func (d hy2Deltas) json() json.RawMessage {
	if len(d) == 0 {
		return json.RawMessage("{}")
	}
	raw, err := json.Marshal(d)
	if err != nil {
		return json.RawMessage("{}")
	}
	return raw
}
