package com.prostovpn.desktop

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
        val prefix = if (slash.size > 1) (slash[1].trim().toIntOrNull() ?: 32) else 32
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

    /**
     * Достаёт CIDR-подсети из содержимого файла списка:
     * JSON-массив объектов {"hostname": "1.2.3.0/24"}, JSON-массив строк
     * или обычный текст — по одной записи на строку.
     */
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
                .map { it.trim() }
                .filter { it.isNotEmpty() && cidrToRange(it) != null }
                .forEach { result.add(it) }
        }
        return result
    }

    private const val MAX_ROUTES = 2500

    /**
     * Сети, которые огрубление обязано сохранить точно.
     *
     * Огрубление по сетке выбрасывает куски меньше клетки, и на боевом списке
     * это стоило нам ровно тех сервисов, ради которых раздельное
     * туннелирование и включают: при сетке /18 из списка исчезало 34%
     * российского пространства, а вместе с ним Ozon (185.73.192.0/22),
     * Кинопоиск (213.180.192.0/19), Сбербанк, Wildberries, Avito и Тинькофф.
     * Они уходили в туннель, видели зарубежный адрес — и переставали
     * работать: Ozon зацикливал редирект, Кинопоиск не поднимал сессию.
     *
     * Поэтому эти сети добавляются к результату огрубления как есть, без
     * выравнивания. Стоит это несколько десятков лишних маршрутов — против
     * неработающих банков и маркетплейсов цена никакая.
     */
    private val PROTECTED = listOf(
        "5.255.192.0/18",    // Яндекс
        "31.130.128.0/19",   // Ozon, оплата
        "77.88.0.0/18",      // Яндекс
        "80.67.40.0/22",     // Иви
        "84.252.144.0/21",   // Сбербанк
        "87.240.128.0/18",   // VK
        "89.221.232.0/21",   // Mail.ru
        "90.156.224.0/19",   // Mail.ru
        "91.206.126.0/23",   // Мегамаркет, СДЭК
        "91.236.48.0/22",    // 2ГИС
        "93.186.224.0/20",   // VK
        "94.124.192.0/20",   // HeadHunter
        "95.163.0.0/17",     // Одноклассники
        "109.238.88.0/22",   // Rutube
        "176.114.112.0/20",  // Avito
        "178.130.128.0/20",  // Тинькофф
        "178.176.0.0/14",    // Мегафон
        "178.248.232.0/21",  // Rutube, МТС
        "185.62.200.0/22",   // Wildberries
        "185.73.192.0/22",   // Ozon
        "185.169.152.0/22",  // Okko
        "185.180.200.0/22",  // Mail.ru
        "188.162.0.0/16",    // Мегафон
        "194.9.208.0/22",    // Ozon Банк: оплата и корзина
        "195.208.0.0/15",    // Налоговая, Сбермаркет
        "195.242.82.0/23",   // ВТБ
        "212.164.0.0/16",    // Почта России, РЖД
        "213.59.128.0/17",   // Госуслуги
        "213.180.192.0/19",  // Кинопоиск
        "217.12.96.0/20",    // Альфа-Банк
        "217.118.64.0/19",   // Билайн
    )

    /**
     * Точное дополнение списка — это ~21000 подсетей, столько маршрутов
     * Windows ставить не должна. Поэтому исключения огрубляем по сетке,
     * пока их дополнение не влезет в [MAX_ROUTES].
     *
     * Огрубление идёт строго **внутрь**: границы поджимаются к сетке, а
     * куски меньше клетки исчезают. Тогда любая ошибка огрубления уводит
     * подсеть в VPN — медленнее, но работает. Наружу округлять нельзя:
     * так из VPN вылетают чужие адреса. Именно это ломало Telegram —
     * российские куски 149.154.64-143 раздувались до целого 149.154.0.0/16
     * и выносили из туннеля 149.154.160.0/20, дата-центр Telegram, который
     * в списке исключений не значился.
     *
     * Но «уводит в VPN» — это не безобидно: российский сервис за таким
     * адресом просто перестаёт работать. Поэтому сети из [PROTECTED]
     * возвращаются в набор исключений после каждого огрубления — они
     * переживают любую сетку, и Ozon с Кинопоиском больше не пропадают.
     */
    fun complement(excludeCidrs: List<String>): List<String> {
        val ranges = excludeCidrs.mapNotNull { cidrToRange(it) }.sortedBy { it.start }
        if (ranges.isEmpty()) return listOf("0.0.0.0/0")

        // Защищаем только то, что человек и так исключает: список из панели
        // может быть чужим и коротким, и навязывать ему наши сети незачем.
        val protectedRanges = PROTECTED.mapNotNull { cidrToRange(it) }
            .filter { p -> ranges.any { it.start <= p.start && p.end <= it.end } }

        for (gridPrefix in intArrayOf(32, 24, 22, 20, 18, 16, 14, 12)) {
            val aligned = alignToGrid(ranges, gridPrefix) + protectedRanges
            if (aligned.isEmpty()) break
            val out = complementOf(mergeRanges(aligned.sortedBy { it.start }))
            if (out.isEmpty()) break
            if (out.size <= MAX_ROUTES) return out
        }
        // Огрубить до бюджета не вышло — честнее увести весь трафик в VPN,
        // чем оставить дыры: раздельное туннелирование не важнее связи.
        return listOf("0.0.0.0/0")
    }

    /**
     * Поджимает диапазоны к сетке /[gridPrefix] внутрь. Диапазоны, целиком
     * умещающиеся внутри клетки, пропадают — они уйдут в VPN.
     */
    private fun alignToGrid(ranges: List<Range>, gridPrefix: Int): List<Range> {
        if (gridPrefix >= 32) return ranges
        val grid = 1L shl (32 - gridPrefix)
        return ranges.mapNotNull {
            val start = (it.start + grid - 1) / grid * grid
            val end = (it.end + 1) / grid * grid - 1
            if (start <= end) Range(start, end) else null
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

    /**
     * Адрес VPN-сервера из `Endpoint` в виде `/32` — его нельзя загонять
     * в туннель.
     *
     * При раздельном туннелировании список исключений разворачивается в
     * тысячи подсетей, и сервер запросто попадает в одну из них: для
     * 89.125.138.227 это была 89.120.0.0/13. Тогда маршрут до сервера ведёт
     * в сам туннель, то есть пакеты рукопожатия должны выйти через
     * соединение, которого ещё нет.
     *
     * Возвращает null, если Endpoint задан именем, а не адресом IPv4:
     * имя резолвит уже движок, и подсети для него мы не знаем.
     */
    fun endpointCidr(configText: String): String? {
        var section = ""
        for (rawLine in configText.lineSequence()) {
            val line = rawLine.substringBefore('#').trim()
            if (line.isEmpty()) continue
            if (line.startsWith("[") && line.endsWith("]")) {
                section = line.trim('[', ']').lowercase()
                continue
            }
            if (section != "peer") continue
            val key = line.substringBefore('=', "").trim()
            if (!key.equals("endpoint", ignoreCase = true)) continue

            val value = line.substringAfter('=').trim()
            // IPv6-эндпоинт пишут как [::1]:51820 — порт отделяем по последнему ':'
            val host = value.substringBeforeLast(':', value).trim().trim('[', ']')
            return if (ipToLong(host) != null) "$host/32" else null
        }
        return null
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
