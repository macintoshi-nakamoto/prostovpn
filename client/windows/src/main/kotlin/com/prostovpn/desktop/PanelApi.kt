package com.prostovpn.desktop

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

object PanelApi {
    var baseUrl: String =
        System.getProperty("panel.url") ?: System.getenv("PANEL_URL") ?: BuildInfo.PANEL_URL

    private const val TIMEOUT_MS = 15_000

    private val installPrefs = java.util.prefs.Preferences.userRoot().node("com/prostovpn/desktop/install")

    private val installId: String by lazy {
        installPrefs.get("id", null) ?: java.util.UUID.randomUUID().toString().also {
            installPrefs.put("id", it)

            runCatching { installPrefs.flush() }
        }
    }

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

        val trafficLimitBytes: Long?,

        val trafficLeftBytes: Long?,

        val trafficLow: Boolean,

        val expiresSoon: Boolean,

        val renewUrl: String?,
        val servers: List<ServerInfo>,

        val notice: String?,
    )

    class PanelException(
        message: String,
        val status: Int = 0,

        val code: String = "",

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

                    .put("device_id", installId)
                    .put("device_name", deviceName.take(96))
                parseSession(request("POST", "/api/v1/login", payload, token = null))
            }
        }

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

    /** Отчёты о попытках подключиться — см. Telemetry. Зовётся из IO. */
    fun telemetry(token: String, reports: JSONArray) {
        request("POST", "/api/v1/telemetry/connect", JSONObject().put("reports", reports), token)
    }

    private fun optLongOrNull(json: JSONObject, key: String): Long? =
        if (json.isNull(key)) null else json.optLong(key)

    private fun optStringOrNull(json: JSONObject, key: String): String? =
        if (json.isNull(key)) null else json.optString(key).takeIf { it.isNotEmpty() }

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

    /**
     * Запасной путь до узла. Панель присылает его не всегда: на узле может не
     * быть точки Reality. Разбираем мягко — без ключа или адреса подключаться
     * всё равно нечем, и лучше остаться с одним основным протоколом, чем
     * уронить разбор всего списка серверов.
     */
    private fun parseVless(item: JSONObject?): XrayTunnel.Access? {
        if (item == null) return null
        val host = item.optString("host")
        val port = item.optInt("port")
        val id = item.optString("id")
        val publicKey = item.optString("public_key")
        if (host.isEmpty() || port !in 1..65535 || id.isEmpty() || publicKey.isEmpty()) return null
        return XrayTunnel.Access(
            host = host,
            port = port,
            id = id,
            publicKey = publicKey,
            shortId = item.optString("short_id"),
            serverName = item.optString("server_name"),
            fingerprint = item.optString("fingerprint").ifEmpty { "chrome" },
            flow = item.optString("flow"),
        )
    }

    private fun parseServers(body: JSONObject): List<ServerInfo> {
        val array = body.optJSONArray("servers") ?: return emptyList()
        return (0 until array.length()).mapNotNull { i ->
            val item = array.optJSONObject(i) ?: return@mapNotNull null
            val config = item.optString("config")
            if (config.isEmpty()) return@mapNotNull null
            ServerInfo(

                host = "",
                country = item.optString("country").takeIf { it.isNotEmpty() },
                city = item.optString("city").takeIf { it.isNotEmpty() },
                countryEn = item.optString("country_en").takeIf { it.isNotEmpty() },
                cityEn = item.optString("city_en").takeIf { it.isNotEmpty() },
                countryCode = item.optString("country_code").takeIf { it.isNotEmpty() },
                config = config,
                altPorts = item.optJSONArray("alt_ports")?.let { ports ->
                    (0 until ports.length()).mapNotNull { n ->
                        ports.optInt(n).takeIf { it in 1..65535 }
                    }
                } ?: emptyList(),
                vless = parseVless(item.optJSONObject("vless")),
            )
        }
    }

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
