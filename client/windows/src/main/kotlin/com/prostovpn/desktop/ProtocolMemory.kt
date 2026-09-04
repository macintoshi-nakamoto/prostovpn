package com.prostovpn.desktop

import java.util.prefs.Preferences

/**
 * Память о том, какой протокол сработал на этой сети.
 *
 * Если в прошлый раз AmneziaWG молчал, а спас Reality, следующее
 * подключение начинается сразу с Reality — без минуты перебора портов.
 * Память живёт 12 часов: сети чинят, и AmneziaWG быстрее, когда проходит.
 * Удача AmneziaWG память стирает. Сеть на Windows различаем по типу
 * адаптера — оператора здесь не узнать.
 */
object ProtocolMemory {
    private const val TTL_MS = 12 * 60 * 60 * 1000L
    private const val KEY_PREFIX = "proto.vless."

    private val prefs = Preferences.userRoot().node("com/prostovpn/desktop")

    fun networkKey(): String = Telemetry.networkKind()

    fun prefersVless(key: String = networkKey()): Boolean {
        val since = prefs.getLong(KEY_PREFIX + key, 0L)
        return since > 0 && System.currentTimeMillis() - since < TTL_MS
    }

    fun rememberVless(key: String = networkKey()) {
        prefs.putLong(KEY_PREFIX + key, System.currentTimeMillis())
        runCatching { prefs.flush() }
    }

    fun forget(key: String = networkKey()) {
        prefs.remove(KEY_PREFIX + key)
        runCatching { prefs.flush() }
    }
}
