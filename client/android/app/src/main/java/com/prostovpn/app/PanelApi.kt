package com.prostovpn.app

import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

object PanelApi {
    var baseUrl: String = BuildConfig.PANEL_URL

    private const val TIMEOUT_MS = 15_000

    data class Session(
        val token: String,
        val login: String,
        val name: String?,
        val publicId: String,
        val subscription: Subscription,
        val servers: List<PanelServer>,

        val notice: String?,
    )

    data class Subscription(
        val active: Boolean,
        val plan: String?,
        val daysLeft: Int,
        val trafficUsedBytes: Long,

        val trafficLimitBytes: Long?,

        val trafficLeftBytes: Long?,

        val trafficLow: Boolean,

        val expiresSoon: Boolean,

        val renewUrl: String?,
    )

    data class ServersReply(
        val servers: List<PanelServer>,
        val subscription: Subscription,
        val notice: String?,
    )

    data class PanelServer(
        val id: Int,
        val country: String,
        val countryEn: String?,
        val city: String?,
        val countryCode: String?,
        val config: String,

        val altPorts: List<Int> = emptyList(),
    )

    data class UpdateInfo(
        val available: Boolean,
        val version: String?,
        val url: String?,
        val changelog: String?,
        val mandatory: Boolean,

        val sha256: String?,

        val sizeBytes: Long?,
    )

    class PanelException(
        message: String,
        val status: Int = 0,

        val code: String = "",

        val retryAfterSeconds: Int = 0,
    ) : IOException(message)

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

        deviceId?.let { payload.put("device_id", it) }
        deviceName?.let { payload.put("device_name", it.take(96)) }

        val body = post("/api/v1/login", payload, token = null)
        return parseSession(body)
    }

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
                altPorts = item.optJSONArray("alt_ports")?.let { ports ->
                    (0 until ports.length()).mapNotNull { n -> ports.optInt(n).takeIf { it > 0 } }
                } ?: emptyList(),
            )
        }
    }

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

private fun JSONObject.optLongOrNull(key: String): Long? =
    if (isNull(key)) null else optLong(key)

fun PanelApi.PanelServer.toServerInfo(): ServerInfo = ServerInfo(
    host = "",
    country = country,
    city = city,
    countryEn = countryEn,
    countryCode = countryCode,
    config = config,
    altPorts = altPorts,
)
