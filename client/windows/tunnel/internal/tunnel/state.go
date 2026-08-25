/* SPDX-License-Identifier: MIT
 *
 * Состояние туннеля для приложения Prosto VPN.
 */

package tunnel

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/amnezia-vpn/amneziawg-go/v3/device"
)

/*
Выкладывает состояние туннеля рядом с конфигурацией.

«Служба запущена» ещё не значит «VPN работает»: адаптер поднимается и
маршруты ставятся до первого рукопожатия, и если сервер не отвечает, весь
трафик уходит в мёртвый туннель — со стороны это выглядит как «подключено,
но интернета нет». Приложение работает без прав администратора и не может
спросить движок через управляющий канал, поэтому состояние кладём в файл
рядом с конфигом: там у пользователя есть доступ.
*/
func watchState(dev *device.Device, confPath string) {
	statePath := filepath.Join(filepath.Dir(confPath), "state.txt")
	/*
	400 мс, а не две секунды: по этому файлу приложение узнаёт о состоявшемся
	рукопожатии. С редким тиком подключение выглядело медленным на ровном
	месте — сервер отвечал за доли секунды, а кнопка ещё секунды крутилась.
	Файл крошечный, запись идёт через переименование, так что цена низкая.
	*/
	ticker := time.NewTicker(400 * time.Millisecond)
	defer ticker.Stop()

	write := func() {
		handshake, rx, tx := deviceStats(dev)
		body := fmt.Sprintf(
			"handshake=%d\nrx=%d\ntx=%d\nupdated=%d\n",
			handshake, rx, tx, time.Now().Unix(),
		)
		// Пишем через временный файл: приложение читает этот файл на каждом
		// тике таймера и не должно ловить его наполовину записанным.
		tmp := statePath + ".tmp"
		if err := os.WriteFile(tmp, []byte(body), 0o644); err != nil {
			return
		}
		os.Rename(tmp, statePath)
	}

	write()
	for {
		select {
		case <-dev.Wait():
			os.Remove(statePath)
			return
		case <-ticker.C:
			write()
		}
	}
}

/** Последнее рукопожатие (unix-секунды) и счётчики трафика по всем пирам. */
func deviceStats(dev *device.Device) (handshake, rx, tx int64) {
	report, err := dev.IpcGet()
	if err != nil {
		return 0, 0, 0
	}
	for _, line := range strings.Split(report, "\n") {
		key, value, ok := strings.Cut(strings.TrimSpace(line), "=")
		if !ok {
			continue
		}
		number, err := strconv.ParseInt(value, 10, 64)
		if err != nil {
			continue
		}
		switch key {
		case "last_handshake_time_sec":
			// Берём самое свежее: пиров может быть несколько
			if number > handshake {
				handshake = number
			}
		case "rx_bytes":
			rx += number
		case "tx_bytes":
			tx += number
		}
	}
	return handshake, rx, tx
}
