package com.prostovpn.desktop

import java.net.NetworkInterface

object AdapterConflict {
    fun holderOf(configText: String): String? {
        val wanted = addressesOf(configText)
        if (wanted.isEmpty()) return null

        val interfaces = runCatching { NetworkInterface.getNetworkInterfaces() }.getOrNull()
            ?: return null

        for (nif in interfaces) {
            val name = nif.displayName ?: nif.name ?: continue
            if (isOurs(name) || isOurs(nif.name.orEmpty())) continue
            if (!runCatching { nif.isUp }.getOrDefault(false)) continue

            for (address in nif.inetAddresses) {
                val text = address.hostAddress?.substringBefore('%') ?: continue
                if (text in wanted) return name
            }
        }
        return null
    }

    private fun addressesOf(configText: String): Set<String> {
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
            return line.substringAfter('=')
                .split(',')
                .map { it.trim().substringBefore('/') }
                .filter { it.isNotEmpty() }
                .toSet()
        }
        return emptySet()
    }

    private fun isOurs(name: String): Boolean =
        name.contains(WindowsTunnel.TUNNEL_NAME, ignoreCase = true)
}
