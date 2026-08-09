/* SPDX-License-Identifier: MIT
 *
 * Собственный движок туннеля Prosto VPN.
 *
 * Приложение больше не зависит от установленной Amnezia: этот исполняемый
 * файл сам поднимает адаптер Wintun, регистрирует службу Windows под нашим
 * именем и ведёт свой журнал. Внутри — реализация протокола AmneziaWG
 * (amneziawg-go, MIT) и обвязка службы, доработанная из wireguard-windows /
 * amneziawg-windows (MIT), см. THIRD_PARTY_LICENSES.md.
 */

package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
	"unsafe"

	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/svc"
	"golang.org/x/sys/windows/svc/mgr"

	"github.com/prostovpn/prostovpn-tunnel/internal/conf"
	"github.com/prostovpn/prostovpn-tunnel/internal/ringlogger"
	"github.com/prostovpn/prostovpn-tunnel/internal/services"
	"github.com/prostovpn/prostovpn-tunnel/internal/tunnel"
)

const usage = `Prosto VPN tunnel engine

  prostovpn-tunnel /start <config.conf>      (без прав, служба уже стоит)
  prostovpn-tunnel /installtunnelservice <config.conf> [report.log]
  prostovpn-tunnel /uninstalltunnelservice <name>
  prostovpn-tunnel /stop <name>
  prostovpn-tunnel /status <name>
  prostovpn-tunnel /service <config.conf>   (запускается диспетчером служб)
`

/*
Имя события, по которому служба останавливает себя сама.

Иначе отключение требовало бы второго запроса UAC: снять службу может
только администратор. Событие открыто интерактивному пользователю —
тому, кто сидит за этим компьютером и нажал «отключить».
*/
const stopEventName = `Global\ProstoVPN-Tunnel-Stop`

func main() {
	if len(os.Args) < 2 {
		fail(2, usage)
	}

	switch strings.ToLower(os.Args[1]) {
	case "/service":
		// Тело службы: сюда попадаем только из диспетчера служб Windows.
		requireArgs(3)
		runService(os.Args[2])

	case "/installtunnelservice":
		if len(os.Args) != 3 && len(os.Args) != 4 {
			fail(2, usage)
		}
		report := ""
		if len(os.Args) == 4 {
			report = os.Args[3]
		}
		if err := installTunnel(os.Args[2], report); err != nil {
			fail(1, "не удалось поднять туннель: %v", err)
		}

	case "/uninstalltunnelservice":
		requireArgs(3)
		if err := uninstallTunnel(os.Args[2]); err != nil {
			fail(1, "не удалось снять туннель: %v", err)
		}

	case "/start":
		// Обычное подключение: служба уже стоит, прав не требуется
		requireArgs(3)
		if err := startInstalledTunnel(os.Args[2]); err != nil {
			fail(1, "%v", err)
		}

	case "/stop":
		// Мягкая остановка без прав администратора
		requireArgs(3)
		if err := signalStop(); err != nil {
			fail(1, "не удалось остановить туннель: %v", err)
		}

	case "/status":
		requireArgs(3)
		state, err := tunnelState(os.Args[2])
		if err != nil {
			fail(1, "%v", err)
		}
		fmt.Println(state)

	default:
		fail(2, usage)
	}
}

/** Имя службы туннеля — вынесено ради проверки в тестах. */
func tunnelServiceName(name string) (string, error) {
	return services.ServiceNameOfTunnel(name)
}

/*
Командная строка службы туннеля — ровно в том виде, в каком её вернёт
Windows в BinaryPathName.

Собирается вручную, а не через %q: тот экранирует обратные слэши
(C:\\Program Files\\…), сверка с настоящим путём никогда не совпадала,
и подключение каждый раз уходило в установку с правами администратора.
*/
func serviceCommandLine(exePath, configPath string) string {
	return `"` + exePath + `" /service ` + configPath
}

/*
Запускает уже установленную службу туннеля без прав администратора.

Служба остаётся в системе между подключениями, а право на её запуск
выдано интерактивному пользователю при установке — поэтому обычное
подключение обходится без UAC. Возврат ошибки означает «так не вышло,
ставь заново с правами»: службы нет, она от другой сборки или от другого
конфига.
*/
func startInstalledTunnel(configPath string) error {
	name, err := conf.NameFromPath(configPath)
	if err != nil {
		return err
	}
	serviceName, err := services.ServiceNameOfTunnel(name)
	if err != nil {
		return err
	}
	exePath, err := os.Executable()
	if err != nil {
		return err
	}

	/*
	Права запрашиваем минимальные. mgr.Connect() просит у диспетчера служб
	полный доступ, которого обычному пользователю не дают, — отказ наступил бы
	раньше, чем мы дошли до самой службы, и подключение всегда падало бы
	в запрос администратора.
	*/
	serviceName16, err := windows.UTF16PtrFromString(serviceName)
	if err != nil {
		return err
	}
	scm, err := windows.OpenSCManager(nil, nil, windows.SC_MANAGER_CONNECT)
	if err != nil {
		return fmt.Errorf("нет доступа к диспетчеру служб: %w", err)
	}
	defer windows.CloseServiceHandle(scm)

	const access = windows.SERVICE_START |
		windows.SERVICE_QUERY_STATUS |
		windows.SERVICE_QUERY_CONFIG
	handle, err := windows.OpenService(scm, serviceName16, access)
	if err != nil {
		return fmt.Errorf("служба не установлена или запуск не разрешён: %w", err)
	}
	defer windows.CloseServiceHandle(handle)
	service := &mgr.Service{Name: serviceName, Handle: handle}

	/*
	Служба могла остаться от прошлой версии приложения или от другого
	конфига — тогда её нужно пересоздать, а не запускать. Сверяем всю
	командную строку: в ней и путь к движку, и путь к конфигу.
	*/
	cfg, err := service.Config()
	if err != nil {
		return fmt.Errorf("не прочитать настройки службы: %w", err)
	}
	want := serviceCommandLine(exePath, configPath)
	if !strings.EqualFold(strings.TrimSpace(cfg.BinaryPathName), want) {
		return fmt.Errorf("служба от другой сборки или конфига")
	}

	status, err := service.Query()
	if err != nil {
		return fmt.Errorf("не опросить службу: %w", err)
	}
	if status.State == svc.Running || status.State == svc.StartPending {
		return nil
	}

	if err := service.Start(); err != nil {
		return fmt.Errorf("служба не запустилась: %w", err)
	}
	return nil
}

func requireArgs(n int) {
	if len(os.Args) != n {
		fail(2, usage)
	}
}

func fail(code int, format string, args ...any) {
	fmt.Fprintf(os.Stderr, format+"\n", args...)
	os.Exit(code)
}

// --- служба -----------------------------------------------------------------

/*
Тело службы: поднимает туннель и по завершении оставляет читаемый журнал
рядом с конфигурацией.

Кольцевой журнал движка лежит в каталоге, куда пускают только SYSTEM и
администраторов, поэтому приложение его не прочитает. Служба работает от
SYSTEM — она и выкладывает копию туда, откуда приложение читает.
*/
func runService(confPath string) {
	logPath := filepath.Join(filepath.Dir(confPath), "tunnel.log")

	go watchStopEvent(confPath)

	err := tunnel.Run(confPath)

	if file, ferr := os.Create(logPath); ferr == nil {
		if err != nil {
			fmt.Fprintf(file, "! туннель остановился с ошибкой: %v\n\n", err)
		}
		if ringlogger.Global != nil {
			ringlogger.Global.WriteTo(file)
		} else {
			fmt.Fprintln(file, "(журнал движка не открывался)")
		}
		file.Close()
	}

	if err != nil {
		fail(1, "служба туннеля остановилась: %v", err)
	}
}

/** Ждёт сигнал от приложения и штатно останавливает свою же службу. */
func watchStopEvent(confPath string) {
	sa, err := interactiveUserEventAttributes()
	if err != nil {
		return
	}
	name16, err := windows.UTF16PtrFromString(stopEventName)
	if err != nil {
		return
	}
	// Автосброс: сигнал дожидается нас, если приложение выставило событие
	// раньше, чем мы дошли до ожидания, но не остаётся висеть после —
	// иначе следующая служба увидела бы старый сигнал и сразу выключилась.
	event, err := windows.CreateEvent(sa, 0, 0, name16)
	if err != nil {
		return
	}
	defer windows.CloseHandle(event)

	if _, err := windows.WaitForSingleObject(event, windows.INFINITE); err != nil {
		return
	}

	name, err := conf.NameFromPath(confPath)
	if err != nil {
		return
	}
	serviceName, err := services.ServiceNameOfTunnel(name)
	if err != nil {
		return
	}
	m, err := mgr.Connect()
	if err != nil {
		return
	}
	defer m.Disconnect()
	service, err := m.OpenService(serviceName)
	if err != nil {
		return
	}
	defer service.Close()
	service.Control(svc.Stop)
}

/** SYSTEM и администраторы — полный доступ, интерактивный пользователь — только выставить событие. */
func interactiveUserEventAttributes() (*windows.SecurityAttributes, error) {
	const eventModifyStateAndSync = 0x00100002
	sd, err := windows.SecurityDescriptorFromString(
		fmt.Sprintf("O:SYD:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;0x%x;;;IU)", eventModifyStateAndSync),
	)
	if err != nil {
		return nil, err
	}
	return &windows.SecurityAttributes{
		Length:             uint32(unsafe.Sizeof(windows.SecurityAttributes{})),
		SecurityDescriptor: sd,
	}, nil
}

/** Просит службу остановиться — без прав администратора и без запроса UAC. */
func signalStop() error {
	name16, err := windows.UTF16PtrFromString(stopEventName)
	if err != nil {
		return err
	}
	const eventModifyState = 0x0002
	event, err := windows.OpenEvent(eventModifyState, false, name16)
	if err != nil {
		return fmt.Errorf("туннель не отвечает: %w", err)
	}
	defer windows.CloseHandle(event)
	return windows.SetEvent(event)
}

// --- установка службы -------------------------------------------------------

/*
Ставит и запускает службу туннеля.

Требует прав администратора: создание службы и загрузка драйвера Wintun
недоступны обычному пользователю. Служба живёт ровно одно подключение —
её снимает отключение, поэтому туннель не переживает перезагрузку.
*/
func installTunnel(configPath, reportPath string) (err error) {
	var report *os.File
	if reportPath != "" {
		if report, err = os.Create(reportPath); err == nil {
			defer report.Close()
		}
	}
	step := func(format string, args ...any) {
		if report != nil {
			fmt.Fprintf(report, format+"\n", args...)
		}
	}
	defer func() {
		if err != nil {
			step("РЕЗУЛЬТАТ: ОШИБКА — %v", err)
		} else {
			step("РЕЗУЛЬТАТ: туннель запущен")
		}
	}()

	step("Prosto VPN, движок туннеля, %s", time.Now().Format(time.RFC3339))

	configPath, err = filepath.Abs(configPath)
	if err != nil {
		return err
	}
	name, err := conf.NameFromPath(configPath)
	if err != nil {
		return err
	}
	serviceName, err := services.ServiceNameOfTunnel(name)
	if err != nil {
		return err
	}
	step("конфигурация: %s", configPath)
	step("служба: %s", serviceName)

	// Конфиг разбираем до создания службы: так ошибка в ключе видна сразу
	// в отчёте, а не превращается в «служба не запустилась».
	if _, err = conf.LoadFromPath(configPath); err != nil {
		return fmt.Errorf("конфигурация не читается: %w", err)
	}
	step("конфигурация разобрана")

	exePath, err := os.Executable()
	if err != nil {
		return err
	}
	step("движок: %s", exePath)

	m, err := mgr.Connect()
	if err != nil {
		return fmt.Errorf("нет доступа к диспетчеру служб: %w", err)
	}
	defer m.Disconnect()

	if err = removeService(m, serviceName); err != nil {
		return err
	}
	step("прошлая служба снята")

	// Nsi и TcpIp должны подняться раньше нас, иначе настройка адресов
	// и маршрутов падает на старте службы.
	config := mgr.Config{
		ServiceType:  windows.SERVICE_WIN32_OWN_PROCESS,
		StartType:    mgr.StartManual,
		ErrorControl: mgr.ErrorNormal,
		Dependencies: []string{"Nsi", "TcpIp"},
		DisplayName:  "Prosto VPN: " + name,
		Description:  "Tunnel service of Prosto VPN",
		// Свой SID службы нужен правилам брандмауэра (kill switch):
		// они разрешают трафик именно этому процессу.
		SidType: windows.SERVICE_SID_TYPE_UNRESTRICTED,
	}

	service, err := m.CreateService(serviceName, exePath, config, "/service", configPath)
	if err != nil {
		return fmt.Errorf("служба не создалась: %w", err)
	}
	defer service.Close()
	step("служба создана")

	/*
	Пускаем к службе того, кто сидит за машиной. Дальше подключение идёт
	простым стартом службы, без запроса прав: UAC остаётся только на этой
	установке. Право не критично — если не выдалось, следующий запуск
	просто снова спросит администратора.
	*/
	if permErr := allowInteractiveUserToStart(windows.Handle(service.Handle)); permErr != nil {
		step("права на запуск не выданы: %v (подключение будет спрашивать администратора)", permErr)
	} else {
		step("запуск без прав администратора разрешён")
	}

	if err = service.Start(); err != nil {
		// Не оставляем за собой мёртвую службу — иначе следующая попытка
		// упрётся в «служба уже существует».
		service.Delete()
		return fmt.Errorf("служба не запустилась: %w", err)
	}
	step("служба запущена")
	return nil
}

/** Останавливает и удаляет службу туннеля; отсутствие службы — не ошибка. */
func uninstallTunnel(name string) error {
	serviceName, err := services.ServiceNameOfTunnel(name)
	if err != nil {
		return err
	}
	m, err := mgr.Connect()
	if err != nil {
		return fmt.Errorf("нет доступа к диспетчеру служб: %w", err)
	}
	defer m.Disconnect()
	return removeService(m, serviceName)
}

func removeService(m *mgr.Mgr, serviceName string) error {
	service, err := m.OpenService(serviceName)
	if err != nil {
		return nil // службы нет — уже снято
	}

	if status, err := service.Query(); err == nil && status.State != svc.Stopped {
		service.Control(svc.Stop)
		for i := 0; i < 60; i++ {
			status, err := service.Query()
			if err != nil || status.State == svc.Stopped {
				break
			}
			time.Sleep(250 * time.Millisecond)
		}
	}

	deleteErr := service.Delete()
	service.Close()
	if deleteErr != nil && deleteErr != windows.ERROR_SERVICE_MARKED_FOR_DELETE {
		return fmt.Errorf("служба не удалилась: %w", deleteErr)
	}

	// Диспетчер удаляет службу отложенно: пока имя занято, создать новую
	// с тем же именем нельзя. Ждём освобождения имени.
	for i := 0; i < 60; i++ {
		s, err := m.OpenService(serviceName)
		if err != nil {
			return nil
		}
		s.Close()
		time.Sleep(250 * time.Millisecond)
	}
	return fmt.Errorf("служба %s не освободила имя", serviceName)
}

/*
Состояние туннеля одним словом — приложение опрашивает его без PowerShell.

Диспетчер служб открываем с минимальными правами: опрос идёт из обычного,
неповышенного процесса приложения.
*/
func tunnelState(name string) (string, error) {
	serviceName, err := services.ServiceNameOfTunnel(name)
	if err != nil {
		return "", err
	}
	serviceName16, err := windows.UTF16PtrFromString(serviceName)
	if err != nil {
		return "", err
	}

	scm, err := windows.OpenSCManager(nil, nil, windows.SC_MANAGER_CONNECT)
	if err != nil {
		return "", fmt.Errorf("нет доступа к диспетчеру служб: %w", err)
	}
	defer windows.CloseServiceHandle(scm)

	service, err := windows.OpenService(scm, serviceName16, windows.SERVICE_QUERY_STATUS)
	if err != nil {
		return "ABSENT", nil
	}
	defer windows.CloseServiceHandle(service)

	var status windows.SERVICE_STATUS
	if err := windows.QueryServiceStatus(service, &status); err != nil {
		return "", err
	}
	switch status.CurrentState {
	case windows.SERVICE_STOPPED:
		return "STOPPED", nil
	case windows.SERVICE_START_PENDING:
		return "STARTING", nil
	case windows.SERVICE_STOP_PENDING:
		return "STOPPING", nil
	case windows.SERVICE_RUNNING:
		return "RUNNING", nil
	default:
		return fmt.Sprintf("STATE_%d", status.CurrentState), nil
	}
}
