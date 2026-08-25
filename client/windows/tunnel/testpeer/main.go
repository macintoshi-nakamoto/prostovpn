/* SPDX-License-Identifier: MIT
 *
 * Локальный пир для проверки живого рукопожатия в CI.
 *
 * Поднимает userspace-узел AmneziaWG (netstack, без прав и драйверов)
 * на loopback с теми же параметрами маскировки, что выдаёт Amnezia
 * (диапазоны H1-H4, S1-S4, junk-пакеты), генерирует обе пары ключей
 * и пишет готовый клиентский конфиг. Служба туннеля подключается к нему
 * по-настоящему: через сокеты Windows, с junk-пакетами и паддингом.
 */

package main

import (
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"flag"
	"fmt"
	"net/netip"
	"os"

	"golang.org/x/crypto/curve25519"

	"github.com/amnezia-vpn/amneziawg-go/v3/conn"
	"github.com/amnezia-vpn/amneziawg-go/v3/device"
	"github.com/amnezia-vpn/amneziawg-go/v3/tun/netstack"
)

// Параметры маскировки как в реальных ключах Amnezia 2.x — с диапазонами
// магических заголовков. Значения из поля, на которых ловились регрессии.
const obfUAPI = `jc=4
jmin=230
jmax=649
s1=56
s2=149
s3=36
s4=12
h1=142296167-142319474
h2=1851705944-1851738794
h3=2806777913-2806827275
h4=3821906136-3821927050
`

const obfConf = `Jc = 4
Jmin = 230
Jmax = 649
S1 = 56
S2 = 149
S3 = 36
S4 = 12
H1 = 142296167-142319474
H2 = 1851705944-1851738794
H3 = 2806777913-2806827275
H4 = 3821906136-3821927050
`

func genKey() (priv, pub []byte) {
	priv = make([]byte, 32)
	rand.Read(priv)
	priv[0] &= 248
	priv[31] = (priv[31] & 127) | 64
	pub, _ = curve25519.X25519(priv, curve25519.Basepoint)
	return priv, pub
}

func main() {
	port := flag.Int("port", 39999, "UDP-порт пира на loopback")
	confOut := flag.String("conf-out", "live.conf", "куда положить клиентский конфиг")
	flag.Parse()

	peerPriv, peerPub := genKey()
	clientPriv, clientPub := genKey()

	clientConf := fmt.Sprintf(`[Interface]
Address = 10.9.7.2/32
PrivateKey = %s
MTU = 1280
%s
[Peer]
PublicKey = %s
AllowedIPs = 10.9.7.1/32
Endpoint = 127.0.0.1:%d
PersistentKeepalive = 1
`,
		base64.StdEncoding.EncodeToString(clientPriv),
		obfConf,
		base64.StdEncoding.EncodeToString(peerPub),
		*port,
	)
	if err := os.WriteFile(*confOut, []byte(clientConf), 0o600); err != nil {
		fmt.Fprintln(os.Stderr, "conf-out:", err)
		os.Exit(1)
	}

	tun, _, err := netstack.CreateNetTUN(
		[]netip.Addr{netip.MustParseAddr("10.9.7.1")},
		[]netip.Addr{netip.MustParseAddr("1.1.1.1")},
		1280,
	)
	if err != nil {
		fmt.Fprintln(os.Stderr, "netstack:", err)
		os.Exit(1)
	}

	dev := device.NewDevice(tun, conn.NewDefaultBind(), device.NewLogger(device.LogLevelVerbose, "peer "))
	uapi := fmt.Sprintf("private_key=%s\nlisten_port=%d\n%sreplace_peers=true\npublic_key=%s\nallowed_ip=10.9.7.2/32\n",
		hex.EncodeToString(peerPriv),
		*port,
		obfUAPI,
		hex.EncodeToString(clientPub),
	)
	if err := dev.IpcSet(uapi); err != nil {
		fmt.Fprintln(os.Stderr, "IpcSet:", err)
		os.Exit(1)
	}
	if err := dev.Up(); err != nil {
		fmt.Fprintln(os.Stderr, "Up:", err)
		os.Exit(1)
	}

	fmt.Println("PEER READY")
	select {}
}
