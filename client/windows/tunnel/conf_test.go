package main

import (
	"strings"
	"testing"

	"golang.org/x/sys/windows"

	"github.com/prostovpn/prostovpn-tunnel/internal/conf"
	"github.com/prostovpn/prostovpn-tunnel/internal/tunnel/winipcfg"
)

/*
Конфиг, который приложение собирает из ключа Amnezia.

Разбор здесь строгий: незнакомый ключ — ошибка всего конфига, поэтому
набор параметров обфускации должен совпадать с тем, что оставляет
`WgConfig.sanitize` в приложении.
*/
const amneziaConfig = `[Interface]
Address = 10.8.1.5/32
DNS = 1.1.1.1
PrivateKey = AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=
Jc = 4
Jmin = 40
Jmax = 70
S1 = 84
S2 = 43
S3 = 20
S4 = 15
H1 = 1234567891
H2 = 1234567892
H3 = 1234567893
H4 = 1234567894
I1 = <b 0xf6ab3267fa><b 0xf6ab><t><r 10>
I2 = <b 0x11223344><t>
I3 = <b 0x55667788><r 4>
MTU = 1376

[Peer]
PublicKey = 1m8v/lROKRSJTeZbV81vZNZi2NZZX4BGU3OcLWqbvxE=
PresharedKey = NQ6YcjnQlbwCtIYEXWmCf8yPdik1pxb5KtCzzvqwBEI=
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = 203.0.113.77:41820
PersistentKeepalive = 25
`

func TestAmneziaConfigParses(t *testing.T) {
	c, err := conf.FromWgQuick(amneziaConfig, "prostovpn")
	if err != nil {
		t.Fatalf("конфиг не разобран: %v", err)
	}
	if len(c.Peers) != 1 {
		t.Fatalf("ожидали одного пира, получили %d", len(c.Peers))
	}
	if len(c.Interface.Addresses) != 1 {
		t.Fatalf("потерян Address")
	}
	if c.Interface.MTU != 1376 {
		t.Fatalf("MTU = %d", c.Interface.MTU)
	}

	// Параметры обфускации должны дойти до движка целиком: без них
	// сервер AmneziaWG не отвечает на рукопожатие.
	uapi, err := c.ToUAPI()
	if err != nil {
		t.Fatalf("UAPI не собран: %v", err)
	}
	for _, want := range []string{
		"jc=4", "jmin=40", "jmax=70",
		"s1=84", "s2=43", "s3=20", "s4=15",
		"h1=1234567891", "h4=1234567894",
		"i1=<b 0xf6ab3267fa>", "i2=<b 0x11223344>", "i3=<b 0x55667788>",
		"allowed_ip=0.0.0.0/0", "allowed_ip=::/0",
		"persistent_keepalive_interval=25",
	} {
		if !strings.Contains(uapi, want) {
			t.Errorf("в UAPI нет %q", want)
		}
	}
}

/*
Ключи из конфига должны совпадать с тем, что принимает движок протокола:
UAPI отвергает весь набор целиком («invalid UAPI device key»), поэтому
лишний ключ ломает подключение так же надёжно, как отсутствующий.
*/
func TestUAPIKeysAreAcceptedByDevice(t *testing.T) {
	accepted := map[string]bool{
		"private_key": true, "listen_port": true, "fwmark": true,
		"replace_peers": true, "jc": true, "jmin": true, "jmax": true,
		"s1": true, "s2": true, "s3": true, "s4": true,
		"h1": true, "h2": true, "h3": true, "h4": true,
		"i1": true, "i2": true, "i3": true, "i4": true, "i5": true,
		// секция пира
		"public_key": true, "preshared_key": true, "endpoint": true,
		"persistent_keepalive_interval": true, "replace_allowed_ips": true,
		"allowed_ip": true, "protocol_version": true, "update_only": true,
		"remove": true,
	}

	c, err := conf.FromWgQuick(amneziaConfig, "prostovpn")
	if err != nil {
		t.Fatalf("конфиг не разобран: %v", err)
	}
	uapi, err := c.ToUAPI()
	if err != nil {
		t.Fatalf("UAPI не собран: %v", err)
	}
	for _, line := range strings.Split(uapi, "\n") {
		if line == "" {
			continue
		}
		key, _, ok := strings.Cut(line, "=")
		if !ok {
			t.Fatalf("строка UAPI без «=»: %q", line)
		}
		if !accepted[key] {
			t.Errorf("движок не примет ключ %q (строка %q)", key, line)
		}
	}
}

/*
KillSwitch = off приложение пишет по настройке пользователя и при
раздельном туннелировании: blockAll движка конфликтует с обвязками на
WinDivert (zapret) — их переинжектированные пакеты теряют привязку к
процессу, и брандмауэр глушит наше же рукопожатие.
*/
func TestKillSwitchKeyParses(t *testing.T) {
	c, err := conf.FromWgQuick(amneziaConfig, "prostovpn")
	if err != nil {
		t.Fatalf("конфиг не разобран: %v", err)
	}
	if c.Interface.KillSwitchOff {
		t.Fatal("без ключа kill switch должен остаться включённым")
	}

	withOff := strings.Replace(amneziaConfig, "MTU = 1376", "MTU = 1376\nKillSwitch = off", 1)
	c, err = conf.FromWgQuick(withOff, "prostovpn")
	if err != nil {
		t.Fatalf("KillSwitch = off не разобран: %v", err)
	}
	if !c.Interface.KillSwitchOff {
		t.Fatal("KillSwitch = off потерян при разборе")
	}
	// Значение — не для UAPI: это указание службе, а не движку протокола
	uapi, err := c.ToUAPI()
	if err != nil {
		t.Fatalf("UAPI не собран: %v", err)
	}
	if strings.Contains(strings.ToLower(uapi), "killswitch") {
		t.Fatal("KillSwitch просочился в UAPI")
	}

	if _, err := conf.FromWgQuick(strings.Replace(amneziaConfig,
		"MTU = 1376", "MTU = 1376\nKillSwitch = banana", 1), "prostovpn"); err == nil {
		t.Fatal("мусорное значение KillSwitch принято")
	}
}

/*
Скрипты обязаны отвергаться разбором, а не «выключаться по умолчанию».

Служба туннеля остаётся установленной и запускается обычным пользователем
без прав, а конфиг лежит в его профиле. Поддержи движок PreUp/PostUp — и
любой, кто сидит за машиной, выполнил бы команду от имени SYSTEM.
*/
func TestScriptKeysAreRejected(t *testing.T) {
	for _, key := range []string{"PreUp", "PostUp", "PreDown", "PostDown"} {
		broken := strings.Replace(amneziaConfig, "MTU = 1376",
			"MTU = 1376\n"+key+" = calc.exe", 1)
		if _, err := conf.FromWgQuick(broken, "prostovpn"); err == nil {
			t.Errorf("движок принял %s — это выполнение команд от имени SYSTEM", key)
		}
	}
}

func TestUnknownKeyIsRejected(t *testing.T) {
	// Мобильные ключи приложение обязано отсеивать: движок на них падает
	broken := strings.Replace(amneziaConfig, "[Peer]", "ExcludedApplications = com.foo\n\n[Peer]", 1)
	if _, err := conf.FromWgQuick(broken, "prostovpn"); err == nil {
		t.Fatal("движок принял незнакомый ключ — проверка санитайзера потеряла смысл")
	}
}

/*
Права на службу должны разбираться Windows и давать интерактивному
пользователю запуск и остановку — на этом держится подключение без UAC.

Опечатка в SDDL иначе всплыла бы только на живой машине: выдача прав
не критична и лишь пишется в отчёт установки.
*/
func TestTunnelServiceSDDLIsValid(t *testing.T) {
	sd, err := windows.SecurityDescriptorFromString(tunnelServiceSDDL)
	if err != nil {
		t.Fatalf("Windows не понимает права службы: %v", err)
	}
	dacl, _, err := sd.DACL()
	if err != nil {
		t.Fatalf("список прав не читается: %v", err)
	}
	if dacl == nil {
		t.Fatal("список прав пуст — служба осталась бы без ограничений")
	}

	back := sd.String()
	for _, want := range []string{
		";;;SY)", // SYSTEM
		";;;BA)", // администраторы
		";;;IU)", // тот, кто сидит за машиной
	} {
		if !strings.Contains(back, want) {
			t.Errorf("в правах нет %s: %s", want, back)
		}
	}
	// Всем подряд права давать нельзя: службу запускают и по сети
	for _, forbidden := range []string{";;;AU)", ";;;WD)", ";;;BU)"} {
		if strings.Contains(back, forbidden) {
			t.Errorf("права выданы слишком широко (%s): %s", forbidden, back)
		}
	}
}

/*
Командная строка должна совпадать с тем, что Windows отдаёт в
BinaryPathName, байт в байт.

По ней решается, можно ли просто запустить уже установленную службу.
Не совпало — приложение считает службу чужой и лезет за правами
администратора. Так и было: %q экранировал обратные слэши, сверка не
совпадала никогда, и UAC появлялся на каждом подключении.
*/
func TestServiceCommandLineMatchesWindows(t *testing.T) {
	const exe = `C:\Program Files\Prosto VPN\app\resources\prostovpn-tunnel.exe`
	const cfg = `C:\Users\Egorik\AppData\Local\ProstoVPN\prostovpn.conf`

	// Ровно эта строка лежит в PathName живой службы
	const fromWindows = `"C:\Program Files\Prosto VPN\app\resources\prostovpn-tunnel.exe"` +
		` /service C:\Users\Egorik\AppData\Local\ProstoVPN\prostovpn.conf`

	got := serviceCommandLine(exe, cfg)
	if got != fromWindows {
		t.Errorf("не совпадает с Windows:\n  собрали: %s\n  Windows: %s", got, fromWindows)
	}
	if strings.Contains(got, `\\`) {
		t.Errorf("обратные слэши экранированы — сверка пути не совпадёт: %s", got)
	}
}

/*
Кэш DNS должен чиститься при отключении и без прав администратора.

Пока туннель поднят, имена разрешаются через DNS провайдера VPN и оседают
в кэше на своё время жизни — обычно минуты. Не почистив его, после
отключения браузер продолжает ходить по адресам из VPN, и это выглядит
так, будто туннель ещё работает.
*/
func TestDNSCacheFlushWorksWithoutAdmin(t *testing.T) {
	if err := flushDNSCache(); err != nil {
		t.Fatalf("кэш DNS не чистится: %v", err)
	}
}

/*
Проверка адаптера — то, по чему отключение понимает, что туннель снят.
Маршруты уходят вместе с адаптером, поэтому ждать надо именно его.
*/
func TestTunnelAdapterLookup(t *testing.T) {
	if tunnelAdapterPresent("заведомо-несуществующий-адаптер-9f3a") {
		t.Fatal("найден адаптер, которого нет")
	}
	// Хотя бы один адаптер в системе есть всегда — значит перебор работает
	interfaces, err := winipcfg.GetAdaptersAddresses(windows.AF_UNSPEC, winipcfg.GAAFlagDefault)
	if err != nil {
		t.Skipf("список адаптеров недоступен: %v", err)
	}
	if len(interfaces) == 0 {
		t.Skip("в системе нет адаптеров")
	}
	if !tunnelAdapterPresent(interfaces[0].FriendlyName()) {
		t.Errorf("существующий адаптер %q не найден", interfaces[0].FriendlyName())
	}
}

func TestServiceNameIsOurs(t *testing.T) {
	name, err := tunnelServiceName("prostovpn")
	if err != nil {
		t.Fatal(err)
	}
	if name != `ProstoVPNTunnel$prostovpn` {
		t.Fatalf("имя службы чужое: %s", name)
	}
}
