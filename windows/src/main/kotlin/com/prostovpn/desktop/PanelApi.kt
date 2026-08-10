package com.prostovpn.desktop

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/**
 * Вход в аккаунт и список стран из панели.
 *
 * Пароль проверяет сервер, а не приложение: страны выдаются только
 * оплаченной учётной записи. Адреса серверов и ключей панель не присылает —
 * человеку показывать нечего, кроме страны, а конфиг уходит в туннель.
 */
object PanelApi {

    var baseUrl: String =
        System.getProperty("panel.url") ?: System.getenv("PANEL_URL") ?: BuildInfo.PANEL_URL

    private const val TIMEOUT_MS = 15_000

    data class Session(
        val token: String,
        val login: String,
        val name: String?,
        val publicId: String,
        val subscriptionActive: Boolean,
        val daysLeft: Int,
        val trafficUsedBytes: Long,
        /** null — безлимит. */
        val trafficLimitBytes: Long?,
        val servers: List<ServerInfo>,
    )

    /** Ошибка с текстом, который панель написала для человека. */
    class PanelException(message: String) : IOException(message)

    suspend fun login(login: String, password: String): Result<Session> =
        withContext(Dispatchers.IO) {
            runCatching {
                val payload = JSONObject()
                    .put("login", login.trim())
                    .put("password", password)
                    .put("platform", "windows")
                    .put("app_version", BuildInfo.VERSION)
                parseSession(request("POST", "/api/v1/login", payload, token = null))
            }
        }

    /** Перечитывает страны по сохранённому токену. */
    suspend fun servers(token: String): Result<Session> = withContext(Dispatchers.IO) {
        runCatching {
            val body = request("GET", "/api/v1/servers", null, token)
            val subscription = body.optJSONObject("subscription") ?: JSONObject()
            Session(
                token = token,
                login = "",
                name = null,
                publicId = "",
                subscriptionActive = subscription.optBoolean("active"),
                daysLeft = subscription.optInt("days_left"),
                trafficUsedBytes = subscription.optLong("traffic_used_bytes"),
                trafficLimitBytes = if (subscription.isNull("traffic_limit_bytes")) null
                                    else subscription.optLong("traffic_limit_bytes"),
                servers = parseServers(body),
            )
        }
    }

    suspend fun logout(token: String) = withContext(Dispatchers.IO) {
        runCatching { request("POST", "/api/v1/logout", JSONObject(), token) }
        Unit
    }

    // --- разбор ---------------------------------------------------------

    private fun parseSession(body: JSONObject): Session {
        val account = body.optJSONObject("account") ?: JSONObject()
        val subscription = body.optJSONObject("subscription") ?: JSONObject()
        return Session(
            token = body.getString("token"),
            login = account.optString("login"),
            name = account.optString("name").takeIf { it.isNotEmpty() },
            publicId = account.optString("public_id"),
            subscriptionActive = subscription.optBoolean("active"),
            daysLeft = subscription.optInt("days_left"),
            trafficUsedBytes = subscription.optLong("traffic_used_bytes"),
            trafficLimitBytes = if (subscription.isNull("traffic_limit_bytes")) null
                                else subscription.optLong("traffic_limit_bytes"),
            servers = parseServers(body),
        )
    }

    private fun parseServers(body: JSONObject): List<ServerInfo> {
        val array = body.optJSONArray("servers") ?: return emptyList()
        return (0 until array.length()).mapNotNull { i ->
            val item = array.optJSONObject(i) ?: return@mapNotNull null
            val config = item.optString("config")
            if (config.isEmpty()) return@mapNotNull null
            ServerInfo(
                // Адреса сервера панель не присылает — и показывать его негде.
                host = "",
                country = item.optString("country").takeIf { it.isNotEmpty() },
                city = item.optString("city").takeIf { it.isNotEmpty() },
                countryEn = item.optString("country_en").takeIf { it.isNotEmpty() },
                cityEn = item.optString("city_en").takeIf { it.isNotEmpty() },
                countryCode = item.optString("country_code").takeIf { it.isNotEmpty() },
                config = config,
            )
        }
    }

    // --- транспорт ------------------------------------------------------

    private fun request(
        method: String,
        path: String,
        payload: JSONObject?,
        token: String?,
    ): JSONObject {
        val connection = (URL(baseUrl.trimEnd('/') + path).openConnection() as HttpURLConnection).apply {
            PanelTls.apply(this)
            requestMethod = method
            connectTimeout = TIMEOUT_MS
            readTimeout = TIMEOUT_MS
            setRequestProperty("Content-Type", "application/json")
            token?.let { setRequestProperty("Authorization", "Bearer $it") }
            doOutput = payload != null
        }

        try {
            payload?.let { body ->
                connection.outputStream.use { it.write(body.toString().toByteArray()) }
            }

            val code = connection.responseCode
            val text = if (code in 200..299) {
                connection.inputStream.bufferedReader().use { it.readText() }
            } else {
                connection.errorStream?.bufferedReader()?.use { it.readText() }.orEmpty()
            }

            if (code !in 200..299) {
                // Панель кладёт человеческий текст в detail — показываем его
                // как есть, он написан для пользователя, а не для лога.
                val detail = runCatching { JSONObject(text).optString("detail") }.getOrNull()
                throw PanelException(detail?.takeIf { it.isNotBlank() } ?: "Ошибка $code")
            }
            return JSONObject(text)
        } finally {
            connection.disconnect()
        }
    }
}
