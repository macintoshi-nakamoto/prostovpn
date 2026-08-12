/* SPDX-License-Identifier: MIT
 *
 * Полное отключение туннеля одним вызовом.
 */

package main

import (
	"fmt"
	"time"

	"golang.org/x/sys/windows"

	"github.com/prostovpn/prostovpn-tunnel/internal/tunnel/winipcfg"
)

var (
	dnsapi                  = windows.NewLazySystemDLL("dnsapi.dll")
	procDnsFlushResolverCache = dnsapi.NewProc("DnsFlushResolverCache")
)

/*
Чистит кэш DNS-клиента Windows.

Пока туннель поднят, имена разрешаются через DNS провайдера VPN, и адреса
оседают в кэше на своё время жизни — обычно минуты. После отключения
браузер продолжает ходить по ним, и это выглядит так, будто VPN всё ещё
работает. Прав администратора не требует.
*/
func flushDNSCache() error {
	ret, _, err := procDnsFlushResolverCache.Call()
	if ret == 0 {
		return err
	}
	return nil
}

/** Поднят ли ещё сетевой адаптер туннеля. */
func tunnelAdapterPresent(name string) bool {
	interfaces, err := winipcfg.GetAdaptersAddresses(windows.AF_UNSPEC, winipcfg.GAAFlagDefault)
	if err != nil {
		return false
	}
	for _, iface := range interfaces {
		if iface.FriendlyName() == name {
			return true
		}
	}
	return false
}

/*
Отключает туннель и возвращается только когда он действительно снят.

Одним вызовом, а не цепочкой запусков движка: раньше приложение спрашивало
состояние, потом слало сигнал, потом опрашивало снова — и всё это время
показывало «отключено», хотя адаптер ещё жил и уводил трафик в VPN.

Ждём не остановки службы, а исчезновения адаптера: маршруты снимаются
вместе с ним, и до этого момента трафик идёт в туннель.
*/
func downTunnel(name string) error {
	state, err := tunnelState(name)
	if err != nil {
		return err
	}

	if state == "RUNNING" || state == "STARTING" {
		// Служба останавливает себя сама — прав это не требует
		if err := signalStop(); err != nil {
			return fmt.Errorf("сигнал остановки не дошёл: %w", err)
		}
	}

	deadline := time.Now().Add(20 * time.Second)
	for time.Now().Before(deadline) {
		state, err := tunnelState(name)
		stopped := err == nil && (state == "STOPPED" || state == "ABSENT")
		if stopped && !tunnelAdapterPresent(name) {
			// Кэш чистим последним: пока адаптер жив, DNS туннеля ещё
			// может успеть положить в кэш свежую запись.
			if flushErr := flushDNSCache(); flushErr != nil {
				return fmt.Errorf("туннель снят, но кэш DNS не очищен: %w", flushErr)
			}
			return nil
		}
		time.Sleep(150 * time.Millisecond)
	}
	return fmt.Errorf("туннель не снялся за 20 секунд")
}
