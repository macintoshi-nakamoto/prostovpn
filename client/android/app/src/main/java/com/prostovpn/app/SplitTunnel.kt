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
     * системе давать нельзя. Поэтому исключения огрубляем по сетке, пока
     * их дополнение не влезет в [MAX_ROUTES].
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

    /**
     * Список AllowedIPs для раздельного туннелирования.
     *
     * `::/0` добавляем ВСЕГДА, даже когда у интерфейса нет IPv6-адреса, и это не
     * прихоть. Библиотека решает судьбу IPv6 так (GoBackend.setStateInternal):
     *
     *     если среди AllowedIPs есть маска 0 и пир один — allowFamily не зовётся;
     *     иначе вызывается allowFamily(AF_INET) и allowFamily(AF_INET6).
     *
     * При полном туннеле маска 0 есть (`0.0.0.0/0`), поэтому IPv6 остаётся
     * заблокированным — маршрута и адреса этого семейства нет, и система его глушит.
     * А при раздельном туннелировании маски 0 не было ни одной, значит срабатывал
     * `allowFamily(AF_INET6)` и РАЗБЛОКИРОВАЛ IPv6 при полном отсутствии IPv6-маршрутов:
     * весь IPv6-трафик уходил мимо туннеля с настоящим адресом абонента. На мобильных
     * сетях, где IPv6 выдаётся по умолчанию, это значит, что двухстековые сайты —
     * а Google двухстековый целиком — видели реальную страну, и Gemini отвечал
     * «эта страна не поддерживается».
     *
     * С `::/0` в списке маска 0 появляется: allowFamily не зовётся, IPv6 уходит в
     * туннель. Если v6-адреса у интерфейса нет, система не отдаёт приложениям
     * IPv6-связность и они работают по IPv4 через VPN — то есть корректно.
     */
    fun allowedIpsExcept(excludeCidrs: List<String>): String =
        (complement(excludeCidrs) + "::/0").joinToString(", ")

    /**
     * Есть ли у интерфейса IPv6-адрес — по строке `Address` секции
     * `[Interface]`.
     *
     * От этого зависит, можно ли заворачивать IPv6 в туннель. Если адреса
     * нет, а `::/0` в маршрутах есть, то на Android весь IPv6 уходит в
     * чёрную дыру: интерфейс без v6-адреса пакеты принять не может, но
     * система считает IPv6 доступным и предпочитает его. На мобильных
     * сетях с IPv6 это выглядит как «подключено, а ничего не грузит».
     */
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
            // IPv6 отличаем по двоеточию: у IPv4-адресов их не бывает.
            // Проходим все строки Address, а не только первую: адреса разных
            // семейств часто пишут отдельными строками, и выход на первой же
            // строке с IPv4 прятал существующий IPv6-адрес.
            if (line.substringAfter('=').split(',').any { ':' in it }) return true
        }
        return false
    }

    /** Резолверы на случай, когда сервер своих не прислал. */
    const val FALLBACK_DNS = "1.1.1.1, 8.8.8.8"

    /**
     * MTU по умолчанию, когда сервер своего не прислал.
     *
     * Без строки MTU библиотека берёт 1420. На мобильных сетях с CGNAT и
     * на телефонах Huawei/Honor это регулярно даёт самую коварную поломку:
     * рукопожатие проходит (оно маленькое), «подключено» горит, а страницы
     * не открываются — большие пакеты молча тонут, потому что канал
     * оператора не пропускает 1420 и не говорит об этом (PMTU-discovery
     * через CGNAT не работает). 1280 — гарантированный минимум IPv6,
     * который обязан пропускать любой канал. Цена — пара процентов
     * пропускной способности; «работает везде» дороже.
     */
    const val FALLBACK_MTU = 1280

    /**
     * Дописывает `MTU` в секцию `[Interface]`, если сервер его не задал.
     *
     * Конфиг сервера важнее: задан MTU — не трогаем.
     */
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

    /**
     * Дописывает `DNS` в секцию `[Interface]`, если сервер его не задал.
     *
     * Библиотека зовёт `VpnService.Builder.addDnsServer` только из
     * `Interface.getDnsServers()`, своего значения по умолчанию у неё нет. Когда
     * строки `DNS` в конфиге не было, туннель поднимался вообще без резолверов, и
     * система продолжала спрашивать DNS оператора. Дальше два одинаково плохих
     * исхода: при полном туннеле запросы к резолверу оператора уходят в туннель,
     * а он часто отвечает только абонентам своей сети — имена перестают
     * разрешаться совсем; при раздельном туннелировании адрес резолвера
     * российский, то есть в списке исключений, и запросы идут мимо VPN — тогда
     * ответы приходят с оглядкой на настоящее местоположение.
     *
     * Конфиг сервера всегда важнее: если `DNS` есть, не трогаем.
     */
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
