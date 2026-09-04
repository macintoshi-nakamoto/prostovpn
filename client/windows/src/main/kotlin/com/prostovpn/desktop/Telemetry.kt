package com.prostovpn.desktop

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.NetworkInterface
import java.util.prefs.Preferences

/**
 * Отчёты о попытках подключиться — панели, чтобы перестать гадать, где и
 * что режут. Один отчёт на попытку протокола: протокол, узел, порт, вышло
 * или нет, сколько заняло, тип сети. Ни адресов, ни трафика.
 *
 * Очередь живёт в Preferences и переживает перезапуск: неудача обычно
 * значит, что сети нет, и отправить её удаётся позже — после удачного
 * подключения или при следующем запуске.
 */
object Telemetry {
    private const val KEY_QUEUE = "telemetry.queue"
    private const val MAX_QUEUE = 40
    private const val MAX_BATCH = 20

    private val prefs = Preferences.userRoot().node("com/prostovpn/desktop")

    /** Тип сети — по имени активного адаптера. Оператора Windows не знает. */
    private fun networkKind(): String {
        val names = runCatching {
            NetworkInterface.getNetworkInterfaces().toList()
                .filter { it.isUp && !it.isLoopback && !it.isVirtual }
                .filter { nic -> nic.inetAddresses.toList().any { it.address.size == 4 && !it.isLinkLocalAddress } }
                .map { (it.displayName + " " + it.name).lowercase() }
                .filterNot { n ->
                    listOf("prosto", "wireguard", "amnezia", "tun", "tap", "vethernet", "hyper-v", "vmware", "virtualbox")
                        .any { n.contains(it) }
                }
        }.getOrDefault(emptyList())
        if (names.isEmpty()) return "unknown"
        return when {
            names.any { n -> listOf("wi-fi", "wifi", "wireless", "wlan", "802.11").any { n.contains(it) } } -> "wifi"
            names.any { n -> listOf("mobile", "cellular", "wwan", "lte", "modem").any { n.contains(it) } } -> "cellular"
            names.any { n -> n.contains("ethernet") || n.contains("gigabit") } -> "ethernet"
            else -> "other"
        }
    }

    fun record(
        protocol: String,
        host: String?,
        port: Int?,
        ok: Boolean,
        stage: String,
        durationMs: Long,
        attempts: Int,
        error: String? = null,
    ) {
        val report = JSONObject()
            .put("protocol", protocol)
            .put("host", host ?: JSONObject.NULL)
            .put("port", port?.takeIf { it > 0 } ?: JSONObject.NULL)
            .put("ok", ok)
            .put("stage", stage)
            .put("duration_ms", durationMs)
            .put("attempts", attempts)
            .put("error", error?.take(160) ?: JSONObject.NULL)
            .put("network", JSONObject().put("kind", networkKind()))
        synchronized(this) {
            val queue = load()
            queue.put(report)
            val trimmed = JSONArray()
            val start = maxOf(0, queue.length() - MAX_QUEUE)
            for (i in start until queue.length()) trimmed.put(queue.get(i))
            save(trimmed)
        }
    }

    suspend fun flush(token: String) {
        if (token.isEmpty()) return
        val batch = JSONArray()
        val rest = JSONArray()
        synchronized(this) {
            val queue = load()
            if (queue.length() == 0) return
            for (i in 0 until queue.length()) {
                if (i < MAX_BATCH) batch.put(queue.get(i)) else rest.put(queue.get(i))
            }
        }
        val sent = withContext(Dispatchers.IO) {
            runCatching { PanelApi.telemetry(token, batch) }.isSuccess
        }
        if (sent) synchronized(this) { save(rest) }
    }

    private fun load(): JSONArray =
        runCatching { JSONArray(prefs.get(KEY_QUEUE, "[]") ?: "[]") }.getOrDefault(JSONArray())

    private fun save(queue: JSONArray) {
        // Preferences на Windows держат строку до 8 КБ — этого хватает на
        // очередь в 40 коротких отчётов; при переполнении просто режем.
        var text = queue.toString()
        var cut = queue
        while (text.length > Preferences.MAX_VALUE_LENGTH && cut.length() > 0) {
            val smaller = JSONArray()
            for (i in 1 until cut.length()) smaller.put(cut.get(i))
            cut = smaller
            text = cut.toString()
        }
        prefs.put(KEY_QUEUE, text)
        runCatching { prefs.flush() }
    }
}
