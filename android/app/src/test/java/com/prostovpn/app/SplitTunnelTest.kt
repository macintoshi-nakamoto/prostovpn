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
    fun `IPv6 в туннель попадает только при наличии v6-адреса`() {
        // Без v6-адреса ::/0 добавлять нельзя: иначе IPv6 уходит в чёрную дыру
        val withV6 = SplitTunnel.allowedIpsExcept(listOf("87.240.128.0/18"), includeIpv6 = true)
        val withoutV6 = SplitTunnel.allowedIpsExcept(listOf("87.240.128.0/18"), includeIpv6 = false)
        assertTrue("::/0 ожидался при includeIpv6", "::/0" in withV6)
        assertFalse("::/0 не должно быть без v6-адреса", "::/0" in withoutV6)
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
