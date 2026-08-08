package com.alisavpn.app

import android.app.Application
import android.util.Base64
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.zip.Inflater

data class ServerInfo(
    val host: String,
    val country: String? = null,
    val city: String? = null,
    val countryEn: String? = null,
    val cityEn: String? = null,
    val countryCode: String? = null,
    val config: String? = null,
) {
    fun countryFor(lang: String): String? =
        if (lang == "en") countryEn ?: country else country ?: countryEn

    fun cityFor(lang: String): String? =
        if (lang == "en") cityEn ?: city else city ?: cityEn
}

enum class Phase { OFF, CONNECTING, ON }

class AppState(application: Application) : AndroidViewModel(application) {

    private val prefs = application.getSharedPreferences("alisa", 0)

    var phase by mutableStateOf(Phase.OFF)
        private set
    var seconds by mutableIntStateOf(0)
        private set
    var server by mutableStateOf<ServerInfo?>(null)
        private set

    val isLoggedIn get() = server != null

    private var connectJob: Job? = null
    private var timerJob: Job? = null

    var pendingPermissionIntent by mutableStateOf<android.content.Intent?>(null)
        private set
    private var pendingConfig: String? = null

    private val tunnel: TunnelManager by lazy {
        TunnelManager(getApplication()).apply {
            onStateChange = { up ->
                if (!up && phase == Phase.ON) disconnect()
            }
        }
    }

    @OptIn(ExperimentalCoroutinesApi::class)
    private val tunnelDispatcher = Dispatchers.IO.limitedParallelism(1)

    var lang by mutableStateOf(prefs.getString("lang", "ru") ?: "ru")
        private set

    fun changeLang(value: String) {
        lang = value
        prefs.edit().putString("lang", value).apply()
    }

    private val s get() = strings(lang)

    var splitTunnelEnabled by mutableStateOf(prefs.getBoolean("split.enabled", true))
        private set
    var customSplitName by mutableStateOf(prefs.getString("split.name", null))
        private set
    val hasCustomSplitList get() = customSplitName != null

    var autoConnect by mutableStateOf(prefs.getBoolean("autoConnect", false))
        private set

    private var cachedAllowedIps: String? = null
    private var autoConnectTried = false

    fun changeSplitTunnel(enabled: Boolean) {
        if (splitTunnelEnabled == enabled) return
        splitTunnelEnabled = enabled
        prefs.edit().putBoolean("split.enabled", enabled).apply()
        reconnectIfActive()
    }

    private fun reconnectIfActive() {
        if (phase == Phase.OFF) return
        disconnect()
        toggleConnection()
    }

    fun changeAutoConnect(enabled: Boolean) {
        autoConnect = enabled
        prefs.edit().putBoolean("autoConnect", enabled).apply()
    }

    fun setCustomSplitList(json: String, name: String): Boolean {
        val cidrs = SplitTunnel.parseCidrList(json)
        if (cidrs.isEmpty()) return false
        prefs.edit()
            .putString("split.customJson", json)
            .putString("split.name", name)
            .apply()
        customSplitName = name
        cachedAllowedIps = null
        reconnectIfActive()
        return true
    }

    fun resetSplitList() {
        prefs.edit().remove("split.customJson").remove("split.name").apply()
        customSplitName = null
        cachedAllowedIps = null
        reconnectIfActive()
    }

    private fun excludeCidrs(): List<String> {
        val custom = prefs.getString("split.customJson", null)
        val json = custom ?: runCatching {
            getApplication<Application>().assets.open("ru-split-tunnel.json")
                .bufferedReader().use { it.readText() }
        }.getOrNull() ?: return emptyList()
        return SplitTunnel.parseCidrList(json)
    }

    private suspend fun buildConfigForConnect(base: String): String {
        if (!splitTunnelEnabled) {
            return SplitTunnel.applyToConfig(base, "0.0.0.0/0, ::/0")
        }
        val allowed = cachedAllowedIps ?: withContext(Dispatchers.Default) {
            SplitTunnel.allowedIpsExcept(excludeCidrs())
        }.also { cachedAllowedIps = it }
        return SplitTunnel.applyToConfig(base, allowed)
    }

    fun maybeAutoConnect() {
        if (autoConnectTried) return
        autoConnectTried = true
        if (autoConnect && isLoggedIn && phase == Phase.OFF) {
            toggleConnection()
        }
    }

    init {
        prefs.getString("server.host", null)?.let { host ->
            server = ServerInfo(
                host = host,
                country = prefs.getString("server.country", null),
                city = prefs.getString("server.city", null),
                countryEn = prefs.getString("server.countryEn", null),
                cityEn = prefs.getString("server.cityEn", null),
                countryCode = prefs.getString("server.countryCode", null),
                config = prefs.getString("server.config", null),
            )
            refreshGeo()
        }
    }

    sealed class LoginResult {
        data object Success : LoginResult()
        data class Error(val message: String) : LoginResult()
    }

    fun login(loginInput: String, password: String): LoginResult {
        val credentials = loginInput.filterNot { it.isWhitespace() }

        if (credentials.startsWith("vpn://")) {
            val info = KeyParser.extractServer(credentials)
                ?: return LoginResult.Error(s.errBadKey)
            prefs.edit().putString("accessKey", credentials).apply()
            applyServer(info)
            return LoginResult.Success
        }

        if (loginInput.isBlank()) {
            return LoginResult.Error(s.errEnterLogin)
        }
        if (password.length < 4) {
            return LoginResult.Error(s.errShortPassword)
        }

        return LoginResult.Error(s.errBadCredentials)
    }

    fun logout() {
        disconnect()
        server = null
        prefs.edit().clear().apply()
        customSplitName = null
        cachedAllowedIps = null
        splitTunnelEnabled = true
        autoConnect = false
        prefs.edit().putString("lang", lang).apply()
    }

    private fun applyServer(info: ServerInfo) {
        server = info
        persistServer()
        refreshGeo()
    }

    private fun persistServer() {
        val current = server ?: return
        prefs.edit()
            .putString("server.host", current.host)
            .putString("server.country", current.country)
            .putString("server.city", current.city)
            .putString("server.countryEn", current.countryEn)
            .putString("server.cityEn", current.cityEn)
            .putString("server.countryCode", current.countryCode)
            .putString("server.config", current.config)
            .apply()
    }

    fun toggleConnection() {
        when (phase) {
            Phase.CONNECTING -> Unit
            Phase.ON -> disconnect()
            Phase.OFF -> {
                val config = server?.config
                if (config.isNullOrBlank()) {
                    startSimulated()
                    return
                }
                val prepareIntent = android.net.VpnService.prepare(getApplication())
                if (prepareIntent != null) {
                    pendingConfig = config
                    pendingPermissionIntent = prepareIntent
                    return
                }
                startTunnel(config)
            }
        }
    }

    fun onVpnPermissionResult(granted: Boolean) {
        pendingPermissionIntent = null
        val config = pendingConfig
        pendingConfig = null
        if (granted && config != null) {
            startTunnel(config)
        }
    }

    private fun startTunnel(config: String) {
        phase = Phase.CONNECTING
        connectJob = viewModelScope.launch {
            val prepared = buildConfigForConnect(config)
            val ok = withContext(tunnelDispatcher) { tunnel.connect(prepared) }
            if (ok) {
                phase = Phase.ON
                startTimer()
            } else {
                phase = Phase.OFF
            }
        }
    }

    private fun startSimulated() {
        phase = Phase.CONNECTING
        connectJob = viewModelScope.launch {
            delay(1600)
            phase = Phase.ON
            startTimer()
        }
    }

    private fun startTimer() {
        seconds = 0
        timerJob = viewModelScope.launch {
            while (true) {
                delay(1000)
                seconds += 1
            }
        }
    }

    fun disconnect() {
        connectJob?.cancel()
        timerJob?.cancel()
        connectJob = null
        timerJob = null
        viewModelScope.launch(tunnelDispatcher) {
            runCatching { tunnel.disconnect() }
        }
        phase = Phase.OFF
        seconds = 0
    }

    val formattedDuration: String
        get() = "%02d:%02d".format(seconds / 60, seconds % 60)

    fun refreshGeo() {
        val host = server?.host?.takeIf { it.isNotEmpty() } ?: return
        if (server?.country != null && server?.countryEn != null) return

        viewModelScope.launch {
            val (ru, en) = withContext(Dispatchers.IO) {
                val ruDeferred = async { fetchGeo(host, "ru") }
                val enDeferred = async { fetchGeo(host, "en") }
                ruDeferred.await() to enDeferred.await()
            }
            if (ru == null && en == null) return@launch

            val current = server ?: return@launch
            if (current.host != host) return@launch
            server = current.copy(
                country = ru?.optString("country")?.takeIf { it.isNotEmpty() } ?: current.country,
                city = ru?.optString("city")?.takeIf { it.isNotEmpty() } ?: current.city,
                countryEn = en?.optString("country")?.takeIf { it.isNotEmpty() } ?: current.countryEn,
                cityEn = en?.optString("city")?.takeIf { it.isNotEmpty() } ?: current.cityEn,
                countryCode = (ru ?: en)?.optString("countryCode")?.takeIf { it.isNotEmpty() }
                    ?: current.countryCode,
            )
            persistServer()
        }
    }

    private fun fetchGeo(host: String, lang: String): JSONObject? = runCatching {
        val url = URL("http://ip-api.com/json/$host?fields=status,country,countryCode,city&lang=$lang")
        val connection = url.openConnection() as HttpURLConnection
        connection.connectTimeout = 8000
        connection.readTimeout = 8000
        val text = connection.inputStream.bufferedReader().use { it.readText() }
        JSONObject(text).takeIf { it.optString("status") == "success" }
    }.getOrNull()
}

object KeyParser {

    fun extractServer(key: String): ServerInfo? {
        val payload = key.removePrefix("vpn://")
        val data = decodeBase64Flexible(payload) ?: return null

        val text = runCatching { String(data, Charsets.UTF_8) }.getOrNull()
        if (text != null && (text.contains("[Interface]") || text.contains("[Peer]"))) {
            return ServerInfo(host = endpointHost(text) ?: "", config = text)
        }

        decodeQCompressedJson(data)?.let { json ->
            return ServerInfo(host = findHost(json) ?: "", config = findConfig(json))
        }

        runCatching { JSONObject(String(data, Charsets.UTF_8)) }.getOrNull()?.let { json ->
            return ServerInfo(host = findHost(json) ?: "", config = findConfig(json))
        }

        return null
    }

    private fun findConfig(node: Any?): String? {
        when (node) {
            is JSONObject -> {
                for (key in node.keys()) {
                    val value = node.opt(key)
                    if (value is String && (value.contains("[Interface]") && value.contains("[Peer]"))) {
                        return value
                    }
                    findConfig(value)?.let { return it }
                }
            }
            is JSONArray -> {
                for (i in 0 until node.length()) {
                    findConfig(node.opt(i))?.let { return it }
                }
            }
            is String -> {
                if (node.contains("[Interface]") && node.contains("[Peer]")) return node
                decodeBase64Flexible(node)?.let { bytes ->
                    val inner = runCatching { String(bytes, Charsets.UTF_8) }.getOrNull()
                    if (inner != null && inner.contains("[Interface]") && inner.contains("[Peer]")) {
                        return inner
                    }
                }
            }
        }
        return null
    }

    private fun decodeBase64Flexible(payload: String): ByteArray? {
        val normalized = payload.replace('-', '+').replace('_', '/')
        val padded = normalized + "=".repeat((4 - normalized.length % 4) % 4)
        return runCatching { Base64.decode(padded, Base64.DEFAULT) }.getOrNull()
    }

    private fun endpointHost(text: String): String? {
        for (line in text.lineSequence()) {
            val trimmed = line.trim()
            if (!trimmed.lowercase().startsWith("endpoint")) continue
            val value = trimmed.substringAfter('=', "").trim()
            if (value.isEmpty()) continue

            return if (value.startsWith("[")) {
                value.substringAfter('[').substringBefore(']')
            } else {
                value.substringBeforeLast(':')
            }.takeIf { it.isNotEmpty() }
        }
        return null
    }

    private fun decodeQCompressedJson(compressed: ByteArray): Any? {
        if (compressed.size <= 6) return null

        val expectedSize = compressed.take(4).fold(0) { acc, byte -> (acc shl 8) or (byte.toInt() and 0xFF) }
        if (expectedSize <= 0 || expectedSize > 10_000_000) return null

        val output = ByteArray(expectedSize)
        val inflater = Inflater()
        return runCatching {
            inflater.setInput(compressed, 4, compressed.size - 4)
            val size = inflater.inflate(output)
            if (size <= 0) return null
            parseJson(String(output, 0, size, Charsets.UTF_8))
        }.getOrNull().also { inflater.end() }
    }

    private fun parseJson(text: String): Any? =
        runCatching { JSONObject(text) }.getOrNull()
            ?: runCatching { JSONArray(text) }.getOrNull()

    private fun findHost(node: Any?): String? {
        when (node) {
            is JSONObject -> {
                for (key in listOf("hostName", "host")) {
                    node.optString(key).takeIf { it.isNotEmpty() }?.let { return it }
                }
                for (key in node.keys()) {
                    findHost(node.opt(key))?.let { return it }
                }
            }
            is JSONArray -> {
                for (i in 0 until node.length()) {
                    findHost(node.opt(i))?.let { return it }
                }
            }
            is String -> {
                if (node.contains("[Interface]") || node.contains("Endpoint")) {
                    return endpointHost(node)
                }
            }
        }
        return null
    }
}
