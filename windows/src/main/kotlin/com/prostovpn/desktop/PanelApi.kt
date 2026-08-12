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

    /**
     * Постоянный идентификатор установки.
     *
     * Без него панель считает каждый повторный вход новым устройством и по
     * лимиту тарифа гасит чужой живой сеанс — вплоть до телефона того же
     * человека. Живёт в отдельном узле настроек: logout() зовёт
     * prefs.clear(), а clear() чистит только собственные ключи узла, не
     * подузлы, — иначе идентификатор обнулялся бы на самом частом пути.
     */
    private val installPrefs = java.util.prefs.Preferences.userRoot().node("com/prostovpn/desktop/install")

    private val installId: String by lazy {
        installPrefs.get("id", null) ?: java.util.UUID.randomUUID().toString().also {
            installPrefs.put("id", it)
            // Preferences пишутся отложенно: без сброса на диск внезапная
            // перезагрузка вернёт нас к «новому устройству» на каждом входе.
            runCatching { installPrefs.flush() }
        }
    }

    /**
     * Имя устройства для списка в панели.
     *
     * InetAddress.getLocalHost() только запасной путь: он ходит в резолвер и
     * бросает UnknownHostException, когда имя хоста не разрешается.
     */
    private val deviceName: String =
        System.getenv("COMPUTERNAME")
            ?: runCatching { java.net.InetAddress.getLocalHost().hostName }.getOrNull()
            ?: "Windows"

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
        /** Остаток трафика; null — безлимит. Считает панель, не приложение. */
        val trafficLeftBytes: Long?,
        /** Осталось меньше десятой части лимита — пора предупредить. */
        val trafficLow: Boolean,
        /** Подписка кончается в ближайшие дни — пора показать продление. */
        val expiresSoon: Boolean,
        /** Куда вести продлевать. Панель присылает только когда пора. */
        val renewUrl: String?,
        val servers: List<ServerInfo>,
        /**
         * Почему список стран пуст. Панель объясняет это сама: пустой
         * список без причины человек читает как «приложение сломалось».
         */
        val notice: String?,
    )

    /**
     * Ошибка с текстом, который панель написала для человека.
     *
     * [status] — код ответа. Он нужен, чтобы отличать «токен больше не
     * действует» от «панель сейчас недоступна». Пока их не различали,
     * приложение выкидывало человека из аккаунта на любой пятисотке и на
     * каждом перезапуске панели: одна неудачная проверка списка стран — и
     * все сохранённые настройки стёрты.
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

    suspend fun login(login: String, password: String): Result<Session> =
        withContext(Dispatchers.IO) {
            runCatching {
                val payload = JSONObject()
                    .put("login", login.trim())
                    .put("password", password)
                    .put("platform", "windows")
                    .put("app_version", BuildInfo.VERSION)
                    // Панель ждёт их, чтобы переустановка и повторный вход
                    // с этого же ПК не съедали новый слот устройства.
                    .put("device_id", installId)
                    .put("device_name", deviceName.take(96))
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
                trafficLimitBytes = optLongOrNull(subscription, "traffic_limit_bytes"),
                trafficLeftBytes = optLongOrNull(subscription, "traffic_left_bytes"),
                trafficLow = subscription.optBoolean("traffic_low"),
                expiresSoon = subscription.optBoolean("expires_soon"),
                renewUrl = optStringOrNull(subscription, "renew_url"),
                servers = parseServers(body),
                notice = optStringOrNull(body, "notice"),
            )
        }
    }

    suspend fun logout(token: String) = withContext(Dispatchers.IO) {
        runCatching { request("POST", "/api/v1/logout", JSONObject(), token) }
        Unit
    }


    /** null и отсутствующий ключ — одно и то же; optLong вернул бы 0. */
    private fun optLongOrNull(json: JSONObject, key: String): Long? =
        if (json.isNull(key)) null else json.optLong(key)

    /** То же для строк: optString вернул бы пустую вместо null. */
    private fun optStringOrNull(json: JSONObject, key: String): String? =
        if (json.isNull(key)) null else json.optString(key).takeIf { it.isNotEmpty() }

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
            trafficLimitBytes = optLongOrNull(subscription, "traffic_limit_bytes"),
            trafficLeftBytes = optLongOrNull(subscription, "traffic_left_bytes"),
            trafficLow = subscription.optBoolean("traffic_low"),
            expiresSoon = subscription.optBoolean("expires_soon"),
            renewUrl = optStringOrNull(subscription, "renew_url"),
            servers = parseServers(body),
            notice = optStringOrNull(body, "notice"),
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
                // Текст панели берём запасным вариантом: он написан для
                // человека, но по-русски. Свой перевод приложение выберет по
                // коду причины — см. AppState.loginError.
                val detail = runCatching { JSONObject(text).optString("detail") }.getOrNull()
                throw PanelException(
                    message = detail?.takeIf { it.isNotBlank() } ?: "Ошибка $code",
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
