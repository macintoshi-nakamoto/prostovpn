package com.prostovpn.app

import android.content.Context
import android.telephony.TelephonyManager
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

/**
 * Отчёты о попытках подключиться — панели, чтобы перестать гадать, что
 * режут у какого оператора.
 *
 * Один отчёт на попытку протокола: протокол, узел, порт, вышло или нет,
 * сколько заняло, сколько было заходов, тип сети и оператор. Ни адресов,
 * ни трафика. Очередь живёт в настройках, чтобы пережить перезапуск:
 * неудача обычно значит, что сети нет, и отправить её удаётся позже —
 * после удачного подключения или при следующем запуске.
 */
object Telemetry {
    private const val TAG = "ProstoTelemetry"
    private const val PREF_QUEUE = "telemetry.queue"
    private const val MAX_QUEUE = 40
    private const val MAX_BATCH = 20

    private fun prefs(context: Context) = context.getSharedPreferences("prosto", 0)

    private fun network(context: Context): JSONObject {
        val kind = NetworkInfo.kind(context)
        val json = JSONObject().put("kind", kind)
        if (kind == "cellular") {
            val tm = runCatching { context.getSystemService(TelephonyManager::class.java) }.getOrNull()
            val operator = tm?.networkOperatorName?.trim().orEmpty()
            if (operator.isNotEmpty()) json.put("operator", operator)
            val country = tm?.networkCountryIso?.trim()?.uppercase().orEmpty()
            if (country.length == 2) json.put("country", country)
        }
        return json
    }

    /** Кладёт отчёт в очередь. Дёшево, без сети — можно звать откуда угодно. */
    fun record(
        context: Context,
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
            .put("port", port ?: JSONObject.NULL)
            .put("ok", ok)
            .put("stage", stage)
            .put("duration_ms", durationMs)
            .put("attempts", attempts)
            .put("error", error?.take(160) ?: JSONObject.NULL)
            .put("network", network(context))
        synchronized(this) {
            val queue = load(context)
            queue.put(report)
            // Очередь не растёт бесконечно: старое вытесняется — свежее важнее.
            val trimmed = JSONArray()
            val start = maxOf(0, queue.length() - MAX_QUEUE)
            for (i in start until queue.length()) trimmed.put(queue.get(i))
            prefs(context).edit().putString(PREF_QUEUE, trimmed.toString()).apply()
        }
    }

    /** Отправляет накопленное. Молчит при любой ошибке: это не главное. */
    suspend fun flush(context: Context, token: String) {
        if (token.isEmpty()) return
        val batch: JSONArray
        val rest: JSONArray
        synchronized(this) {
            val queue = load(context)
            if (queue.length() == 0) return
            batch = JSONArray()
            rest = JSONArray()
            for (i in 0 until queue.length()) {
                if (i < MAX_BATCH) batch.put(queue.get(i)) else rest.put(queue.get(i))
            }
        }
        val sent = withContext(Dispatchers.IO) {
            runCatching { PanelApi.telemetry(token, batch) }
                .onFailure { Log.d(TAG, "отчёты не ушли: ${it.message}") }
                .isSuccess
        }
        if (sent) {
            synchronized(this) {
                prefs(context).edit().putString(PREF_QUEUE, rest.toString()).apply()
            }
        }
    }

    private fun load(context: Context): JSONArray =
        runCatching { JSONArray(prefs(context).getString(PREF_QUEUE, "[]") ?: "[]") }
            .getOrDefault(JSONArray())
}
