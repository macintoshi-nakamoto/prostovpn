package com.prostovpn.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * Раздельное туннелирование может **оставить** лишнюю подсеть в VPN, но не
 * может **выкинуть** из VPN адрес, которого нет в списке исключений.
 *
 * Так ломался Telegram: огрубление раздувало российские куски
 * 149.154.64-143 до целого 149.154.0.0/16 и уносило с собой
 * 149.154.160.0/20 — дата-центр Telegram, в списке не значившийся.
 */
class SplitTunnelTest {

    /** Встроенный список исключений — тот же файл, что уходит в APK. */
    private fun listContent(): String {
        val asset = File("src/main/assets/ru-split-tunnel.json")
        assertTrue("нет списка исключений: ${asset.absolutePath}", asset.isFile)
        return asset.readText()
    }

    @Test
    fun `сервера Telegram остаются в туннеле`() {
        val excluded = SplitTunnel.parseCidrList(listContent())
        assertTrue("список подозрительно мал: ${excluded.size}", excluded.size > 1000)

        val allowed = toRanges(SplitTunnel.complement(excluded))
        val excludedRanges = toRanges(excluded)

        for ((name, ip) in mapOf(
            "Telegram DC 149.154.167.51" to "149.154.167.51",
            "Telegram DC 149.154.175.50" to "149.154.175.50",
            "Telegram 91.108.56.130" to "91.108.56.130",
            "Cloudflare 1.1.1.1" to "1.1.1.1",
            "Google DNS 8.8.8.8" to "8.8.8.8",
            "GitHub 140.82.121.3" to "140.82.121.3",
        )) {
            val value = ipToLong(ip)!!
            if (inRanges(excludedRanges, value)) continue // исключён намеренно
            assertTrue("$name выкинут из VPN, хотя не исключён", inRanges(allowed, value))
        }
    }

    @Test
    fun `огрубление не выталкивает из VPN ничего лишнего`() {
        val excluded = SplitTunnel.parseCidrList(listContent())
        val excludedRanges = toRanges(excluded)
        val allowed = toRanges(SplitTunnel.complement(excluded))

        var checked = 0
        var firstLost: String? = null
        var probe = 1L
        while (probe < 0xFFFFFFFFL) {
            if (!inRanges(excludedRanges, probe) && !inRanges(allowed, probe) && firstLost == null) {
                firstLost = longToIp(probe)
            }
            checked++
            probe += 997 // простой шаг — не попадаем в кратности сетки
        }
        assertTrue("проверено слишком мало адресов: $checked", checked > 1_000_000)
        assertEquals("огрубление вытолкнуло адрес из VPN", null, firstLost)
    }

    @Test
    fun `маршрутов не больше, чем система выдержит`() {
        val routes = SplitTunnel.complement(SplitTunnel.parseCidrList(listContent()))
        assertTrue("маршрутов слишком много: ${routes.size}", routes.size <= 2500)
        assertFalse("список маршрутов пуст", routes.isEmpty())
    }

    @Test
    fun `огрубление не уводит в VPN сервисы, ради которых всё затевалось`() {
        /*
        Обратная сторона предыдущего теста, и без неё он был однобоким: тот
        следит, чтобы из VPN не вылетело чужое, а этот — чтобы в VPN не
        провалилось своё. Именно это и случилось на боевом списке: огрубление
        до сетки /18 выбрасывало 34% российского пространства, а с ним Ozon,
        Кинопоиск, Сбербанк, Wildberries и Avito. Приложение показывало
        «подключено», а магазины и банки переставали работать.
        */
        val excluded = SplitTunnel.parseCidrList(listContent())
        val excludedRanges = toRanges(excluded)
        val allowed = toRanges(SplitTunnel.complement(excluded))

        val services = mapOf(
            "Ozon" to "185.73.193.68",
            "Ozon Банк (оплата)" to "194.9.211.128",
            "Кинопоиск" to "213.180.199.9",
            "Яндекс" to "77.88.55.88",
            "Сбербанк" to "84.252.149.206",
            "Т-Банк" to "178.130.128.27",
            "Wildberries" to "185.62.202.2",
            "Avito" to "176.114.120.24",
            "Госуслуги" to "213.59.253.7",
            "VK" to "87.240.129.133",
        )
        val lost = services.filter { (_, ip) ->
            val value = ipToLong(ip)!!
            // Сервис в списке исключений, но после огрубления попал в туннель.
            inRanges(excludedRanges, value) && inRanges(allowed, value)
        }
        assertEquals("огрубление увело эти сервисы в VPN, они перестанут работать", emptyMap<String, String>(), lost)
    }

    @Test
    fun `при раздельном туннелировании IPv6 не утекает мимо VPN`() {
        /*
        Раньше без v6-адреса ::/0 не добавляли, боясь чёрной дыры. Но библиотека
        (GoBackend.setStateInternal) при ОТСУТСТВИИ маски 0 среди AllowedIPs зовёт
        allowFamily(AF_INET6), который разблокирует IPv6 при полном отсутствии
        IPv6-маршрутов: весь IPv6 уходил мимо туннеля с настоящим адресом абонента.
        На мобильных сетях с IPv6 двухстековые сайты видели реальную страну.
        Маска 0 в списке гасит этот вызов, поэтому ::/0 нужен всегда.
        */
        val allowed = SplitTunnel.allowedIpsExcept(listOf("87.240.128.0/18"))
        assertTrue("::/0 обязателен: без него срабатывает allowFamily(AF_INET6)", "::/0" in allowed)

        val masks = allowed.split(", ").mapNotNull { it.substringAfter('/', "").toIntOrNull() }
        assertTrue("нужна хотя бы одна маска 0, иначе IPv6 разблокируется", masks.any { it == 0 })
    }

    @Test
    fun `DNS подставляется только когда сервер его не задал`() {
        val withoutDns = """
            [Interface]
            Address = 10.8.1.3/32
            PrivateKey = aaa=

            [Peer]
            Endpoint = 1.2.3.4:51820
        """.trimIndent()
        val patched = SplitTunnel.ensureDns(withoutDns)
        assertTrue("DNS должен появиться", "DNS = ${SplitTunnel.FALLBACK_DNS}" in patched)
        // Строка обязана попасть в [Interface], иначе парсер её не увидит
        val interfacePart = patched.substringAfter("[Interface]").substringBefore("[Peer]")
        assertTrue("DNS оказался вне [Interface]", "DNS" in interfacePart)

        val withDns = """
            [Interface]
            Address = 10.8.1.3/32
            DNS = 9.9.9.9
        """.trimIndent()
        assertEquals("свой DNS сервера трогать нельзя", withDns, SplitTunnel.ensureDns(withDns))
    }

    @Test
    fun `applyToConfig заворачивает весь IPv6 при полном туннеле`() {
        // Регресс-защита: сервер раздаёт AllowedIPs с ::/0, клиент при полном
        // туннеле обязан его сохранить. Без ::/0 библиотека зовёт
        // allowFamily(AF_INET6), и IPv6 утекает мимо VPN с реальным адресом —
        // на Huawei с IPv6-сетью это «страна не меняется». Проверяем саму
        // подстановку полного маршрута, на которой строится buildConfigForConnect.
        val base = """
            [Interface]
            Address = 10.8.1.18/32
            PrivateKey = aaa=

            [Peer]
            PublicKey = bbb=
            AllowedIPs = 0.0.0.0/0, ::/0
            Endpoint = 45.151.106.253:51820
        """.trimIndent()

        val full = SplitTunnel.applyToConfig(base, "0.0.0.0/0, ::/0")
        val allowed = full.lineSequence().first { it.trim().startsWith("AllowedIPs") }
        assertTrue("::/0 обязателен даже без v6-адреса, иначе IPv6 течёт мимо VPN", "::/0" in allowed)
        assertTrue("IPv4 тоже должен идти в туннель", "0.0.0.0/0" in allowed)
        // Ровно одна строка AllowedIPs: движок берёт первую, лишние — мусор.
        assertEquals(1, full.lineSequence().count { it.trim().startsWith("AllowedIPs") })
    }

    @Test
    fun `MTU подставляется только когда сервер его не задал`() {
        val withoutMtu = """
            [Interface]
            Address = 10.8.1.3/32
            PrivateKey = aaa=

            [Peer]
            Endpoint = 1.2.3.4:51820
        """.trimIndent()
        val patched = SplitTunnel.ensureMtu(withoutMtu)
        assertTrue("MTU должен появиться", "MTU = ${SplitTunnel.FALLBACK_MTU}" in patched)
        // Строка обязана попасть в [Interface], иначе парсер её не увидит
        val interfacePart = patched.substringAfter("[Interface]").substringBefore("[Peer]")
        assertTrue("MTU оказался вне [Interface]", "MTU" in interfacePart)

        val withMtu = """
            [Interface]
            Address = 10.8.1.3/32
            MTU = 1420
        """.trimIndent()
        assertEquals("свой MTU сервера трогать нельзя", withMtu, SplitTunnel.ensureMtu(withMtu))
    }

    @Test
    fun `наличие IPv6-адреса определяется по конфигу`() {
        val v4only = """
            [Interface]
            Address = 10.8.1.3/32
            DNS = 1.1.1.1
        """.trimIndent()
        val dual = """
            [Interface]
            Address = 10.8.1.3/32, fd58:baa6:dead::1
            DNS = 1.1.1.1
        """.trimIndent()
        assertFalse("у IPv4-конфига нет v6-адреса", SplitTunnel.hasIpv6Address(v4only))
        assertTrue("двойной конфиг имеет v6-адрес", SplitTunnel.hasIpv6Address(dual))
    }

    // --- вспомогательное ---

    private fun ipToLong(text: String): Long? {
        val parts = text.split(".")
        if (parts.size != 4) return null
        var value = 0L
        for (part in parts) {
            val n = part.toIntOrNull() ?: return null
            if (n !in 0..255) return null
            value = (value shl 8) or n.toLong()
        }
        return value
    }

    private fun longToIp(value: Long) =
        "${(value shr 24) and 255}.${(value shr 16) and 255}.${(value shr 8) and 255}.${value and 255}"

    private fun toRanges(cidrs: List<String>): List<LongRange> {
        val parsed = cidrs.mapNotNull { cidr ->
            val base = ipToLong(cidr.substringBefore('/')) ?: return@mapNotNull null
            val prefix = cidr.substringAfter('/', "32").toIntOrNull() ?: return@mapNotNull null
            if (prefix == 0) 0L..0xFFFFFFFFL
            else {
                val mask = (0xFFFFFFFFL shl (32 - prefix)) and 0xFFFFFFFFL
                val start = base and mask
                start..(start or ((1L shl (32 - prefix)) - 1))
            }
        }.sortedBy { it.first }

        val merged = ArrayList<LongRange>(parsed.size)
        for (r in parsed) {
            val last = merged.lastOrNull()
            if (last != null && r.first <= last.last + 1) {
                merged[merged.size - 1] = last.first..maxOf(last.last, r.last)
            } else {
                merged.add(r)
            }
        }
        return merged
    }

    private fun inRanges(ranges: List<LongRange>, value: Long): Boolean {
        var low = 0
        var high = ranges.size - 1
        while (low <= high) {
            val mid = (low + high) ushr 1
            val r = ranges[mid]
            when {
                value < r.first -> high = mid - 1
                value > r.last -> low = mid + 1
                else -> return true
            }
        }
        return false
    }
}
