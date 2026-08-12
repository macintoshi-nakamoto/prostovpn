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
        val subscription: Subscription,
        val servers: List<PanelServer>,
        /**
         * Почему список стран пуст. Панель объясняет это сама: пустой
         * список без причины человек читает как «приложение сломалось».
         */
        val notice: String?,
    )

    /**
     * Подписка — общая часть ответов /login и /servers.
     *
     * Отдельным типом, потому что приходит из двух мест: пока поля лежали
     * плоско в Session, обновление списка стран разбирало их вторым,
     * рукописным путём — и любое новое поле требовалось не забыть дважды.
     */
    data class Subscription(
        val active: Boolean,
        val plan: String?,
        val daysLeft: Int,
        val trafficUsedBytes: Long,
        /** null — безлимит. */
        val trafficLimitBytes: Long?,
        /** Остаток трафика; null — безлимит. Считает панель, не приложение. */
        val trafficLeftBytes: Long?,
        /** Осталось меньше порога — пора предупредить на главном экране. */
        val trafficLow: Boolean,
        /** Подписка кончается в ближайшие дни — пора показать продление. */
        val expiresSoon: Boolean,
        /** Куда вести продлевать. Панель присылает только когда пора. */
        val renewUrl: String?,
    )

    /**
     * Ответ /servers.
     *
     * Список стран — первым полем намеренно: страж сессии в TunnelManager
     * деструктурирует ответ как `val (servers, _) = …`. Поменяется порядок —
     * страж молча начнёт проверять пустоту не того значения.
     */
    data class ServersReply(
        val servers: List<PanelServer>,
        val subscription: Subscription,
        val notice: String?,
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
        /** Сумма APK. Без неё скачанное сверить не с чем — ставим на TLS. */
        val sha256: String?,
        /** Размер APK — дешёвая проверка целостности до подсчёта хеша. */
        val sizeBytes: Long?,
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
        /**
         * Код причины от панели: bad_credentials, blocked, disabled,
         * throttled. Пустой — панель старая и кодов не присылает.
         *
         * Нужен, потому что текст панели русский, а интерфейс бывает
         * английским, и по одному коду ответа причину не восстановить:
         * 401 приходит и на «пароль не тот», и на «доступ заблокирован».
         */
        val code: String = "",
        /** Через сколько секунд можно повторить — из Retry-After. */
        val retryAfterSeconds: Int = 0,
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
    fun servers(token: String): ServersReply {
        val body = get("/api/v1/servers", token)
        return ServersReply(
            servers = parseServers(body),
            subscription = parseSubscription(body.optJSONObject("subscription").orEmpty()),
            notice = body.optStringOrNull("notice"),
        )
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
            sha256 = body.optStringOrNull("sha256"),
            sizeBytes = body.optLong("size_bytes").takeIf { it > 0 },
        )
    }

    // --- разбор ---------------------------------------------------------

    private fun parseSession(body: JSONObject): Session {
        val account = body.optJSONObject("account").orEmpty()
        return Session(
            token = body.getString("token"),
            login = account.optString("login"),
            name = account.optStringOrNull("name"),
            publicId = account.optString("public_id"),
            subscription = parseSubscription(body.optJSONObject("subscription").orEmpty()),
            servers = parseServers(body),
            notice = body.optStringOrNull("notice"),
        )
    }

    private fun parseSubscription(subscription: JSONObject): Subscription = Subscription(
        active = subscription.optBoolean("active"),
        plan = subscription.optStringOrNull("plan"),
        daysLeft = subscription.optInt("days_left"),
        trafficUsedBytes = subscription.optLong("traffic_used_bytes"),
        // null в ответе — безлимит, а не ноль: ноль означал бы «всё выбрано».
        trafficLimitBytes = subscription.optLongOrNull("traffic_limit_bytes"),
        trafficLeftBytes = subscription.optLongOrNull("traffic_left_bytes"),
        trafficLow = subscription.optBoolean("traffic_low"),
        expiresSoon = subscription.optBoolean("expires_soon"),
        renewUrl = subscription.optStringOrNull("renew_url"),
    )

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
                    code = connection.getHeaderField("X-Error-Code").orEmpty(),
                    retryAfterSeconds = connection.getHeaderFieldInt("Retry-After", 0),
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

/** null и отсутствующий ключ — одно и то же; optLong вернул бы 0. */
private fun JSONObject.optLongOrNull(key: String): Long? =
    if (isNull(key)) null else optLong(key)

/** Страна из панели в модель приложения. Адреса сервера в ней нет. */
fun PanelApi.PanelServer.toServerInfo(): ServerInfo = ServerInfo(
    host = "",
    country = country,
    city = city,
    countryEn = countryEn,
    countryCode = countryCode,
    config = config,
)
