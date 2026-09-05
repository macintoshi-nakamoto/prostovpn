// prosto-node — агент на узле Prosto VPN.
//
// Первый шаг: агент только смотрит. Раз в несколько секунд он снимает с узла
// то же, за чем панель ходила по SSH, — пиры AmneziaWG, счётчики и онлайн
// xray, счётчики Hysteria2, живость каждой службы — и сам отправляет снимок
// панели по HTTPS с токеном. Панель ни на что на узле не влияет: ни одной
// команды сюда не приходит, ни один счётчик не обнуляется. Поэтому агент
// можно поставить рядом с обходом по SSH и сверять цифры, а откат — это
// просто выключить службу.
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

const version = "0.1.0"

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
		snap := collect(context.Background(), cfg)
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

	for {
		cycleCtx, cancel := context.WithTimeout(ctx, 45*time.Second)
		snap := collect(cycleCtx, cfg)
		got, err := send(cycleCtx, cfg, snap)
		cancel()

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
			if got >= 5 && got <= 300 && time.Duration(got)*time.Second != interval {
				interval = time.Duration(got) * time.Second
				log.Printf("панель просит интервал %ds", got)
			}
		}

		if time.Since(lastSummary) >= 10*time.Minute {
			lastSummary = time.Now()
			log.Print(summary(snap))
		}

		select {
		case <-ctx.Done():
			return
		case <-time.After(interval):
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
