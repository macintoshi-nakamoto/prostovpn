package com.prostovpn.desktop

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
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
import java.util.prefs.Preferences
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

enum class Phase { OFF, CONNECTING, ON }

/**
 * Состояние приложения. Подключение в тестовой сборке для Windows —
 * симуляция (как в iOS-демо); точка интеграции реального туннеля — startConnect().
 */
class AppState(private val scope: CoroutineScope) {

    private val prefs = Preferences.userRoot().node("com/prostovpn/desktop")

    var phase by mutableStateOf(Phase.OFF)
        private set
    var seconds by mutableIntStateOf(0)
        private set
    var server by mutableStateOf<ServerInfo?>(null)
        private set
    var isGuest by mutableStateOf(prefs.getBoolean("guest", false))
        private set

    val isLoggedIn get() = server != null || isGuest

    private var connectJob: Job? = null
    private var timerJob: Job? = null

    var lang by mutableStateOf(prefs.get("lang", "ru") ?: "ru")
        private set

    fun changeLang(value: String) {
        lang = value
        prefs.put("lang", value)
    }

    val s get() = strings(lang)

    // --- Настройки ---

    // На Windows раздельное туннелирование выключено по умолчанию: список
    // исключений превращается в ~2000 маршрутов, а kill-switch системного
    // туннеля включается только при AllowedIPs = 0.0.0.0/0
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

    private var autoConnectTried = false

    fun changeSplitTunnel(enabled: Boolean) {
        splitTunnelEnabled = enabled
        prefs.putBoolean("split.enabled", enabled)
        cachedAllowedIps = null
    }

    fun changeKillSwitch(enabled: Boolean) {
        killSwitch = enabled
        prefs.putBoolean("killSwitch", enabled)
    }

    fun changeAutoStart(enabled: Boolean) {
        autoStart = enabled
        prefs.putBoolean("autoStart", enabled)
    }

    fun changeAutoConnect(enabled: Boolean) {
        autoConnect = enabled
        prefs.putBoolean("autoConnect", enabled)
    }

    fun changeLogging(enabled: Boolean) {
        logging = enabled
        prefs.putBoolean("logging", enabled)
    }

    // --- Файлы туннелирования ---

    val tunnelFiles = mutableStateListOf<TunnelFile>()
    var activeTunnelFileId by mutableStateOf(prefs.get("tunnel.active", DEFAULT_FILE_ID) ?: DEFAULT_FILE_ID)
        private set

    private fun tunnelDir(): File =
        File(System.getProperty("user.home"), ".prostovpn/tunneling").apply { mkdirs() }

    /** Кэш вычисленных AllowedIPs — пересчёт списка исключений недёшев. */
    private var cachedAllowedIps: String? = null

    /** Содержимое активного списка исключений (свой файл или встроенный). */
    private fun activeListContent(): String? {
        val active = tunnelFiles.firstOrNull { it.id == activeTunnelFileId }
        if (active == null || active.isDefault) {
            return javaClass.getResourceAsStream("/ru-split-tunnel.json")
                ?.bufferedReader()?.use { it.readText() }
        }
        return runCatching { File(tunnelDir(), active.name).readText() }.getOrNull()
            ?: javaClass.getResourceAsStream("/ru-split-tunnel.json")
                ?.bufferedReader()?.use { it.readText() }
    }

    private fun loadTunnelFiles() {
        tunnelFiles.clear()
        tunnelFiles.add(TunnelFile(DEFAULT_FILE_ID, DEFAULT_FILE_NAME, prefs.getInt("tunnel.defaultCount", 0), isDefault = true))
        runCatching {
            val arr = JSONArray(prefs.get("tunnel.files", "[]") ?: "[]")
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
        if (tunnelFiles.first().count == 0) {
            scope.launch(Dispatchers.Default) {
                val content = javaClass.getResourceAsStream("/ru-split-tunnel.json")
                    ?.bufferedReader()?.use { it.readText() } ?: ""
                val count = entryCount(content, "json")
                prefs.putInt("tunnel.defaultCount", count)
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
        prefs.put("tunnel.files", arr.toString())
    }

    fun selectTunnelFile(file: TunnelFile) {
        activeTunnelFileId = file.id
        prefs.put("tunnel.active", file.id)
        cachedAllowedIps = null
    }

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

    // --- Серверы ---

    var selectedServerIndex by mutableIntStateOf(prefs.getInt("selectedServer", 0))
        private set

    fun selectServer(index: Int) {
        selectedServerIndex = index
        prefs.putInt("selectedServer", index)
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
        scope.launch {
            // Туннель мог пережить закрытие окна. Подхватываем только живой:
            // поднятый, но без единого рукопожатия он лишь забирает на себя
            // весь трафик — такой снимаем, чтобы вернуть сеть.
            val existing = withContext(Dispatchers.IO) {
                runCatching { if (tunnel.isUp()) tunnel.live() ?: WindowsTunnel.Live(0, 0, 0, 0) else null }
                    .getOrNull()
            }
            if (existing != null) {
                if (existing.handshakeAt > 0) {
                    phase = Phase.ON
                    startTimer()
                    return@launch
                }
                withContext(Dispatchers.IO) { runCatching { tunnel.disconnect() } }
            }
            if (autoConnect && isLoggedIn && phase == Phase.OFF) {
                toggleConnection()
            }
        }
    }

    init {
        prefs.get("server.host", null)?.let { host ->
            server = ServerInfo(
                host = host,
                country = prefs.get("server.country", null),
                city = prefs.get("server.city", null),
                countryEn = prefs.get("server.countryEn", null),
                cityEn = prefs.get("server.cityEn", null),
                countryCode = prefs.get("server.countryCode", null),
                config = prefs.get("server.config", null),
            )
            refreshGeo()
        }
        loadTunnelFiles()
        if (selectedServerIndex >= displayServers().size) {
            selectServer(0)
        }
    }

    // --- Вход ---

    fun login(credentials: String): Boolean {
        val joined = credentials.filterNot { it.isWhitespace() }

        if (joined.startsWith("vpn://")) {
            val info = KeyParser.extractServer(joined) ?: return false
            prefs.put("accessKey", joined)
            server = info
            selectServer(0)
            persistServer()
            refreshGeo()
            return true
        }

        isGuest = true
        prefs.putBoolean("guest", true)
        return true
    }

    fun loginAsGuest() {
        isGuest = true
        prefs.putBoolean("guest", true)
    }

    fun logout() {
        disconnect()
        server = null
        isGuest = false
        selectedServerIndex = 0
        val language = lang
        runCatching { prefs.clear() }
        prefs.put("lang", language)
        splitTunnelEnabled = true
        killSwitch = true
        autoStart = false
        autoConnect = false
        logging = true
        loadTunnelFiles()
    }

    private fun persistServer() {
        val current = server ?: return
        prefs.put("server.host", current.host)
        current.country?.let { prefs.put("server.country", it) }
        current.city?.let { prefs.put("server.city", it) }
        current.countryEn?.let { prefs.put("server.countryEn", it) }
        current.cityEn?.let { prefs.put("server.cityEn", it) }
        current.countryCode?.let { prefs.put("server.countryCode", it) }
        current.config?.let { prefs.put("server.config", it) }
    }

    // --- Подключение ---

    private val tunnel = WindowsTunnel()

    /** Текст последней ошибки подключения — показывается на главном экране. */
    var connectionError by mutableStateOf<String?>(null)
        private set

    fun dismissConnectionError() {
        connectionError = null
    }

    fun toggleConnection() {
        when (phase) {
            Phase.CONNECTING, Phase.ON -> disconnect()
            Phase.OFF -> startConnect()
        }
    }

    private fun startConnect() {
        val config = server?.config
        connectionError = null

        // Гостевой режим и демо-серверы: реального конфига нет, показываем
        // интерфейс как есть — подключаться нечем.
        if (config.isNullOrBlank()) {
            phase = Phase.CONNECTING
            connectJob = scope.launch {
                delay(1200)
                phase = Phase.OFF
                connectionError = s.errNoKey
            }
            return
        }

        phase = Phase.CONNECTING
        connectJob = scope.launch {
            val prepared = withContext(Dispatchers.Default) {
                // Приводим к тому, что принимает туннель Windows: мобильные
                // ключи он отвергает целиком, без Address не будет маршрутов
                WgConfig.sanitize(buildConfigForConnect(config))
            }
            if (prepared == null) {
                phase = Phase.OFF
                connectionError = s.errBadConfig
                return@launch
            }
            val result = withContext(Dispatchers.IO) { tunnel.connect(prepared) }
            when (result) {
                is WindowsTunnel.Result.Success -> {
                    phase = Phase.ON
                    startTimer()
                }
                is WindowsTunnel.Result.Failure -> {
                    phase = Phase.OFF
                    connectionError = when (result.reason) {
                        WindowsTunnel.Reason.NoBackend -> s.errNoBackend
                        WindowsTunnel.Reason.ElevationDenied -> s.errElevation
                        WindowsTunnel.Reason.UnsupportedOs -> s.errUnsupportedOs
                        WindowsTunnel.Reason.NoHandshake ->
                            // Сервер мог ждать маскировку, которую движок не умеет —
                            // без подсказки это выглядит как «просто не работает»
                            listOfNotNull(
                                s.errNoHandshake,
                                WgConfig.unsupportedKeys(config)
                                    .takeIf { it.isNotEmpty() }
                                    ?.let { s.errUnsupportedObfuscation + " " + it.joinToString(", ") },
                            ).joinToString(" · ")
                        WindowsTunnel.Reason.TunnelFailed ->
                            listOfNotNull(s.errTunnel, result.detail.takeIf { it.isNotBlank() })
                                .joinToString(" · ")
                    }
                }
            }
        }
    }

    /**
     * Готовит конфиг под раздельное туннелирование: без него весь трафик
     * идёт в VPN, с ним — всё, кроме подсетей из активного списка.
     */
    private fun buildConfigForConnect(base: String): String {
        if (!splitTunnelEnabled) {
            return SplitTunnel.applyToConfig(base, "0.0.0.0/0, ::/0")
        }
        val cached = cachedAllowedIps
        if (cached != null) return SplitTunnel.applyToConfig(base, cached)

        val content = activeListContent()
        val excluded = if (content == null) emptyList() else SplitTunnel.parseCidrList(content)
        val allowed = SplitTunnel.allowedIpsExcept(excluded)
        cachedAllowedIps = allowed
        return SplitTunnel.applyToConfig(base, allowed)
    }

    private fun startTimer() {
        seconds = 0
        val startedAt = System.currentTimeMillis()
        timerJob = scope.launch {
            var misses = 0
            var nextCheck = 5
            var lastRx = -1L
            while (true) {
                delay(500)
                val elapsed = ((System.currentTimeMillis() - startedAt) / 1000L).toInt()
                if (elapsed != seconds) seconds = elapsed

                // Туннель мог оборваться сам — экран не должен врать, что
                // соединение есть. Одиночный промах не считаем: опрос службы
                // изредка не проходит, а ложное отключение хуже секунды
                // задержки.
                if (elapsed >= nextCheck) {
                    nextCheck = elapsed + 5
                    val alive = withContext(Dispatchers.IO) {
                        runCatching {
                            if (!tunnel.isUp()) return@runCatching false
                            val live = tunnel.live() ?: return@runCatching true
                            // Рукопожатие обновляется не чаще раза в две минуты,
                            // а на простое может и вовсе не повторяться — поэтому
                            // растущий приём считаем доказательством связи.
                            val moving = live.rx > lastRx
                            lastRx = live.rx
                            live.isHealthy(staleSeconds = 300) || moving
                        }.getOrDefault(true)
                    }
                    misses = if (alive) 0 else misses + 1
                    if (misses >= 2) {
                        phase = Phase.OFF
                        connectionError = s.errTunnelDropped
                        timerJob = null
                        scope.launch(Dispatchers.IO) { runCatching { tunnel.disconnect() } }
                        return@launch
                    }
                }
            }
        }
    }

    fun disconnect() {
        connectJob?.cancel()
        timerJob?.cancel()
        connectJob = null
        timerJob = null
        phase = Phase.OFF
        // seconds не обнуляем: уходящий таймер дофейдится с последним значением
        scope.launch(Dispatchers.IO) {
            runCatching { tunnel.disconnect() }
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

        scope.launch {
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

    /** Только для офскрин-скриншотов (задача gradle screenshots). */
    internal fun previewAs(guest: Boolean, previewPhase: Phase, previewSeconds: Int = 754) {
        isGuest = guest
        phase = previewPhase
        seconds = previewSeconds
    }

    /** Скриншот шторки файлов: подкладываем второй файл в список. */
    internal var previewFileSheetOpen by mutableStateOf(false)
        private set

    /** Скриншот шторки серверов. */
    internal var previewServerSheetOpen by mutableStateOf(false)
        private set

    internal fun previewOpenServerSheet() {
        previewServerSheetOpen = true
    }

    internal fun previewOpenFileSheet() {
        if (tunnelFiles.none { !it.isDefault }) {
            tunnelFiles.add(TunnelFile("preview", "my-sites.json", 42))
        }
        previewFileSheetOpen = true
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
        return runCatching { java.util.Base64.getDecoder().decode(padded) }.getOrNull()
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
