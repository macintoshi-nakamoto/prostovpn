package com.prostovpn.app

import org.junit.Assert.assertEquals
import org.junit.Test

class EndpointsTest {
    private val config = """
        [Interface]
        Address = 10.8.1.28/32
        PrivateKey = CBGz7PwpuUX4iER0T59QNT4UtwpTeptpWuOcvNN0r1c=
        DNS = 1.1.1.1, 1.0.0.1
        MTU = 1280
        Jc = 10
        Jmin = 39
        Jmax = 628
        S1 = 27
        S2 = 140
        H1 = 522668942
        H2 = 1626372724
        H3 = 1116046423
        H4 = 129443659

        [Peer]
        PublicKey = nV0ZUJvb+1nW5YGzkQI4//ZRp/PdeZSv+FS813zp6lU=
        AllowedIPs = 0.0.0.0/0, ::/0
        Endpoint = 45.151.106.253:51820
        PersistentKeepalive = 25
    """.trimIndent()

    @Test
    fun `порт читается из конфига`() {
        assertEquals(51820, Endpoints.portOf(config))
    }

    @Test
    fun `подмена порта не трогает остальное`() {
        val moved = Endpoints.withPort(config, 443)
        assertEquals("Endpoint = 45.151.106.253:443", moved.lineSequence().first { it.startsWith("Endpoint") })

        assertEquals(
            config.lines().filterNot { it.startsWith("Endpoint") },
            moved.lines().filterNot { it.startsWith("Endpoint") },
        )
    }

    @Test
    fun `имя узла вместо адреса тоже переписывается`() {
        val named = config.replace("45.151.106.253:51820", "nl.example.com:51820")
        assertEquals(51820, Endpoints.portOf(named))
        assertEquals(
            "Endpoint = nl.example.com:2408",
            Endpoints.withPort(named, 2408).lineSequence().first { it.startsWith("Endpoint") },
        )
    }

    @Test
    fun `эндпоинт без порта получает порт`() {
        val bare = config.replace("45.151.106.253:51820", "45.151.106.253")
        assertEquals(0, Endpoints.portOf(bare))
        assertEquals(
            "Endpoint = 45.151.106.253:443",
            Endpoints.withPort(bare, 443).lineSequence().first { it.startsWith("Endpoint") },
        )
    }

    @Test
    fun `сработавший порт идёт первым, дубликатов нет`() {
        assertEquals(listOf(443, 51820, 2408), Endpoints.order(51820, 443, listOf(443, 2408, 51820)))
    }

    @Test
    fun `без запомненного порта первым идёт порт из конфига`() {
        assertEquals(listOf(51820, 443, 2408), Endpoints.order(51820, 0, listOf(443, 2408)))
    }

    @Test
    fun `перебирать нечего — список пуст`() {
        assertEquals(emptyList<Int>(), Endpoints.order(0, 0, emptyList()))
    }
}
