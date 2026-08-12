package com.prostovpn.desktop

/** Замер раздельного туннелирования на реальном списке: gradle splitStats */
fun main() {
    val content = object {}.javaClass.getResourceAsStream("/ru-split-tunnel.json")!!
        .bufferedReader().use { it.readText() }
    val excluded = SplitTunnel.parseCidrList(content)
    println("исключений в списке: ${excluded.size}")

    // Точный complement (grid /32) — эталон без округления
    println("точных маршрутов (без округления): ${exactComplementSize(excluded)}")

    // Развёртка по сетке округления (как реальный alignToGrid): какой самый
    // мягкий грид ещё оставляет Telegram в туннеле и сколько это маршрутов.
    println("--- округление НАРУЖУ (как сейчас) ---")
    for (grid in intArrayOf(24, 22, 20, 18, 16)) {
        val (size, tgOk) = gridStats(excluded, grid, "149.154.167.51", inward = false)
        println("  /%-2d -> %6d маршрутов, Telegram %s".format(grid, size, if (tgOk) "OK" else "ПОТЕРЯН"))
    }
    println("--- округление ВНУТРЬ (безопасное) ---")
    for (grid in intArrayOf(24, 22, 20, 18, 16, 14, 12)) {
        val (size, tgOk) = gridStats(excluded, grid, "149.154.167.51", inward = true)
        println("  /%-2d -> %6d маршрутов, Telegram %s".format(grid, size, if (tgOk) "OK" else "ПОТЕРЯН"))
    }

    val allowed = SplitTunnel.complement(excluded)
    println("маршрутов сейчас (текущий алгоритм): ${allowed.size}")

    // Контрольные адреса: их НЕ должно быть в списке исключений, а значит
    // они обязаны попасть в туннель. Если нет — округление съело соседа.
    val probes = mapOf(
        "Telegram DC2 149.154.167.51" to "149.154.167.51",
        "Telegram DC 149.154.175.50" to "149.154.175.50",
        "Telegram 91.108.56.130" to "91.108.56.130",
        "Google DNS 8.8.8.8" to "8.8.8.8",
        "Cloudflare 1.1.1.1" to "1.1.1.1",
        "GitHub 140.82.121.3" to "140.82.121.3",
    )
    println("--- контроль: адрес в списке исключений? / попал в туннель? ---")
    for ((name, ip) in probes) {
        val excludedHit = excluded.any { cidrCovers(it, ip) }
        val allowedHit = allowed.any { cidrCovers(it, ip) }
        val verdict = when {
            excludedHit -> "исключён по списку (ок, мимо VPN намеренно)"
            allowedHit -> "в туннеле ✓"
            else -> "!!! ПОТЕРЯН: не исключён, но и не в туннеле"
        }
        println("  %-32s %s".format(name, verdict))
    }
}

/** Сколько CIDR даёт точное дополнение списка по всему IPv4 (grid /32). */
private fun exactComplementSize(excludeCidrs: List<String>): Int {
    data class R(val start: Long, val end: Long)
    fun toLong(text: String): Long? {
        val parts = text.split(".")
        if (parts.size != 4) return null
        var v = 0L
        for (p in parts) { val n = p.toIntOrNull() ?: return null; if (n !in 0..255) return null; v = (v shl 8) or n.toLong() }
        return v
    }
    val ranges = excludeCidrs.mapNotNull { c ->
        val ip = toLong(c.substringBefore('/')) ?: return@mapNotNull null
        val prefix = c.substringAfter('/', "32").toIntOrNull() ?: return@mapNotNull null
        if (prefix == 0) R(0, 0xFFFFFFFFL) else {
            val mask = (0xFFFFFFFFL shl (32 - prefix)) and 0xFFFFFFFFL
            R(ip and mask, (ip and mask) or ((1L shl (32 - prefix)) - 1))
        }
    }.sortedBy { it.start }

    val merged = ArrayList<R>()
    for (r in ranges) {
        val last = merged.lastOrNull()
        if (last != null && r.start <= last.end + 1) merged[merged.size - 1] = R(last.start, maxOf(last.end, r.end))
        else merged.add(r)
    }
    // Число CIDR для диапазона [s,e] считаем так же, как rangeToCidrs
    fun cidrCount(start: Long, end: Long): Int {
        var s = start; var n = 0
        while (s <= end) {
            val maxAlign = if (s == 0L) 32 else java.lang.Long.numberOfTrailingZeros(s)
            val size = 63 - java.lang.Long.numberOfLeadingZeros(end - s + 1)
            val k = minOf(maxAlign, size)
            n++; s += (1L shl k)
        }
        return n
    }
    var total = 0L; var cursor = 0L
    for (m in merged) { if (m.start > cursor) total += cidrCount(cursor, m.start - 1); cursor = m.end + 1 }
    if (cursor <= 0xFFFFFFFFL) total += cidrCount(cursor, 0xFFFFFFFFL)
    return total.toInt()
}

/** Число complement-CIDR и судьба Telegram при округлении исключений до сетки /grid. */
private fun gridStats(excludeCidrs: List<String>, gridPrefix: Int, tgIp: String, inward: Boolean): Pair<Int, Boolean> {
    data class R(val start: Long, val end: Long)
    fun toLong(text: String): Long? {
        val parts = text.split("."); if (parts.size != 4) return null
        var v = 0L; for (p in parts) { val n = p.toIntOrNull() ?: return null; if (n !in 0..255) return null; v = (v shl 8) or n.toLong() }
        return v
    }
    var ranges = excludeCidrs.mapNotNull { c ->
        val ip = toLong(c.substringBefore('/')) ?: return@mapNotNull null
        val prefix = c.substringAfter('/', "32").toIntOrNull() ?: return@mapNotNull null
        if (prefix == 0) R(0, 0xFFFFFFFFL) else {
            val mask = (0xFFFFFFFFL shl (32 - prefix)) and 0xFFFFFFFFL
            R(ip and mask, (ip and mask) or ((1L shl (32 - prefix)) - 1))
        }
    }.sortedBy { it.start }
    if (gridPrefix < 32) {
        val grid = 1L shl (32 - gridPrefix)
        ranges = if (inward) {
            // Внутрь: границы поджимаем к сетке, куски меньше клетки исчезают.
            // Такие подсети просто пойдут через VPN — это безопасный отказ.
            ranges.mapNotNull {
                val s = (it.start + grid - 1) / grid * grid
                val e = (it.end + 1) / grid * grid - 1
                if (s <= e) R(s, e) else null
            }.sortedBy { it.start }
        } else {
            ranges.map { R(it.start / grid * grid, (it.end / grid + 1) * grid - 1) }.sortedBy { it.start }
        }
    }
    if (ranges.isEmpty()) return 1 to true

    val merged = ArrayList<R>()
    for (r in ranges) {
        val last = merged.lastOrNull()
        if (last != null && r.start <= last.end + 1) merged[merged.size - 1] = R(last.start, maxOf(last.end, r.end))
        else merged.add(r)
    }
    fun cidrCount(start: Long, end: Long): Int {
        var s = start; var n = 0
        while (s <= end) { val a = if (s == 0L) 32 else java.lang.Long.numberOfTrailingZeros(s); val sz = 63 - java.lang.Long.numberOfLeadingZeros(end - s + 1); n++; s += (1L shl minOf(a, sz)) }
        return n
    }
    var total = 0L; var cursor = 0L
    val tg = toLong(tgIp)!!
    var tgInTunnel = true
    for (m in merged) {
        if (m.start > cursor) total += cidrCount(cursor, m.start - 1)
        if (tg in m.start..m.end) tgInTunnel = false
        cursor = m.end + 1
    }
    if (cursor <= 0xFFFFFFFFL) total += cidrCount(cursor, 0xFFFFFFFFL)
    return total.toInt() to tgInTunnel
}

private fun cidrCovers(cidr: String, ip: String): Boolean {
    fun toLong(text: String): Long? {
        val parts = text.split(".")
        if (parts.size != 4) return null
        var v = 0L
        for (p in parts) {
            val n = p.toIntOrNull() ?: return null
            if (n !in 0..255) return null
            v = (v shl 8) or n.toLong()
        }
        return v
    }
    val target = toLong(ip) ?: return false
    val base = toLong(cidr.substringBefore('/')) ?: return false
    val prefix = cidr.substringAfter('/', "32").toIntOrNull() ?: return false
    if (prefix == 0) return true
    val mask = (0xFFFFFFFFL shl (32 - prefix)) and 0xFFFFFFFFL
    return (target and mask) == (base and mask)
}
