package com.prostovpn.desktop

import org.json.JSONArray
import org.json.JSONObject
import java.util.Base64

/** Проверка разбора ключа Amnezia: gradle keycheck */
fun main() {
    val ini = """
        [Interface]
        Address = 10.8.1.5/32
        DNS = 1.1.1.1
        PrivateKey = QEFbfLbTiJ2nHFPfJnrCLI9nCQXUKC0aSsyfXlXSVEg=
        Jc = 4
        Jmin = 40
        Jmax = 70
        S1 = 84
        S2 = 43
        H1 = 1234567891
        H2 = 1234567892
        H3 = 1234567893
        H4 = 1234567894

        [Peer]
        PublicKey = lJ7fS3fUvJ0PkGqXnFf0Xk1oXQ9dQ0EnT2xEeS2iMHU=
        PresharedKey = 5nHFPfJnrCLI9nCQXUKC0aSsyfXlXSVEgQEFbfLbTiJ2=
        AllowedIPs = 0.0.0.0/0, ::/0
        Endpoint = 203.0.113.77:41820
        PersistentKeepalive = 25
    """.trimIndent()

    // Как это кладёт Amnezia: last_config — JSON-строка с полем config
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
    check("MTU" in sanitized) { "не добавлен MTU" }
    println("--- итоговый конфиг для Windows ---")
    println(sanitized)

    // Мобильные ключи должны отсеиваться
    val withAndroidKeys = config.replace("[Peer]", "ExcludedApplications = com.foo\n\n[Peer]")
    val cleaned = WgConfig.sanitize(withAndroidKeys)
    check(cleaned != null && "ExcludedApplications" !in cleaned) { "мобильный ключ не отсеян" }

    println("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
}
