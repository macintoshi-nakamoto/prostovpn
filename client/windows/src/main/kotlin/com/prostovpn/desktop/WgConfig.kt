package com.prostovpn.desktop

object WgConfig {
    private val interfaceKeys = setOf(
        "privatekey", "listenport", "address", "dns", "mtu", "table",

        "jc", "jmin", "jmax", "s1", "s2", "s3", "s4",
        "h1", "h2", "h3", "h4",
        "i1", "i2", "i3", "i4", "i5",
    )

    private val peerKeys = setOf(
        "publickey", "presharedkey", "allowedips", "endpoint", "persistentkeepalive",
    )

    private val unsupportedObfuscation = setOf("j1", "j2", "j3", "itime")

    fun unsupportedKeys(configText: String): List<String> {
        val found = linkedSetOf<String>()
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
            if (key.lowercase() in unsupportedObfuscation) found += key
        }
        return found.toList()
    }

    private const val DEFAULT_MTU = 1376

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

        interfaceLines += "KillSwitch = off"

        return buildString {
            appendLine("[Interface]")
            interfaceLines.forEach { appendLine(it) }
            appendLine()
            appendLine("[Peer]")
            peerLines.forEach { appendLine(it) }
        }
    }
}
