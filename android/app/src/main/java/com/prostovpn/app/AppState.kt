package com.prostovpn.app

import android.app.Application
import android.util.Base64
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
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
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID
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

data class DemoServer(
    val flag: String,
    val nameRu: String,
    val nameEn: String,
    val cityRu: String,
    val cityEn: String,
    val ping: Int,
)

data class DisplayServer(
    val flag: String,
    val name: String,
    val sub: String,
)

data class TunnelFile(
    val id: String,
    val name: String,
    val count: Int,
    val isDefault: Boolean = false,
)

/**
 * DISCONNECTING — не косметика. Пока интерфейс VpnService не снят, весь
 * трафик идёт через него. Показывать в это время «отключено» — врать
 * пользователю о том, куда уходят его пакеты.
 */
enum class Phase { OFF, CONNECTING, DISCONNECTING, ON }

class AppState(application: Application) : AndroidViewModel(application) {

    private val prefs = application.getSharedPreferences("prosto", 0)

    init {
        migrateToFullTunnel()
    }

    /**
     * Переводит на полный туннель по умолчанию.
     *
     * Раньше по умолчанию было раздельное туннелирование: в туннель уходило
     * ~2000 подсетей. На части устройств Android столько маршрутов приводит
     * к «подключено, но не работает» — в любой сети, потому что маршруты от
     * сети не зависят. Полный туннель — это один маршрут и надёжная работа
     * везде; раздельное остаётся ручной опцией.
     *
     * Разовая, по флагу: кто осознанно включит сплит позже — сохранит его.
     */
    private fun migrateToFullTunnel() {
        if (prefs.getBoolean("fulltunnel.migrated", false)) return
        prefs.edit()
            .putBoolean("split.enabled", false)
            .putBoolean("fulltunnel.migrated", true)
            .apply()
    }

    var phase by mutableStateOf(Phase.OFF)
        private set
    var seconds by mutableIntStateOf(0)
        private set

    /** Текст последней ошибки подключения; null — ошибки нет. */
    var connectionError by mutableStateOf<String?>(null)
        private set

    fun dismissConnectionError() {
        connectionError = null
    }
    var server by mutableStateOf<ServerInfo?>(null)
        private set
    var isGuest by mutableStateOf(prefs.getBoolean("guest", false))
        private set

    val isLoggedIn get() = server != null || isGuest

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

    val s get() = strings(lang)

    // --- Настройки ---

    // Полный туннель по умолчанию: один маршрут вместо ~2000, работает на
    // любом Android. Раздельное включается вручную в настройках.
    var splitTunnelEnabled by mutableStateOf(prefs.getBoolean("split.enabled", false))
        private set
    var killSwitch by mutableStateOf(prefs.getBoolean("killSwitch", true))
        private set
    var autoStart by mutableStateOf(prefs.getBoolean("autoStart", false))
        private set
    var autoConnect by mutableStateOf(prefs.getBoolean("autoConnect", false))
        private set
    var logging by mutableStateOf(prefs.getBoolean("logging", true))
        private set

    private var cachedAllowedIps: String? = null
    // Отдельный кэш для сетей без IPv6: список без ::/0
    private var cachedAllowedIpsV4: String? = null
    private var autoConnectTried = false

    fun changeSplitTunnel(enabled: Boolean) {
        if (splitTunnelEnabled == enabled) return
        splitTunnelEnabled = enabled
        prefs.edit().putBoolean("split.enabled", enabled).apply()
        reconnectIfActive()
    }

    fun changeKillSwitch(enabled: Boolean) {
        killSwitch = enabled
        prefs.edit().putBoolean("killSwitch", enabled).apply()
    }

    fun changeAutoStart(enabled: Boolean) {
        autoStart = enabled
        prefs.edit().putBoolean("autoStart", enabled).apply()
    }

    fun changeAutoConnect(enabled: Boolean) {
        autoConnect = enabled
        prefs.edit().putBoolean("autoConnect", enabled).apply()
    }

    fun changeLogging(enabled: Boolean) {
        logging = enabled
        prefs.edit().putBoolean("logging", enabled).apply()
    }

    private fun reconnectIfActive() {
        if (phase == Phase.OFF) return
        disconnect()
        toggleConnection()
    }

    // --- Файлы туннелирования (списки исключений сплит-туннеля) ---

    val tunnelFiles = mutableStateListOf<TunnelFile>()
    var activeTunnelFileId by mutableStateOf(prefs.getString("tunnel.active", DEFAULT_FILE_ID) ?: DEFAULT_FILE_ID)
        private set

    val activeTunnelFile: TunnelFile?
        get() = tunnelFiles.firstOrNull { it.id == activeTunnelFileId }

    private fun tunnelDir(): File =
        File(getApplication<Application>().filesDir, "tunneling").apply { mkdirs() }

    private fun loadTunnelFiles() {
        tunnelFiles.clear()
        tunnelFiles.add(TunnelFile(DEFAULT_FILE_ID, DEFAULT_FILE_NAME, prefs.getInt("tunnel.defaultCount", 0), isDefault = true))
        runCatching {
            val arr = JSONArray(prefs.getString("tunnel.files", "[]") ?: "[]")
            for (i in 0 until arr.length()) {
                val obj = arr.optJSONObject(i) ?: continue
                tunnelFiles.add(
                    TunnelFile(
                        id = obj.optString("id"),
                        name = obj.optString("name"),
                        count = obj.optInt("count"),
                    )
                )
            }
        }
        if (tunnelFiles.none { it.id == activeTunnelFileId }) {
            activeTunnelFileId = DEFAULT_FILE_ID
        }
        // Число записей встроенного списка считаем один раз в фоне
        if (tunnelFiles.first().count == 0) {
            viewModelScope.launch(Dispatchers.Default) {
                val count = entryCount(defaultListJson() ?: "", "json")
                prefs.edit().putInt("tunnel.defaultCount", count).apply()
                withContext(Dispatchers.Main) {
                    val index = tunnelFiles.indexOfFirst { it.isDefault }
                    if (index >= 0) tunnelFiles[index] = tunnelFiles[index].copy(count = count)
                }
            }
        }
    }

    private fun persistTunnelFiles() {
        val arr = JSONArray()
        tunnelFiles.filterNot { it.isDefault }.forEach { file ->
            arr.put(
                JSONObject()
                    .put("id", file.id)
                    .put("name", file.name)
                    .put("count", file.count)
            )
        }
        prefs.edit().putString("tunnel.files", arr.toString()).apply()
    }

    fun selectTunnelFile(file: TunnelFile) {
        if (activeTunnelFileId == file.id) return
        activeTunnelFileId = file.id
        prefs.edit().putString("tunnel.active", file.id).apply()
        cachedAllowedIps = null
        cachedAllowedIpsV4 = null
        if (splitTunnelEnabled) reconnectIfActive()
    }

    /** Импорт файла списка. Возвращает false, если файл не удалось прочитать. */
    fun addTunnelFile(originalName: String, content: String): Boolean {
        if (content.isBlank()) return false
        val extension = originalName.substringAfterLast('.', "")
        val count = entryCount(content, extension)
        if (count == 0) return false

        var name = originalName.ifBlank { "list.json" }
        var attempt = 1
        while (tunnelFiles.any { it.name == name }) {
            val base = originalName.substringBeforeLast('.')
            val ext = if (extension.isEmpty()) "" else ".$extension"
            name = "${base}_$attempt$ext"
            attempt++
        }
        runCatching { File(tunnelDir(), name).writeText(content) }.getOrElse { return false }

        val file = TunnelFile(UUID.randomUUID().toString(), name, count)
        tunnelFiles.add(file)
        persistTunnelFiles()
        selectTunnelFile(file)
        return true
    }

    fun deleteTunnelFile(file: TunnelFile) {
        if (file.isDefault) return
        tunnelFiles.removeAll { it.id == file.id }
        runCatching { File(tunnelDir(), file.name).delete() }
        persistTunnelFiles()
        if (activeTunnelFileId == file.id) {
            selectTunnelFile(tunnelFiles.first())
        }
    }

    private fun defaultListJson(): String? = runCatching {
        getApplication<Application>().assets.open("ru-split-tunnel.json")
            .bufferedReader().use { it.readText() }
    }.getOrNull()

    private fun activeListContent(): String? {
        val active = activeTunnelFile ?: return defaultListJson()
        if (active.isDefault) return defaultListJson()
        return runCatching { File(tunnelDir(), active.name).readText() }.getOrNull()
            ?: defaultListJson()
    }

    private fun excludeCidrs(): List<String> {
        val content = activeListContent() ?: return emptyList()
        return SplitTunnel.parseCidrList(content)
    }

    private suspend fun buildConfigForConnect(base: String): String {
        /*
        IPv6 заворачиваем в туннель только если у интерфейса есть v6-адрес.
        Иначе ::/0 отправляет весь IPv6 в чёрную дыру: на мобильных сетях с
        IPv6 (частых у российских операторов) это выглядит как «подключено,
        а ничего не грузит» — система предпочитает IPv6 и упирается в него.
        */
        val ipv6 = SplitTunnel.hasIpv6Address(base)
        if (!splitTunnelEnabled) {
            val all = if (ipv6) "0.0.0.0/0, ::/0" else "0.0.0.0/0"
            return SplitTunnel.applyToConfig(base, all)
        }
        // Кэш зависит от того, включаем ли IPv6 — иначе после смены сервера
        // отдали бы чужой список
        val cacheKey = if (ipv6) cachedAllowedIps else cachedAllowedIpsV4
        val allowed = cacheKey ?: withContext(Dispatchers.Default) {
            SplitTunnel.allowedIpsExcept(excludeCidrs(), includeIpv6 = ipv6)
        }.also { if (ipv6) cachedAllowedIps = it else cachedAllowedIpsV4 = it }
        return SplitTunnel.applyToConfig(base, allowed)
    }

    // --- Серверы ---

    var selectedServerIndex by mutableIntStateOf(prefs.getInt("selectedServer", 0))
        private set

    fun selectServer(index: Int) {
        selectedServerIndex = index
        prefs.edit().putInt("selectedServer", index).apply()
    }

    fun displayServers(): List<DisplayServer> {
        val t = s
        server?.let { imported ->
            val flag = imported.countryCode
                ?.takeIf { it.isNotEmpty() }
                ?.let { flagEmoji(it) } ?: "🌐"
            val name = imported.countryFor(lang)?.takeIf { it.isNotEmpty() } ?: imported.host
            val sub = imported.cityFor(lang)?.takeIf { it.isNotEmpty() } ?: imported.host
            return listOf(DisplayServer(flag, name, sub))
        }
        return demoServers.map { demo ->
            DisplayServer(
                flag = demo.flag,
                name = if (lang == "en") demo.nameEn else demo.nameRu,
                sub = "${if (lang == "en") demo.cityEn else demo.cityRu} · ${demo.ping} ${t.ms}",
            )
        }
    }

    val currentServer: DisplayServer?
        get() {
            val servers = displayServers()
            if (servers.isEmpty()) return null
            return servers[selectedServerIndex.coerceAtMost(servers.size - 1)]
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
        loadTunnelFiles()
        if (selectedServerIndex >= displayServers().size) {
            selectServer(0)
        }
    }

    // --- Вход ---

    /** Применяет учётные данные: ключ vpn:// подключает сервер, иначе гостевой вход. */
    fun login(credentials: String): Boolean {
        val joined = credentials.filterNot { it.isWhitespace() }

        if (joined.startsWith("vpn://")) {
            val info = KeyParser.extractServer(joined) ?: return false
            prefs.edit().putString("accessKey", joined).apply()
            server = info
            selectServer(0)
            persistServer()
            refreshGeo()
            return true
        }

        isGuest = true
        prefs.edit().putBoolean("guest", true).apply()
        return true
    }

    fun loginAsGuest() {
        isGuest = true
        prefs.edit().putBoolean("guest", true).apply()
    }

    fun logout() {
        disconnect()
        server = null
        isGuest = false
        selectedServerIndex = 0
        val language = lang
        prefs.edit().clear().apply()
        // Язык сохраняем, а флаг миграции возвращаем сразу: без него дефолты
        // полей в памяти и в prefs разъедутся до перезапуска
        prefs.edit()
            .putString("lang", language)
            .putBoolean("fulltunnel.migrated", true)
            .putBoolean("split.enabled", false)
            .apply()
        cachedAllowedIps = null
        cachedAllowedIpsV4 = null
        // Полный туннель — как дефолт после установки
        splitTunnelEnabled = false
        killSwitch = true
        autoStart = false
        autoConnect = false
        logging = true
        loadTunnelFiles()
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

    // --- Подключение ---

    fun toggleConnection() {
        when (phase) {
            Phase.CONNECTING, Phase.ON -> disconnect()
            // Снятие уже идёт — повторное нажатие не должно его перебивать
            Phase.DISCONNECTING -> Unit
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
        connectionError = null
        connectJob = viewModelScope.launch {
            val prepared = buildConfigForConnect(config)
            val result = withContext(tunnelDispatcher) { tunnel.connect(prepared) }
            when (result) {
                TunnelManager.Result.CONNECTED -> {
                    phase = Phase.ON
                    startTimer()
                }
                TunnelManager.Result.NO_HANDSHAKE -> {
                    // Туннель поднялся, но сервер молчит — честно говорим об
                    // этом, а не показываем ложное «подключено»
                    phase = Phase.OFF
                    connectionError = s.errNoHandshake
                }
                TunnelManager.Result.FAILED -> {
                    phase = Phase.OFF
                    connectionError = s.errTunnelFailed
                }
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
        val startedAt = System.currentTimeMillis()
        timerJob = viewModelScope.launch {
            while (true) {
                delay(500)
                val elapsed = ((System.currentTimeMillis() - startedAt) / 1000L).toInt()
                if (elapsed != seconds) seconds = elapsed
            }
        }
    }

    fun disconnect() {
        connectJob?.cancel()
        timerJob?.cancel()
        timerJob = null
        connectionError = null
        /*
        Держим DISCONNECTING, пока интерфейс VpnService не снят. Раньше
        здесь сразу ставилось OFF, а снятие уходило в фон: пока туннель
        доживал, экран уже показывал «отключено», хотя весь трафик
        по-прежнему шёл через VPN.
        */
        phase = Phase.DISCONNECTING
        // seconds не обнуляем здесь: уходящий таймер должен дофейдиться
        // с последним значением, а не прокрутиться в 00:00; сброс — в startTimer()
        connectJob = viewModelScope.launch {
            withContext(tunnelDispatcher) { runCatching { tunnel.disconnect() } }
            phase = Phase.OFF
            connectJob = null
        }
    }

    val formattedDuration: String
        get() {
            val h = seconds / 3600
            val m = (seconds % 3600) / 60
            val sec = seconds % 60
            return if (h > 0) {
                "%d:%02d:%02d".format(h, m, sec)
            } else {
                "%02d:%02d".format(m, sec)
            }
        }

    // --- Геолокация сервера ---

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

    companion object {
        const val DEFAULT_FILE_ID = "default"
        const val DEFAULT_FILE_NAME = "ru-split-tunnel.json"

        val demoServers = listOf(
            DemoServer("🇳🇱", "Нидерланды", "Netherlands", "Амстердам", "Amsterdam", 34),
            DemoServer("🇸🇪", "Швеция", "Sweden", "Стокгольм", "Stockholm", 41),
            DemoServer("🇩🇪", "Германия", "Germany", "Франкфурт", "Frankfurt", 48),
        )

        /** Число записей в файле — как в iOS AppState.entryCount. */
        fun entryCount(content: String, extension: String): Int {
            if (extension.lowercase() == "json") {
                runCatching { return JSONArray(content).length() }
                runCatching { return JSONObject(content).length() }
            }
            return content.lineSequence().count { it.isNotBlank() }
        }
    }
}

object KeyParser {

    fun extractServer(key: String): ServerInfo? {
        val payload = key.removePrefix("vpn://")
        val data = decodeBase64Flexible(payload) ?: return null
        val text = runCatching { String(data, Charsets.UTF_8) }.getOrNull()

        // 1) Ключ — сам по себе wg-quick конфиг.
        //    Проверяем именно секцию с начала строки: JSON Amnezia тоже
        //    содержит подстроку «[Interface]» внутри поля, и наивная проверка
        //    возвращала всю JSON-обёртку вместо конфига.
        if (text != null && isWgQuick(text)) {
            return ServerInfo(host = endpointHost(text) ?: "", config = text)
        }

        // 2) JSON, сжатый qCompress (формат Amnezia)
        decodeQCompressedJson(data)?.let { json -> return fromJson(json) }

        // 3) Обычный JSON
        if (text != null) {
            parseJson(text)?.let { json -> return fromJson(json) }
        }

        return null
    }

    /** Собирает сервер из JSON ключа: хост и текст конфига. */
    private fun fromJson(json: Any): ServerInfo {
        val config = findConfig(json)
        val host = findHost(json)
            ?: config?.let { endpointHost(it) }
            ?: ""
        return ServerInfo(host = host, config = config)
    }

    /**
     * Достаёт из ключа текст wg-quick конфига.
     *
     * Amnezia кладёт конфиг вглубь JSON: containers[].awg.last_config — это
     * JSON-*строка*, внутри которой объект с ключом config, и уже там лежит
     * INI-текст. Наивная проверка «строка содержит [Interface] и [Peer]»
     * срабатывала на самой JSON-обёртке и возвращала `{"config":"..."}`,
     * который туннель отвергает («Line must occur in a section»). Поэтому
     * строку сначала пробуем разобрать как JSON и спускаемся внутрь.
     */
    private fun findConfig(node: Any?): String? {
        when (node) {
            is JSONObject -> {
                // Явные ключи Amnezia — самый надёжный путь
                node.optString("last_config").takeIf { it.isNotEmpty() }?.let { raw ->
                    findConfig(parseJson(raw) ?: raw)?.let { return it }
                }
                node.optString("config").takeIf { it.isNotEmpty() }?.let { raw ->
                    findConfig(raw)?.let { return it }
                }
                for (key in node.keys()) {
                    findConfig(node.opt(key))?.let { return it }
                }
            }
            is JSONArray -> {
                for (i in 0 until node.length()) {
                    findConfig(node.opt(i))?.let { return it }
                }
            }
            is String -> {
                // JSON, завёрнутый в строку
                if (looksLikeJson(node)) {
                    parseJson(node)?.let { inner -> findConfig(inner)?.let { return it } }
                } else if (isWgQuick(node)) {
                    return node
                }
                decodeBase64Flexible(node)?.let { bytes ->
                    val inner = runCatching { String(bytes, Charsets.UTF_8) }.getOrNull()
                    if (inner != null && inner != node) {
                        findConfig(inner)?.let { return it }
                    }
                }
            }
        }
        return null
    }

    /** Похоже на JSON, а не на INI-конфиг. */
    private fun looksLikeJson(text: String): Boolean {
        val trimmed = text.trimStart()
        return trimmed.startsWith("{") || trimmed.startsWith("[\"")
    }

    /** Настоящий wg-quick конфиг: секция [Interface] с начала строки. */
    private fun isWgQuick(text: String): Boolean =
        text.contains("[Interface]") &&
            text.contains("[Peer]") &&
            text.lineSequence().any { it.trim().equals("[Interface]", ignoreCase = true) }

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
