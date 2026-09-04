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

    val altPorts: List<Int> = emptyList(),

    // Запасной путь до того же узла. Пусто — значит панель его не дала:
    // на узле нет живой точки Reality либо доступ не выдался.
    val vless: XrayTunnel.Access? = null,
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

enum class Phase { OFF, CONNECTING, DISCONNECTING, ON }

/** Чем поднят туннель: основным AmneziaWG или запасным VLESS поверх Reality. */
enum class Protocol { AWG, VLESS }

private const val ACCOUNT_POLL_MS = 60 * 1000L

class AppState(application: Application) : AndroidViewModel(application) {
    private val prefs = application.getSharedPreferences("prosto", 0)

    init {
        migrateToFullTunnel()
        // Недосланные отчёты о подключениях — при первом же запуске.
        viewModelScope.launch { Telemetry.flush(getApplication(), panelToken) }
    }

    /**
     * Отчёт панели об одной попытке протокола. После удачи сразу отправляем
     * накопленное: сеть только что появилась.
     */
    private fun reportAttempt(
        protocol: String,
        ok: Boolean,
        startedAt: Long,
        attempts: Int,
        host: String? = server?.host,
        port: Int? = null,
        stage: String = "handshake",
        error: String? = null,
    ) {
        Telemetry.record(
            getApplication(),
            protocol,
            host,
            port,
            ok,
            stage,
            System.currentTimeMillis() - startedAt,
            attempts,
            error,
        )
        if (ok) viewModelScope.launch { Telemetry.flush(getApplication(), panelToken) }
    }

    private fun observeTunnel() {
        viewModelScope.launch {
            tunnel.status.collect { status ->
                if (server?.config.isNullOrBlank()) return@collect
                when (status) {
                    TunnelManager.Status.ON -> if (phase != Phase.ON) {
                        phase = Phase.ON
                        connectionError = null
                        startForegroundNotice()
                        if (timerJob == null) startTimer()
                    }

                    TunnelManager.Status.RECONNECTING -> if (phase == Phase.ON) {
                        phase = Phase.CONNECTING
                        startConnectingNotice()
                    }
                    TunnelManager.Status.OFF ->
                        if (phase == Phase.ON || phase == Phase.CONNECTING) {
                            phase = Phase.OFF
                            timerJob?.cancel()
                            timerJob = null
                            stopForegroundNotice()
                            if (connectionError == null) {
                                connectionError = when (tunnel.lastFailure) {
                                    TunnelManager.Result.NO_HANDSHAKE -> s.errNoHandshake
                                    TunnelManager.Result.FAILED -> s.errTunnelFailed
                                    else -> s.errTunnelDropped
                                }
                            }
                        }
                    TunnelManager.Status.CONNECTING -> Unit
                }
            }
        }
    }

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

    var connectionError by mutableStateOf<String?>(null)
        private set

    fun dismissConnectionError() {
        connectionError = null
    }
    var server by mutableStateOf<ServerInfo?>(null)
        private set

    var panelToken by mutableStateOf(prefs.getString("panelToken", "").orEmpty())
        private set
    var accountName by mutableStateOf(prefs.getString("accountName", "").orEmpty())
        private set
    var accountPublicId by mutableStateOf(prefs.getString("accountPublicId", "").orEmpty())
        private set
    var subscriptionDaysLeft by mutableIntStateOf(prefs.getInt("daysLeft", 0))
        private set
    var trafficUsedBytes by mutableStateOf(prefs.getLong("trafficUsed", 0L))
        private set

    var trafficLimitBytes by mutableStateOf(prefs.getLong("trafficLimit", -1L))
        private set

    var trafficLeftBytes by mutableStateOf(prefs.getLong("trafficLeft", -1L))
        private set

    var trafficLow by mutableStateOf(prefs.getBoolean("trafficLow", false))
        private set

    var expiresSoon by mutableStateOf(prefs.getBoolean("expiresSoon", false))
        private set

    var renewUrl by mutableStateOf(prefs.getString("renewUrl", "").orEmpty())
        private set

    var panelNotice by mutableStateOf("")
        private set

    var signedOutReason by mutableStateOf("")
        private set

    fun consumeSignedOutReason(): String = signedOutReason.also { signedOutReason = "" }

    var panelServers by mutableStateOf<List<ServerInfo>>(emptyList())
        private set

    val updates: UpdateManager by lazy { UpdateManager(getApplication(), viewModelScope) }

    val isLoggedIn get() = panelToken.isNotEmpty() || server != null

    private var connectJob: Job? = null
    private var timerJob: Job? = null

    // Каким протоколом стоим сейчас: нужно и чтобы снимать именно поднятое, и
    // чтобы показать это человеку — запасной путь заметно отличается на глаз.
    var activeProtocol by mutableStateOf(Protocol.AWG)
        private set

    var pendingPermissionIntent by mutableStateOf<android.content.Intent?>(null)
        private set
    private var pendingConfig: String? = null

    private val tunnel: TunnelManager by lazy {
        TunnelManager.getInstance(getApplication()).also { manager ->

            manager.onStateChange = { up ->
                // Во время supervision-реконнекта интерфейс штатно опускается —
                // DOWN в этот момент не повод для полного disconnect.
                if (!up && phase == Phase.ON &&
                    manager.status.value == TunnelManager.Status.ON
                ) {
                    this@AppState.disconnect()
                }
            }
        }
    }

    private fun startForegroundNotice() {
        VpnForegroundService.setStoppingLabel(s.disconnectingTxt)
        val where = currentServer?.name?.takeIf { it.isNotEmpty() }
        val status = if (where != null) "${s.connected} · $where" else s.connected
        VpnForegroundService.start(getApplication(), status, s.notifDisconnect)
    }

    private fun startConnectingNotice() {
        VpnForegroundService.start(getApplication(), s.connectingTxt, s.notifDisconnect)
    }

    private fun stopForegroundNotice() {
        VpnForegroundService.stop(getApplication())
    }

    @OptIn(ExperimentalCoroutinesApi::class)
    private val tunnelDispatcher = Dispatchers.IO.limitedParallelism(1)

    var lang by mutableStateOf(
        prefs.getString("lang", null)
            ?: if (java.util.Locale.getDefault().language == "ru") "ru" else "en"
    )
        private set

    fun changeLang(value: String) {
        lang = value
        prefs.edit().putString("lang", value).apply()
    }

    val s get() = strings(lang)

    var splitTunnelEnabled by mutableStateOf(prefs.getBoolean("split.enabled", false))
        private set
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

    fun changeAutoConnect(enabled: Boolean) {
        autoConnect = enabled
        prefs.edit().putBoolean("autoConnect", enabled).apply()
    }

    private fun reconnectIfActive() {
        // Только живое соединение: тумблер во время ручного отключения не
        // должен поднимать туннель обратно.
        if (phase != Phase.ON && phase != Phase.CONNECTING) return
        // disconnect ставит DISCONNECTING и уходит в корутину — немедленный
        // toggleConnection попал бы в ветку «DISCONNECTING -> ничего».
        // Ждём фактического OFF, как это делает selectServer.
        viewModelScope.launch {
            disconnect()
            awaitOff()
            if (phase == Phase.OFF) toggleConnection()
        }
    }

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

        if (tunnelFiles.first().count == 0) {
            viewModelScope.launch(Dispatchers.Default) {
                val count = SplitTunnel.parseCidrList(defaultListJson() ?: "").size
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
        if (splitTunnelEnabled) reconnectIfActive()
    }

    fun addTunnelFile(originalName: String, content: String): Boolean {
        if (content.isBlank()) return false
        // Имя приходит из SAF-провайдера — не даём ему уйти из tunnelDir.
        val safeName = originalName
            .substringAfterLast('/')
            .substringAfterLast('\\')
            .replace("..", "_")
        val extension = safeName.substringAfterLast('.', "")
        // Считаем тем же парсером, который применяет список: файл из
        // доменов «импортировался успешно», а маршруты получались пустыми.
        val count = SplitTunnel.parseCidrList(content).size
        if (count == 0) return false

        var name = safeName.ifBlank { "list.json" }
        var attempt = 1
        while (tunnelFiles.any { it.name == name }) {
            val base = safeName.substringBeforeLast('.')
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

    private fun defaultListJson(): String? = ConnectConfig.defaultListJson(getApplication())

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
        val withDns = SplitTunnel.ensureMtu(SplitTunnel.ensureDns(base))
        if (!splitTunnelEnabled) {
            return SplitTunnel.applyToConfig(withDns, "0.0.0.0/0, ::/0")
        }
        val allowed = cachedAllowedIps ?: withContext(Dispatchers.Default) {
            SplitTunnel.allowedIpsExcept(excludeCidrs())
        }.also { cachedAllowedIps = it }
        return SplitTunnel.applyToConfig(withDns, allowed)
    }

    var selectedServerIndex by mutableIntStateOf(prefs.getInt("selectedServer", 0))
        private set

    fun selectServer(index: Int) {
        val wasConnected = phase == Phase.ON || phase == Phase.CONNECTING

        panelServers.getOrNull(index)?.let {
            server = it
            persistServer()
        }
        selectedServerIndex = index
        prefs.edit().putInt("selectedServer", index).apply()

        if (wasConnected) {
            viewModelScope.launch {
                disconnect()

                awaitOff()
                if (phase == Phase.OFF) toggleConnection()
            }
        }
    }

    private suspend fun awaitOff() {
        repeat(40) {
            if (phase == Phase.OFF) return
            kotlinx.coroutines.delay(150)
        }
    }

    fun displayServers(): List<DisplayServer> {
        if (panelServers.isNotEmpty()) {
            return panelServers.map { item ->
                DisplayServer(
                    flag = item.countryCode?.takeIf { it.isNotEmpty() }?.let { flagEmoji(it) } ?: "🌐",
                    name = item.countryFor(lang).orEmpty(),
                    sub = item.cityFor(lang).orEmpty(),
                )
            }
        }
        val t = s
        server?.let { imported ->
            val flag = imported.countryCode
                ?.takeIf { it.isNotEmpty() }
                ?.let { flagEmoji(it) } ?: "🌐"
            val name = imported.countryFor(lang)?.takeIf { it.isNotEmpty() } ?: imported.host

            val sub = imported.cityFor(lang)?.takeIf { it.isNotEmpty() && it != name }.orEmpty()
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
                altPorts = (prefs.getString("server.altPorts", "") ?: "")
                    .split(',').mapNotNull { it.trim().toIntOrNull() },
            )
            refreshGeo()
        }
        loadTunnelFiles()
        // Индекс не валидируем по раннему списку: до ответа панели
        // displayServers() — один импортированный сервер, и сохранённый
        // выбор «№2+» ошибочно сбрасывался бы на первый при каждом старте.
        // Валидация по настоящему списку живёт в applyPanelServers.
        restoreRunningTunnel()

        refreshPanelServers()
        startAccountWatch()

        updates.check()
    }

    private fun restoreRunningTunnel() {
        viewModelScope.launch {
            val config = server?.config

            val prepared = if (config.isNullOrBlank()) null else buildConfigForConnect(config)
            val up = withContext(tunnelDispatcher) {
                if (prepared == null) tunnel.isUp
                else tunnel.adopt(prepared, server?.altPorts ?: emptyList())
            }
            if (up && phase == Phase.OFF) {
                phase = Phase.ON
                startForegroundNotice()
                startTimer()
            }

            observeTunnel()
        }
    }

    fun loginWithKey(key: String): Boolean {
        val joined = key.filterNot { it.isWhitespace() }
        val info = KeyParser.extractServer(joined) ?: return false
        prefs.edit().putString("accessKey", joined).apply()
        panelServers = emptyList()
        server = info
        selectServer(0)
        persistServer()
        refreshGeo()
        return true
    }

    suspend fun login(login: String, password: String): Result<Unit> {
        val session = withContext(Dispatchers.IO) {
            runCatching {
                PanelApi.login(
                    login,
                    password,
                    BuildConfig.VERSION_NAME,
                    deviceId = installId(),
                    deviceName = deviceName(),
                )
            }
        }
        return session.map { applySession(it) }
    }

    private fun installId(): String {
        prefs.getString("installId", null)?.let { return it }
        val fresh = java.util.UUID.randomUUID().toString()
        prefs.edit().putString("installId", fresh).apply()
        return fresh
    }

    private fun deviceName(): String {
        val manufacturer = android.os.Build.MANUFACTURER.orEmpty()
            .replaceFirstChar { it.uppercase() }
        val model = android.os.Build.MODEL.orEmpty()
        return listOf(manufacturer, model).filter { it.isNotBlank() }.joinToString(" ")
    }

    private fun applySession(session: PanelApi.Session) {
        panelToken = session.token
        accountName = session.name ?: session.login
        accountPublicId = session.publicId

        prefs.edit()
            .putString("panelToken", session.token)
            .putString("accountName", accountName)
            .putString("accountPublicId", accountPublicId)
            .apply()

        applySubscription(session.subscription, session.notice)
        applyPanelServers(session.servers.map { it.toServerInfo() })
    }

    private fun applySubscription(subscription: PanelApi.Subscription, notice: String?) {
        subscriptionDaysLeft = subscription.daysLeft
        trafficUsedBytes = subscription.trafficUsedBytes
        trafficLimitBytes = subscription.trafficLimitBytes ?: -1L
        trafficLeftBytes = subscription.trafficLeftBytes ?: -1L
        trafficLow = subscription.trafficLow
        expiresSoon = subscription.expiresSoon
        renewUrl = subscription.renewUrl.orEmpty()

        panelNotice = notice.orEmpty()

        prefs.edit()
            .putInt("daysLeft", subscription.daysLeft)
            .putLong("trafficUsed", subscription.trafficUsedBytes)
            .putLong("trafficLimit", trafficLimitBytes)
            .putLong("trafficLeft", trafficLeftBytes)
            .putBoolean("trafficLow", trafficLow)
            .putBoolean("expiresSoon", expiresSoon)
            .putString("renewUrl", renewUrl)
            .apply()
    }

    private fun clearPersistedServer() {
        prefs.edit()
            .remove("server.host")
            .remove("server.country")
            .remove("server.city")
            .remove("server.countryEn")
            .remove("server.cityEn")
            .remove("server.countryCode")
            .remove("server.config")
            .remove("server.altPorts")
            .apply()
    }

    private fun applyPanelServers(list: List<ServerInfo>) {
        panelServers = list
        if (list.isEmpty()) {
            server = null
            // Иначе отозванный конфиг воскресает из prefs после рестарта.
            clearPersistedServer()
            cachedAllowedIps = null
            return
        }
        if (selectedServerIndex !in list.indices) selectServer(0)
        server = list[selectedServerIndex.coerceIn(list.indices)]
        persistServer()
    }

    fun refreshPanelServers() {
        val token = panelToken
        if (token.isEmpty()) return
        viewModelScope.launch(Dispatchers.IO) {
            val result = runCatching { PanelApi.servers(token) }
            withContext(Dispatchers.Main) {
                // Пока запрос летал, могли выйти из аккаунта или перевойти —
                // ответ устаревшего токена не должен воскрешать сессию.
                if (panelToken != token) return@withContext
                result
                    .onSuccess { reply ->

                        val lostAccess = reply.servers.isEmpty() && panelServers.isNotEmpty()
                        applySubscription(reply.subscription, reply.notice)
                        applyPanelServers(reply.servers.map { it.toServerInfo() })
                        if (lostAccess && (phase == Phase.ON || phase == Phase.CONNECTING)) {
                            disconnect()
                        }
                    }
                    .onFailure { error ->

                        // Разлогин — только по решению панели: 401 или 403 с её
                        // X-Error-Code. Голая 403 — это WAF/анти-DDoS по пути,
                        // стирать аккаунт из-за неё нельзя.
                        val panel = error as? PanelApi.PanelException
                        val status = panel?.status ?: 0
                        val fromPanel = status == 401 ||
                            (status == 403 && !panel?.code.isNullOrEmpty())
                        if (fromPanel) {
                            logout()

                            signedOutReason = s.noticeRemoteSignout
                        }
                    }
            }
        }
    }

    private fun startAccountWatch() {
        viewModelScope.launch {
            while (true) {
                delay(ACCOUNT_POLL_MS)
                if (panelToken.isNotEmpty()) refreshPanelServers()
            }
        }
    }

    fun logout() {
        disconnect()
        panelToken.takeIf { it.isNotEmpty() }?.let { token ->
            viewModelScope.launch(Dispatchers.IO) { PanelApi.logout(token) }
        }
        server = null
        panelServers = emptyList()
        panelToken = ""
        accountName = ""
        accountPublicId = ""
        subscriptionDaysLeft = 0
        trafficUsedBytes = 0L
        trafficLimitBytes = -1L
        trafficLeftBytes = -1L
        trafficLow = false
        expiresSoon = false
        renewUrl = ""
        panelNotice = ""
        selectedServerIndex = 0
        val language = lang
        // Идентификатор установки живёт дольше сессии: иначе каждый новый
        // вход плодит в кабинете новое «устройство».
        val keepInstallId = prefs.getString("installId", null)
        prefs.edit().clear().apply()

        prefs.edit()
            .putString("lang", language)
            .putBoolean("fulltunnel.migrated", true)
            .putBoolean("split.enabled", false)
            .apply()
        keepInstallId?.let { prefs.edit().putString("installId", it).apply() }
        // Реестр файлов стёрт clear()-ом — подчистим и сами файлы.
        runCatching { tunnelDir().listFiles()?.forEach { it.delete() } }
        cachedAllowedIps = null

        splitTunnelEnabled = false
        autoConnect = false
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
            .putString("server.altPorts", current.altPorts.joinToString(","))
            .apply()
    }

    fun toggleConnection() {
        when (phase) {
            Phase.CONNECTING, Phase.ON -> disconnect()

            Phase.DISCONNECTING -> Unit
            Phase.OFF -> {
                val config = server?.config
                if (config.isNullOrBlank()) {
                    // У залогиненного пустой config значит «нет доступных
                    // серверов» (кончилась подписка) — честная ошибка вместо
                    // симуляции подключения без VPN.
                    if (panelToken.isNotEmpty()) {
                        connectionError = s.errNoServers
                        return
                    }
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
        val config = pendingConfig ?: server?.config
        pendingConfig = null
        if (granted && !config.isNullOrBlank()) {
            startTunnel(config)
            return
        }
        if (phase == Phase.OFF) {
            connectionError = if (granted) s.errTunnelFailed else s.errVpnDenied
        }
    }

    private fun startTunnel(config: String) {
        phase = Phase.CONNECTING
        connectionError = null
        // Запасной протокол — ответ на неудачу, а не постоянный режим: иначе
        // тот, у кого однажды не прошёл UDP, навсегда остался бы на нём.
        activeProtocol = Protocol.AWG

        startConnectingNotice()
        connectJob = viewModelScope.launch {
            val prepared = buildConfigForConnect(config)
            val ports = server?.altPorts ?: emptyList()
            val hasVless = server?.vless != null

            // Порядок: первый порт AmneziaWG коротким окном → Reality на том
            // же узле → остальные порты → соседняя страна. Reality идёт по
            // TCP и переживает сети, где UDP не проходит вовсе, — на сотовой
            // связи это обычное дело, а раньше до него доходили только после
            // полутора минут перебора портов. Смена протокола дешевле смены
            // страны: человек остаётся там, где выбрал.
            var startedAt = System.currentTimeMillis()
            var result = tunnel.connect(
                prepared,
                ports,
                if (hasVless) TunnelManager.Stage.FIRST else TunnelManager.Stage.ALL,
            )
            reportTunnelResult(result, startedAt, if (hasVless) 1 else maxOf(1, ports.size))
            if (result == TunnelManager.Result.NO_HANDSHAKE && hasVless) {
                if (tryVless()) return@launch
                if (phase != Phase.CONNECTING) return@launch
                startedAt = System.currentTimeMillis()
                result = tunnel.connect(prepared, ports, TunnelManager.Stage.REST)
                reportTunnelResult(result, startedAt, maxOf(1, ports.size - 1))
            }
            when (result) {
                TunnelManager.Result.CONNECTED -> {
                    phase = Phase.ON
                    startForegroundNotice()
                    startTimer()
                }
                TunnelManager.Result.NO_HANDSHAKE -> {
                    // Все порты и второй протокол промолчали — соседняя
                    // страна: у неё другая сеть, другой адрес и своя
                    // обфускация.
                    if (!failoverToAnotherServer()) {
                        phase = Phase.OFF
                        connectionError = s.errNoHandshake
                        stopForegroundNotice()
                    }
                }
                TunnelManager.Result.FAILED -> {
                    phase = Phase.OFF
                    connectionError = s.errTunnelFailed
                    stopForegroundNotice()
                }
                TunnelManager.Result.CANCELLED -> {
                    // Отменили сами (кнопкой «Отключить») — без плашки ошибки.
                    phase = Phase.OFF
                    stopForegroundNotice()
                }
            }
        }
    }

    /**
     * Поднимает запасной протокол на нынешнем узле. `true` — получилось.
     *
     * Доступ к Reality панель присылает вместе с обычным конфигом, ходить за
     * ним отдельно не нужно. Узел его не дал — тихо уходим: отсутствие
     * запасного пути не ошибка, просто пробовать нечего.
     */
    /** Итог перебора портов AmneziaWG — в телеметрию; отмену не считаем. */
    private fun reportTunnelResult(result: TunnelManager.Result, startedAt: Long, attempts: Int) {
        when (result) {
            TunnelManager.Result.CONNECTED -> reportAttempt("awg", true, startedAt, attempts)
            TunnelManager.Result.NO_HANDSHAKE ->
                reportAttempt("awg", false, startedAt, attempts, error = "no handshake")
            TunnelManager.Result.FAILED ->
                reportAttempt("awg", false, startedAt, attempts, stage = "engine", error = "tunnel failed")
            TunnelManager.Result.CANCELLED -> Unit
        }
    }

    private suspend fun tryVless(): Boolean {
        val access = server?.vless ?: return false

        // Снимаем недоподнятый AmneziaWG: Android держит один туннель на
        // приложение, и вторая служба просто не получит дескриптор.
        withContext(tunnelDispatcher) { runCatching { tunnel.disconnect() } }

        val startedAt = System.currentTimeMillis()
        VlessVpnService.start(getApplication(), access)

        // Ждём, пока служба доложит. Пятнадцати секунд хватает с запасом:
        // рукопожатие Reality — это одно TLS-соединение, не перебор портов.
        val deadline = System.currentTimeMillis() + 15_000
        while (System.currentTimeMillis() < deadline) {
            when (VlessVpnService.state) {
                VlessVpnService.State.RUNNING -> {
                    activeProtocol = Protocol.VLESS
                    phase = Phase.ON
                    startForegroundNotice()
                    startTimer()
                    reportAttempt("vless", true, startedAt, 1, port = access.port)
                    return true
                }
                VlessVpnService.State.FAILED -> {
                    connectionError = null
                    reportAttempt("vless", false, startedAt, 1, port = access.port, error = "vless failed")
                    return false
                }
                else -> delay(250)
            }
        }
        VlessVpnService.stop(getApplication())
        reportAttempt("vless", false, startedAt, 1, port = access.port, error = "vless timeout")
        return false
    }

    /**
     * Уводит на соседнюю страну, когда текущая молчит на всех портах.
     *
     * По одной попытке на страну и ни одного круга: пройти список дважды —
     * это минуты «подключение…» вместо честного «не вышло», после которого
     * человек хотя бы сменит сеть. Не помогло — возвращаем его выбор, чтобы
     * в списке не осталась страна, которую он не выбирал.
     */
    private suspend fun failoverToAnotherServer(): Boolean {
        val list = panelServers
        if (list.size < 2) return false

        val started = selectedServerIndex
        for (step in 1 until list.size) {
            val candidate = (started + step) % list.size
            val info = list.getOrNull(candidate) ?: continue
            val config = info.config
            if (config.isNullOrBlank()) continue

            server = info
            selectedServerIndex = candidate
            val prepared = buildConfigForConnect(config)
            val startedAt = System.currentTimeMillis()
            val outcome = tunnel.connect(prepared, info.altPorts)
            reportTunnelResult(outcome, startedAt, maxOf(1, info.altPorts.size))
            if (outcome == TunnelManager.Result.CONNECTED) {
                prefs.edit().putInt("selectedServer", candidate).apply()
                persistServer()
                phase = Phase.ON
                startForegroundNotice()
                startTimer()
                return true
            }
        }

        list.getOrNull(started)?.let { server = it }
        selectedServerIndex = started
        return false
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
            var nextWatch = 5
            while (true) {
                delay(500)
                val elapsed = ((System.currentTimeMillis() - startedAt) / 1000L).toInt()
                if (elapsed != seconds) seconds = elapsed

                // За основным протоколом следит supervision внутри
                // TunnelManager, а запасной там не виден вовсе: его туннель
                // держит другая служба. Присматриваем сами — иначе упавший
                // Reality остался бы на экране «подключено».
                if (activeProtocol == Protocol.VLESS && elapsed >= nextWatch) {
                    nextWatch = elapsed + 5
                    if (VlessVpnService.state != VlessVpnService.State.RUNNING) {
                        timerJob = null
                        connectionError = s.errTunnelDropped
                        disconnect()
                        return@launch
                    }
                }
            }
        }
    }

    fun disconnect() {
        connectJob?.cancel()
        timerJob?.cancel()
        timerJob = null
        connectionError = null

        phase = Phase.DISCONNECTING

        connectJob = viewModelScope.launch {
            // Снимаем оба: какой бы ни был поднят, второй в это время должен
            // молчать. Служба запасного протокола на «стоп» при незапущенной
            // ничего не делает, поэтому звать её безопасно всегда.
            runCatching { tunnel.disconnect() }
            runCatching { VlessVpnService.stop(getApplication()) }

            activeProtocol = Protocol.AWG
            stopForegroundNotice()
            phase = Phase.OFF
            connectJob = null
        }
    }

    /**
     * Время работы, а рядом — пометка, если путь запасной.
     *
     * Без неё человек видит только изменившееся поведение сети и не понимает,
     * почему: Reality идёт через прокси и отличается от прямого туннеля.
     */
    val durationWithProtocol: String
        get() = if (activeProtocol == Protocol.VLESS) {
            formattedDuration + " · " + s.viaBackup
        } else {
            formattedDuration
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
                countryCode = (ru ?: en)?.optString("country_code")?.takeIf { it.isNotEmpty() }
                    ?: current.countryCode,
            )
            persistServer()
        }
    }

    private fun fetchGeo(host: String, lang: String): JSONObject? = runCatching {
        // ipwho.is принимает только IP — доменный Endpoint резолвим сами.
        val ip = if (host.any { it.isLetter() }) {
            java.net.InetAddress.getByName(host).hostAddress ?: return@runCatching null
        } else host
        val url = URL("https://ipwho.is/$ip?lang=$lang&fields=success,country,country_code,city")
        val connection = url.openConnection() as HttpURLConnection
        connection.connectTimeout = 8000
        connection.readTimeout = 8000
        val text = connection.inputStream.bufferedReader().use { it.readText() }
        JSONObject(text).takeIf { it.optBoolean("success") }
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

        if (text != null && isWgQuick(text)) {
            return ServerInfo(host = endpointHost(text) ?: "", config = text)
        }

        decodeQCompressedJson(data)?.let { json -> return fromJson(json) }

        if (text != null) {
            parseJson(text)?.let { json -> return fromJson(json) }
        }

        return null
    }

    private fun fromJson(json: Any): ServerInfo {
        val config = findConfig(json)
        val host = findHost(json)
            ?: config?.let { endpointHost(it) }
            ?: ""
        return ServerInfo(host = host, config = config)
    }

    private fun findConfig(node: Any?): String? {
        when (node) {
            is JSONObject -> {
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

    private fun looksLikeJson(text: String): Boolean {
        val trimmed = text.trimStart()
        return trimmed.startsWith("{") || trimmed.startsWith("[\"")
    }

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
