package com.prostovpn.desktop

object Endpoints {
    private val ENDPOINT = Regex("""(?im)^(\s*Endpoint\s*=\s*)(\S+?)(?::(\d+))?\s*$""")

    fun portOf(config: String): Int =
        ENDPOINT.find(config)?.groupValues?.getOrNull(3)?.toIntOrNull() ?: 0

    fun withPort(config: String, port: Int): String =
        ENDPOINT.replace(config) { m -> "${m.groupValues[1]}${m.groupValues[2]}:$port" }

    fun order(configPort: Int, remembered: Int, alternatives: List<Int>): List<Int> {
        val out = ArrayList<Int>(alternatives.size + 2)
        if (remembered > 0) out.add(remembered)
        if (configPort > 0 && configPort !in out) out.add(configPort)
        for (port in alternatives) if (port > 0 && port !in out) out.add(port)
        return out
    }
}
