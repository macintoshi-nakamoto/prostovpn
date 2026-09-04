package com.prostovpn.app

import android.content.Context
import android.telephony.TelephonyManager

/**
 * Память о том, какой протокол сработал на этой сети.
 *
 * Раньше каждое подключение начиналось с AmneziaWG: там, где UDP режут,
 * человек каждый раз ждал перебор портов, прежде чем приложение доходило до
 * Reality. Теперь, если на этой же сети (тот же оператор или Wi-Fi) в
 * прошлый раз спас Reality, начинаем сразу с него. Память короткая — 12
 * часов: сети чинят, и AmneziaWG быстрее, когда он проходит. Удача
 * AmneziaWG память стирает.
 */
object ProtocolMemory {
    private const val TTL_MS = 12 * 60 * 60 * 1000L
    private const val PREF_PREFIX = "proto.vless."

    /** Ключ сети: оператор для сотовой, тип для остальных. */
    fun networkKey(context: Context): String {
        val kind = NetworkInfo.kind(context)
        if (kind != "cellular") return kind
        val tm = runCatching { context.getSystemService(TelephonyManager::class.java) }.getOrNull()
        val operator = tm?.networkOperatorName?.trim().orEmpty().ifEmpty { "cellular" }
        return "cellular:" + operator.lowercase()
    }

    fun prefersVless(context: Context, key: String = networkKey(context)): Boolean {
        val since = context.getSharedPreferences("prosto", 0).getLong(PREF_PREFIX + key, 0L)
        return since > 0 && System.currentTimeMillis() - since < TTL_MS
    }

    fun rememberVless(context: Context, key: String = networkKey(context)) {
        context.getSharedPreferences("prosto", 0).edit()
            .putLong(PREF_PREFIX + key, System.currentTimeMillis())
            .apply()
    }

    fun forget(context: Context, key: String = networkKey(context)) {
        context.getSharedPreferences("prosto", 0).edit().remove(PREF_PREFIX + key).apply()
    }
}
