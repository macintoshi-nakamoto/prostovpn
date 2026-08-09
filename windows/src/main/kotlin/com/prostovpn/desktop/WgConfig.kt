package com.prostovpn.desktop

/**
 * Приведение wg-quick конфига к тому, что принимает туннель Windows.
 *
 * Разбор конфигов у AmneziaWG для Windows строгий: любой незнакомый ключ
 * в [Interface] или [Peer] — ошибка целиком («Invalid key for section»),
 * поэтому мобильные ключи вроде ExcludedApplications нужно выкидывать.
 * Кроме того, без `Address` адаптер поднимется без маршрутов, а MTU по
 * умолчанию отличается от того, что ставит Amnezia, — задаём явно.
 */
object WgConfig {

    /**
     * Ключи [Interface], которые понимает наш движок туннеля.
     * Список должен совпадать с разбором в
     * `windows/tunnel/internal/conf/parser.go`: незнакомый ключ там —
     * ошибка всего конфига, а не пропуск строки.
     */
    private val interfaceKeys = setOf(
        "privatekey", "listenport", "address", "dns", "mtu", "table",
        // обфускация AmneziaWG
        "jc", "jmin", "jmax", "s1", "s2", "s3", "s4",
        "h1", "h2", "h3", "h4",
        "i1", "i2", "i3", "i4", "i5",
        "j1", "j2", "j3", "itime",
    )

    /** Ключи [Peer]. */
    private val peerKeys = setOf(
        "publickey", "presharedkey", "allowedips", "endpoint", "persistentkeepalive",
    )

    /** MTU по умолчанию для десктопа — как в клиенте Amnezia. */
    private const val DEFAULT_MTU = 1376

    /**
     * Оставляет только понятные Windows ключи и добивает обязательные поля.
     * Возвращает null, если конфиг непригоден (нет ключа или пира).
     */
    fun sanitize(configText: String): String? {
        var section = ""
        var hasAddress = false
        var hasMtu = false
        var hasPrivateKey = false
        var hasPeer = false
        var hasEndpoint = false

        val interfaceLines = mutableListOf<String>()
        val peerLines = mutableListOf<String>()

        for (rawLine in configText.lineSequence()) {
            val line = rawLine.substringBefore('#').trim()
            if (line.isEmpty()) continue

            if (line.startsWith("[") && line.endsWith("]")) {
                section = line.trim('[', ']').lowercase()
                if (section == "peer") hasPeer = true
                continue
            }

            val separator = line.indexOf('=')
            if (separator <= 0) continue
            val key = line.substring(0, separator).trim()
            val value = line.substring(separator + 1).trim()
            if (value.isEmpty()) continue

            when (section) {
                "interface" -> {
                    if (key.lowercase() !in interfaceKeys) continue
                    when (key.lowercase()) {
                        "address" -> hasAddress = true
                        "mtu" -> hasMtu = true
                        "privatekey" -> hasPrivateKey = true
                    }
                    interfaceLines += "$key = $value"
                }
                "peer" -> {
                    if (key.lowercase() !in peerKeys) continue
                    if (key.lowercase() == "endpoint") hasEndpoint = true
                    peerLines += "$key = $value"
                }
            }
        }

        if (!hasPrivateKey || !hasPeer || !hasEndpoint || !hasAddress) return null
        if (!hasMtu) interfaceLines += "MTU = $DEFAULT_MTU"

        return buildString {
            appendLine("[Interface]")
            interfaceLines.forEach { appendLine(it) }
            appendLine()
            appendLine("[Peer]")
            peerLines.forEach { appendLine(it) }
        }
    }
}
