package com.prostovpn.app

import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/**
 * Клиент панели: вход по логину и паролю, список стран, проверка версии.
 *
 * Без сторонних библиотек — как и остальная работа с сетью в приложении.
 * Вызывать только с фонового потока: HttpURLConnection блокирующий.
 */
object PanelApi {

    /** Адрес панели. Меняется на боевой при сборке. */
    var baseUrl: String = BuildConfig.PANEL_URL

    private const val TIMEOUT_MS = 15_000

    /** Ответ панели на вход. */
    data class Session(
        val token: String,
        val login: String,
        val name: String?,
        val publicId: String,
        val subscriptionActive: Boolean,
        val plan: String?,
        val daysLeft: Int,
        val trafficUsedBytes: Long,
        /** null — безлимит. */
        val trafficLimitBytes: Long?,
        val servers: List<PanelServer>,
    )

    /**
     * Страна из панели.
     *
     * Адреса сервера и ключа здесь нет: панель их и не присылает. Показывать
     * человеку нечего, кроме страны, а `config` уходит прямо в туннель.
     */
    data class PanelServer(
        val id: Int,
        val country: String,
        val countryEn: String?,
        val city: String?,
        val countryCode: String?,
        val config: String,
    )

    data class UpdateInfo(
        val available: Boolean,
        val version: String?,
        val url: String?,
        val changelog: String?,
        val mandatory: Boolean,
    )

    /**
     * Ошибка с текстом, который панель написала для человека.
     *
     * Статус — не украшение: по нему различают «токен отозван» (401/403,
     * пора на экран входа) и «панель прилегла или сеть моргнула» (всё
     * остальное, просто пробуем позже). Ноль — ответа не было вовсе.
     */
    class PanelException(
        message: String,
        val status: Int = 0,
        val code: String? = null,
    ) : IOException(message)

    // --- вход -----------------------------------------------------------

    fun login(
        login: String,
        password: String,
        appVersion: String,
        deviceId: String? = null,
        deviceName: String? = null,
    ): Session {
        val payload = JSONObject()
            .put("login", login)
            .put("password", password)
            .put("platform", "android")
            .put("app_version", appVersion)
        // Постоянный идентификатор установки: без него переустановка
        // приложения выглядит для лимита устройств вторым телефоном.
        deviceId?.let { payload.put("device_id", it) }
        deviceName?.let { payload.put("device_name", it.take(96)) }

        val body = post("/api/v1/login", payload, token = null)
        return parseSession(body)
    }

    /** Обновляет список стран по сохранённому токену. */
    fun servers(token: String): Pair<List<PanelServer>, JSONObject> {
        val body = get("/api/v1/servers", token)
        return parseServers(body) to body.optJSONObject("subscription").orEmpty()
    }

    fun logout(token: String) {
        runCatching { post("/api/v1/logout", JSONObject(), token) }
    }

    // --- обновление -----------------------------------------------------

    fun checkUpdate(currentVersion: String): UpdateInfo {
        val query = "platform=android&current=" + URLEncoder.encode(currentVersion, "UTF-8")
        val body = get("/api/v1/version?$query", token = null)
        return UpdateInfo(
            available = body.optBoolean("update_available"),
            version = body.optStringOrNull("version"),
            url = body.optStringOrNull("url"),
            changelog = body.optStringOrNull("changelog"),
            mandatory = body.optBoolean("mandatory"),
        )
    }

    // --- разбор ---------------------------------------------------------

    private fun parseSession(body: JSONObject): Session {
        val account = body.optJSONObject("account").orEmpty()
        val subscription = body.optJSONObject("subscription").orEmpty()
        return Session(
            token = body.getString("token"),
            login = account.optString("login"),
            name = account.optStringOrNull("name"),
            publicId = account.optString("public_id"),
            subscriptionActive = subscription.optBoolean("active"),
            plan = subscription.optStringOrNull("plan"),
            daysLeft = subscription.optInt("days_left"),
            trafficUsedBytes = subscription.optLong("traffic_used_bytes"),
            // null в ответе — безлимит, а не ноль: ноль означал бы «всё выбрано».
            trafficLimitBytes = if (subscription.isNull("traffic_limit_bytes")) null
                                else subscription.optLong("traffic_limit_bytes"),
            servers = parseServers(body),
        )
    }

    private fun parseServers(body: JSONObject): List<PanelServer> {
        val array = body.optJSONArray("servers") ?: return emptyList()
        return (0 until array.length()).mapNotNull { i ->
            val item = array.optJSONObject(i) ?: return@mapNotNull null
            val config = item.optString("config")
            if (config.isEmpty()) return@mapNotNull null
            PanelServer(
                id = item.optInt("id"),
                country = item.optStringOrNull("country") ?: item.optString("name"),
                countryEn = item.optStringOrNull("country_en"),
                city = item.optStringOrNull("city"),
                countryCode = item.optStringOrNull("country_code"),
                config = config,
            )
        }
    }

    // --- транспорт ------------------------------------------------------

    private fun get(path: String, token: String?): JSONObject = request("GET", path, null, token)

    private fun post(path: String, payload: JSONObject, token: String?): JSONObject =
        request("POST", path, payload, token)

    private fun request(method: String, path: String, payload: JSONObject?, token: String?): JSONObject {
        val connection = (URL(baseUrl.trimEnd('/') + path).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = TIMEOUT_MS
            readTimeout = TIMEOUT_MS
            setRequestProperty("Content-Type", "application/json")
            token?.let { setRequestProperty("Authorization", "Bearer $it") }
            doOutput = payload != null
        }

        try {
            payload?.let {
                connection.outputStream.use { stream -> stream.write(it.toString().toByteArray()) }
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
                throw PanelException(
                    detail.takeUnless { it.isNullOrBlank() } ?: "Ошибка $code",
                    status = code,
                    code = connection.getHeaderField("X-Error-Code"),
                )
            }
            return JSONObject(text)
        } finally {
            connection.disconnect()
        }
    }
}

private fun JSONObject?.orEmpty(): JSONObject = this ?: JSONObject()

private fun JSONObject.optStringOrNull(key: String): String? =
    if (isNull(key)) null else optString(key).takeIf { it.isNotEmpty() }

/** Страна из панели в модель приложения. Адреса сервера в ней нет. */
fun PanelApi.PanelServer.toServerInfo(): ServerInfo = ServerInfo(
    host = "",
    country = country,
    city = city,
    countryEn = countryEn,
    countryCode = countryCode,
    config = config,
)
