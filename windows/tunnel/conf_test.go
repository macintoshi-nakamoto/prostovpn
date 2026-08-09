package main

import (
	"strings"
	"testing"

	"github.com/prostovpn/prostovpn-tunnel/internal/conf"
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
I1 = <b 0xf6ab3267fa><c><b 0xf6ab><t><r 10>
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

func TestUnknownKeyIsRejected(t *testing.T) {
	// Мобильные ключи приложение обязано отсеивать: движок на них падает
	broken := strings.Replace(amneziaConfig, "[Peer]", "ExcludedApplications = com.foo\n\n[Peer]", 1)
	if _, err := conf.FromWgQuick(broken, "prostovpn"); err == nil {
		t.Fatal("движок принял незнакомый ключ — проверка санитайзера потеряла смысл")
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
