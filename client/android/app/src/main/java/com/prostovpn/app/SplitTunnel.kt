package com.prostovpn.app

import org.json.JSONArray

object SplitTunnel {
    private data class Range(val start: Long, val end: Long)

    private fun ipToLong(ip: String): Long? {
        val parts = ip.split(".")
        if (parts.size != 4) return null
        var value = 0L
        for (p in parts) {
            val n = p.toIntOrNull() ?: return null
            if (n < 0 || n > 255) return null
            value = (value shl 8) or n.toLong()
        }
        return value
    }

    private fun cidrToRange(cidr: String): Range? {
        val slash = cidr.split("/")
        val ip = ipToLong(slash[0].trim()) ?: return null
        // «1.2.3.4/abc» — битая запись, а не /32: молчаливая подмена маски
        // расширяла бы исключение до одного адреса без ведома пользователя.
        val prefix = if (slash.size > 1) (slash[1].trim().toIntOrNull() ?: return null) else 32
        if (prefix < 0 || prefix > 32) return null
        if (prefix == 0) return Range(0, 0xFFFFFFFFL)
        val mask = (0xFFFFFFFFL shl (32 - prefix)) and 0xFFFFFFFFL
        val start = ip and mask
        val end = start or ((1L shl (32 - prefix)) - 1)
        return Range(start, end)
    }

    private fun longToIp(value: Long): String =
        "${(value shr 24) and 255}.${(value shr 16) and 255}.${(value shr 8) and 255}.${value and 255}"

    private fun rangeToCidrs(start: Long, end: Long, out: MutableList<String>) {
        var s = start
        while (s <= end) {
            val maxAlign = if (s == 0L) 32 else java.lang.Long.numberOfTrailingZeros(s)
            val size = 63 - java.lang.Long.numberOfLeadingZeros(end - s + 1)
            val k = minOf(maxAlign, size)
            out.add("${longToIp(s)}/${32 - k}")
            s += (1L shl k)
        }
    }

    fun parseCidrList(content: String): List<String> {
        val result = ArrayList<String>()
        val parsedJson = runCatching {
            val arr = JSONArray(content)
            for (i in 0 until arr.length()) {
                arr.optJSONObject(i)?.let { obj ->
                    val host = obj.optString("hostname").trim()
                    if (host.isNotEmpty() && cidrToRange(host) != null) result.add(host)
                    return@let
                }
                val str = arr.optString(i).trim()
                if (str.isNotEmpty() && cidrToRange(str) != null) result.add(str)
            }
            true
        }.getOrDefault(false)

        if (!parsedJson) {
            content.lineSequence()
                .map { it.substringBefore('#').trim() }
                .filter { it.isNotEmpty() && cidrToRange(it) != null }
                .forEach { result.add(it) }
        }
        return result
    }

    private const val MAX_ROUTES = 2500

    private val PROTECTED = listOf(
        "5.255.192.0/18",
        "31.130.128.0/19",
        "77.88.0.0/18",
        "80.67.40.0/22",
        "84.252.144.0/21",
        "87.240.128.0/18",
        "89.221.232.0/21",
        "90.156.224.0/19",
        "91.206.126.0/23",
        "91.236.48.0/22",
        "93.186.224.0/20",
        "94.124.192.0/20",
        "95.163.0.0/17",
        "109.238.88.0/22",
        "176.114.112.0/20",
        "178.130.128.0/20",
        "178.176.0.0/14",
        "178.248.232.0/21",
        "185.62.200.0/22",
        "185.73.192.0/22",
        "185.169.152.0/22",
        "185.180.200.0/22",
        "188.162.0.0/16",
        "194.9.208.0/22",
        "195.208.0.0/15",
        "195.242.82.0/23",
        "212.164.0.0/16",
        "213.59.128.0/17",
        "213.180.192.0/19",
        "217.12.96.0/20",
        "217.118.64.0/19",
    )

    fun complement(excludeCidrs: List<String>): List<String> {
        val ranges = excludeCidrs.mapNotNull { cidrToRange(it) }.sortedBy { it.start }
        if (ranges.isEmpty()) return listOf("0.0.0.0/0")

        val protectedRanges = PROTECTED.mapNotNull { cidrToRange(it) }
            .filter { p -> ranges.any { it.start <= p.start && p.end <= it.end } }

        for (gridPrefix in intArrayOf(32, 24, 22, 20, 18, 16, 14, 12)) {
            val aligned = alignToGrid(ranges, gridPrefix) + protectedRanges
            if (aligned.isEmpty()) break
            val out = complementOf(mergeRanges(aligned.sortedBy { it.start }))
            if (out.isEmpty()) break
            if (out.size <= MAX_ROUTES) return out
        }

        return listOf("0.0.0.0/0")
    }

    private fun alignToGrid(ranges: List<Range>, gridPrefix: Int): List<Range> {
        if (gridPrefix >= 32) return ranges
        val grid = 1L shl (32 - gridPrefix)
        // Расширяем НАРУЖУ (floor/ceil): диапазон мельче сетки раньше
        // выбрасывался целиком, и список из одних мелких подсетей молча
        // превращался в полный туннель. Для списка исключений расширение —
        // консервативная сторона: исключим чуть больше, но не потеряем.
        return ranges.map {
            val start = it.start / grid * grid
            val end = (it.end / grid + 1) * grid - 1
            Range(start, end.coerceAtMost(0xFFFFFFFFL))
        }
    }

    private fun mergeRanges(ranges: List<Range>): List<Range> {
        val merged = ArrayList<Range>()
        for (r in ranges) {
            val last = merged.lastOrNull()
            if (last != null && r.start <= last.end + 1) {
                merged[merged.size - 1] = Range(last.start, maxOf(last.end, r.end))
            } else {
                merged.add(r)
            }
        }
        return merged
    }

    private fun complementOf(merged: List<Range>): List<String> {
        val out = ArrayList<String>()
        var cursor = 0L
        for (m in merged) {
            if (m.start > cursor) rangeToCidrs(cursor, m.start - 1, out)
            cursor = m.end + 1
        }
        if (cursor <= 0xFFFFFFFFL) rangeToCidrs(cursor, 0xFFFFFFFFL, out)
        return out
    }

    fun allowedIpsExcept(excludeCidrs: List<String>): String =
        (complement(excludeCidrs) + "::/0").joinToString(", ")

    fun hasIpv6Address(configText: String): Boolean {
        var section = ""
        for (rawLine in configText.lineSequence()) {
            val line = rawLine.substringBefore('#').trim()
            if (line.isEmpty()) continue
            if (line.startsWith("[") && line.endsWith("]")) {
                section = line.trim('[', ']').lowercase()
                continue
            }
            if (section != "interface") continue
            val key = line.substringBefore('=', "").trim()
            if (!key.equals("address", ignoreCase = true)) continue

            if (line.substringAfter('=').split(',').any { ':' in it }) return true
        }
        return false
    }

    const val FALLBACK_DNS = "1.1.1.1, 8.8.8.8"

    const val FALLBACK_MTU = 1280

    fun ensureMtu(configText: String, mtu: Int = FALLBACK_MTU): String {
        var section = ""
        for (rawLine in configText.lineSequence()) {
            val line = rawLine.substringBefore('#').trim()
            if (line.isEmpty()) continue
            if (line.startsWith("[") && line.endsWith("]")) {
                section = line.trim('[', ']').lowercase()
                continue
            }
            if (section != "interface") continue
            if (line.substringBefore('=', "").trim().equals("mtu", ignoreCase = true)) {
                return configText
            }
        }

        val header = Regex("(?im)^[ \\t]*\\[Interface\\][ \\t]*$")
        val match = header.find(configText) ?: return configText
        return configText.substring(0, match.range.last + 1) +
            "\nMTU = $mtu" +
            configText.substring(match.range.last + 1)
    }

    fun ensureDns(configText: String, servers: String = FALLBACK_DNS): String {
        var section = ""
        for (rawLine in configText.lineSequence()) {
            val line = rawLine.substringBefore('#').trim()
            if (line.isEmpty()) continue
            if (line.startsWith("[") && line.endsWith("]")) {
                section = line.trim('[', ']').lowercase()
                continue
            }
            if (section != "interface") continue
            if (line.substringBefore('=', "").trim().equals("dns", ignoreCase = true)) {
                return configText
            }
        }

        val header = Regex("(?im)^[ \\t]*\\[Interface\\][ \\t]*$")
        val match = header.find(configText) ?: return configText
        return configText.substring(0, match.range.last + 1) +
            "\nDNS = $servers" +
            configText.substring(match.range.last + 1)
    }

    fun applyToConfig(configText: String, allowedIps: String): String {
        val regex = Regex("(?im)^[ \\t]*AllowedIPs[ \\t]*=.*(?:\\r?\\n)?")
        var replaced = false
        val result = regex.replace(configText) {
            if (replaced) "" else {
                replaced = true
                "AllowedIPs = $allowedIps\n"
            }
        }
        return if (replaced) result else {
            configText.trimEnd() + "\nAllowedIPs = $allowedIps\n"
        }
    }
}
