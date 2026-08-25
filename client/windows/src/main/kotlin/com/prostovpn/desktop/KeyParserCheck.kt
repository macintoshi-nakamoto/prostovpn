package com.prostovpn.desktop

import org.json.JSONArray
import org.json.JSONObject
import java.util.Base64

fun main() {
    checkMainDispatcher()

    val ini = """
        [Interface]
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

        [Peer]
        PublicKey = 1m8v/lROKRSJTeZbV81vZNZi2NZZX4BGU3OcLWqbvxE=
        PresharedKey = NQ6YcjnQlbwCtIYEXWmCf8yPdik1pxb5KtCzzvqwBEI=
        AllowedIPs = 0.0.0.0/0, ::/0
        Endpoint = 203.0.113.77:41820
        PersistentKeepalive = 25
    """.trimIndent()

    val lastConfig = JSONObject().put("config", ini).toString()
    val awg = JSONObject()
        .put("last_config", lastConfig)
        .put("port", 41820)
        .put("transport_proto", "udp")
    val container = JSONObject().put("container", "amnezia-awg").put("awg", awg)
    val root = JSONObject()
        .put("hostName", "203.0.113.77")
        .put("containers", JSONArray().put(container))
        .put("defaultContainer", "amnezia-awg")

    val key = "vpn://" + Base64.getUrlEncoder().withoutPadding()
        .encodeToString(root.toString().toByteArray())

    val info = KeyParser.extractServer(key)
    println("host = ${info?.host}")
    val config = info?.config
    println("config starts with: ${config?.take(20)?.replace("\n", "\\n")}")

    check(info != null) { "ключ не разобран" }
    check(info.host == "203.0.113.77") { "неверный хост: ${info.host}" }
    check(config != null) { "конфиг не найден" }
    check(config.trimStart().startsWith("[Interface]")) {
        "вернулась обёртка, а не конфиг: ${config.take(60)}"
    }

    val sanitized = WgConfig.sanitize(config)
    check(sanitized != null) { "санитайзер отверг конфиг" }
    check("Jc = 4" in sanitized) { "потеряны параметры обфускации" }
    check("S3 = 20" in sanitized && "I1 = " in sanitized) { "потеряны параметры AWG 2.x" }
    check("MTU" in sanitized) { "не добавлен MTU" }
    println("--- итоговый конфиг для Windows ---")
    println(sanitized)

    val withAndroidKeys = config.replace("[Peer]", "ExcludedApplications = com.foo\n\n[Peer]")
    val cleaned = WgConfig.sanitize(withAndroidKeys)
    check(cleaned != null && "ExcludedApplications" !in cleaned) { "мобильный ключ не отсеян" }

    val outDir = java.io.File("build").apply { mkdirs() }
    java.io.File(outDir, "keycheck-full.conf").writeText(
        WgConfig.sanitize(SplitTunnel.applyToConfig(config, "0.0.0.0/0, ::/0"))!!
    )
    val split = SplitTunnel.allowedIpsExcept(SplitTunnel.parseCidrList("87.240.128.0/18\n5.255.255.0/24"))
    java.io.File(outDir, "keycheck-split.conf").writeText(
        WgConfig.sanitize(SplitTunnel.applyToConfig(config, split))!!
    )
    println("конфиги для проверки движком: build/keycheck-full.conf, build/keycheck-split.conf")

    checkServerStaysOutsideTunnel(config)
    checkAddressConflict()
    checkKillSwitchKey(config)
    checkNothingFallsOutOfTunnel()

    println("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
}

private fun checkKillSwitchKey(config: String) {
    val prepared = WgConfig.sanitize(config)!!
    check("KillSwitch = off" in prepared) { "KillSwitch = off не записан" }

    val foreign = config.replace("[Interface]", "[Interface]\nKillSwitch = banana")
    val cleaned = WgConfig.sanitize(foreign)!!
    check("banana" !in cleaned) { "чужой KillSwitch из ключа не отсеян" }
    check(cleaned.count { it == '\n' } > 0 && "KillSwitch = off" in cleaned) {
        "после отсева не осталось собственного KillSwitch = off"
    }
    println("killswitch: всегда off, чужое значение из ключа отсеивается")
}

private fun checkServerStaysOutsideTunnel(config: String) {
    val endpoint = SplitTunnel.endpointCidr(config)
    check(endpoint == "203.0.113.77/32") { "адрес сервера не распознан: $endpoint" }

    val byName = config.replace("203.0.113.77:41820", "vpn.example.org:41820")
    check(SplitTunnel.endpointCidr(byName) == null) { "имя хоста принято за адрес" }

    val everything = SplitTunnel.allowedIpsExcept(emptyList())
    check(covers(everything, "203.0.113.77")) { "проверка бессмысленна: сервер и так вне туннеля" }

    val excluded = SplitTunnel.allowedIpsExcept(listOf(endpoint))
    check(!covers(excluded, "203.0.113.77")) { "сервер остался внутри туннеля: $endpoint" }
    check(covers(excluded, "203.0.113.78")) { "исключили лишнее, не только сервер" }
    println("сервер вне туннеля: да")
}

private fun checkNothingFallsOutOfTunnel() {
    val content = object {}.javaClass.getResourceAsStream("/ru-split-tunnel.json")
        ?.bufferedReader()?.use { it.readText() }
    check(content != null) { "встроенный список исключений не найден" }

    val excluded = SplitTunnel.parseCidrList(content)
    val allowedList = SplitTunnel.complement(excluded)
    check(excluded.size > 1000) { "список подозрительно мал: ${excluded.size}" }

    val excludedRanges = toSortedRanges(excluded)
    val allowedRanges = toSortedRanges(allowedList)

    val mustTunnel = mapOf(
        "Telegram DC 149.154.167.51" to "149.154.167.51",
        "Telegram DC 149.154.175.50" to "149.154.175.50",
        "Telegram 91.108.56.130" to "91.108.56.130",
        "Cloudflare 1.1.1.1" to "1.1.1.1",
        "Google DNS 8.8.8.8" to "8.8.8.8",
        "GitHub 140.82.121.3" to "140.82.121.3",
    )
    val lost = mustTunnel.filter { (_, ip) ->
        val v = ipToLong(ip)!!
        !inRanges(excludedRanges, v) && !inRanges(allowedRanges, v)
    }
    check(lost.isEmpty()) {
        "выкинуты из VPN, хотя не исключены: " + lost.keys.joinToString(", ")
    }

    var checked = 0
    var violations = 0
    var firstBad = ""
    var probe = 1L
    while (probe < 0xFFFFFFFFL) {
        if (!inRanges(excludedRanges, probe) && !inRanges(allowedRanges, probe)) {
            violations++
            if (firstBad.isEmpty()) {
                firstBad = "${(probe shr 24) and 255}.${(probe shr 16) and 255}." +
                    "${(probe shr 8) and 255}.${probe and 255}"
            }
        }
        checked++
        probe += 997
    }
    check(violations == 0) {
        "огрубление вытолкнуло из VPN $violations адресов из $checked (первый: $firstBad)"
    }
    println("маршрутов в туннеле: ${allowedList.size}; проверено адресов: $checked, потерянных нет")
}

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

private fun toSortedRanges(cidrs: List<String>): List<LongRange> {
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

private fun covers(allowedIps: String, ip: String): Boolean {
    fun toLong(text: String): Long? {
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

    val target = toLong(ip) ?: return false
    return allowedIps.split(",").any { entry ->
        val cidr = entry.trim()
        val base = toLong(cidr.substringBefore('/')) ?: return@any false
        val prefix = cidr.substringAfter('/', "32").toIntOrNull() ?: return@any false
        if (prefix == 0) return@any true
        val mask = (0xFFFFFFFFL shl (32 - prefix)) and 0xFFFFFFFFL
        (target and mask) == (base and mask)
    }
}

private fun checkAddressConflict() {
    fun configWith(address: String) = """
        [Interface]
        Address = $address/32
        PrivateKey = AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=

        [Peer]
        PublicKey = 1m8v/lROKRSJTeZbV81vZNZi2NZZX4BGU3OcLWqbvxE=
        Endpoint = 203.0.113.77:41820
    """.trimIndent()

    check(AdapterConflict.holderOf(configWith("192.0.2.77")) == null) {
        "выдуман конфликт на свободном адресе"
    }

    val own = java.net.NetworkInterface.getNetworkInterfaces().toList()
        .filter { runCatching { it.isUp }.getOrDefault(false) }
        .filterNot { (it.displayName ?: it.name).contains(WindowsTunnel.TUNNEL_NAME, ignoreCase = true) }
        .flatMap { nif -> nif.inetAddresses.toList().map { nif to it } }
        .firstOrNull { (_, address) -> address is java.net.Inet4Address && !address.isLoopbackAddress }

    if (own == null) {
        println("конфликт адресов: сети нет, проверен только отрицательный случай")
        return
    }
    val (nif, address) = own
    val holder = AdapterConflict.holderOf(configWith(address.hostAddress))
    check(holder != null) { "занятый адрес ${address.hostAddress} не найден" }
    println("конфликт адресов: ${address.hostAddress} -> «$holder» (${nif.name})")
}

private fun checkMainDispatcher() {
    val name = kotlinx.coroutines.Dispatchers.Main.toString()
    check(!name.contains("Missing", ignoreCase = true)) {
        "Dispatchers.Main недоступен ($name): нет kotlinx-coroutines-swing"
    }

    runCatching { kotlinx.coroutines.Dispatchers.Main.isDispatchNeeded(kotlin.coroutines.EmptyCoroutineContext) }
        .onFailure { error("Dispatchers.Main непригоден: ${it.message}") }
    println("Dispatchers.Main: $name")
}
