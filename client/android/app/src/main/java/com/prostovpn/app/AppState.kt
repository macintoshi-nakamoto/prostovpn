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

/**
 * Как часто перечитывать подписку, пока экран открыт.
 *
 * Тот же ритм, что у десктопного клиента и у стража сессии в TunnelManager:
 * этим опросом приложение узнаёт, что устройство отвязали, кончился трафик
 * или продлилась подписка.
 */
private const val ACCOUNT_POLL_MS = 60 * 1000L

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
    /** Токен сессии в панели. Пусто — человек не вошёл. */
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

    /** -1 означает безлимит. */
    var trafficLimitBytes by mutableStateOf(prefs.getLong("trafficLimit", -1L))
        private set

    /** -1 — безлимит. Остаток считает панель, а не приложение. */
    var trafficLeftBytes by mutableStateOf(prefs.getLong("trafficLeft", -1L))
        private set

    /** Трафика осталось мало — на главном экране горит предупреждение. */
    var trafficLow by mutableStateOf(prefs.getBoolean("trafficLow", false))
        private set

    /** Подписка кончается — пора показать кнопку продления. */
    var expiresSoon by mutableStateOf(prefs.getBoolean("expiresSoon", false))
        private set

    /** Куда ведёт кнопка продления. Пусто — продлевать пока незачем. */
    var renewUrl by mutableStateOf(prefs.getString("renewUrl", "").orEmpty())
        private set

    /**
     * Почему панель не дала ни одной страны.
     *
     * Пустой список без объяснения человек читает как «приложение
     * сломалось»: он ввёл логин с паролем, вход прошёл — и дальше пустой
     * экран. Текст пишет панель, здесь его только показывают.
     */
    var panelNotice by mutableStateOf("")
        private set

    /**
     * Почему человека выкинуло на экран входа.
     *
     * Заполняется, когда панель погасила сессию, — устройство отключили из
     * личного кабинета или админки. Без объяснения это выглядело как
     * поломка: приложение молча оказывалось на форме входа, и человек шёл
     * в поддержку со «слетел аккаунт». Живёт только в памяти: logout()
     * чистит prefs, а причина обязана его пережить. Читается один раз
     * экраном входа.
     */
    var signedOutReason by mutableStateOf("")
        private set

    /** Экран входа забирает причину: показывается она ровно один раз. */
    fun consumeSignedOutReason(): String = signedOutReason.also { signedOutReason = "" }

    /** Страны, выданные панелью. Пусто — подписка кончилась. */
    var panelServers by mutableStateOf<List<ServerInfo>>(emptyList())
        private set

    /**
     * Обновление приложения.
     *
     * Живёт здесь, а не на экране настроек: проверка стартует вместе с
     * приложением, а баннер обязательного обновления рисуется на главном
     * экране до всякого захода в настройки.
     */
    val updates: UpdateManager by lazy { UpdateManager(getApplication(), viewModelScope) }

    // Вход только по аккаунту: гостевого режима нет, страны выдаёт панель.
    val isLoggedIn get() = panelToken.isNotEmpty() || server != null

    private var connectJob: Job? = null
    private var timerJob: Job? = null

    var pendingPermissionIntent by mutableStateOf<android.content.Intent?>(null)
        private set
    private var pendingConfig: String? = null

    private val tunnel: TunnelManager by lazy {
        TunnelManager.getInstance(getApplication()).also { manager ->
            /*
            Получателя указываем явно. Внутри apply { } им был сам TunnelManager,
            и вызов disconnect() уходил в туннель вместо этого метода: интерфейс
            снимался, а phase оставалась ON, и экран показывал «подключено», пока
            через пять секунд его не поправит проверка живости.
            */
            manager.onStateChange = { up ->
                if (!up && phase == Phase.ON) this@AppState.disconnect()
            }
        }
    }

    /**
     * Поднимает постоянное уведомление на время работы туннеля.
     *
     * Не косметика: туннель wg-go живёт в процессе приложения, а оболочки
     * Huawei/Honor, Xiaomi и Oppo выгружают фоновые процессы по своим правилам.
     * Foreground-состояние — единственное, что они уважают.
     */
    private fun startForegroundNotice() {
        val where = currentServer?.name?.takeIf { it.isNotEmpty() }
        val status = if (where != null) "${s.connected} · $where" else s.connected
        VpnForegroundService.start(getApplication(), status, s.notifDisconnect)
    }

    /**
     * Foreground на время самого подключения, а не только после него.
     *
     * Рукопожатие с ретраями занимает до минуты, и всё это время процесс —
     * обычный фоновый: человеку достаточно свернуть приложение (а на
     * Huawei — просто погасить экран), чтобы оболочка убила процесс посреди
     * подключения. Снаружи это выглядело как «вечное подключение»: спиннер
     * крутится, процесс давно мёртв.
     */
    private fun startConnectingNotice() {
        VpnForegroundService.start(getApplication(), s.connectingTxt, s.notifDisconnect)
    }

    private fun stopForegroundNotice() {
        VpnForegroundService.stop(getApplication())
    }

    @OptIn(ExperimentalCoroutinesApi::class)
    private val tunnelDispatcher = Dispatchers.IO.limitedParallelism(1)

    // Стартовый язык — из системной локали, а не всегда русский: приложение
    // ставят и не только с русскоязычной прошивкой. Сохранённый выбор важнее.
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

    // --- Настройки ---

    // Полный туннель по умолчанию: один маршрут вместо ~2000, работает на
    // любом Android. Раздельное включается вручную в настройках.
    var splitTunnelEnabled by mutableStateOf(prefs.getBoolean("split.enabled", false))
        private set
    var autoConnect by mutableStateOf(prefs.getBoolean("autoConnect", false))
        private set

    // Кэш один: список AllowedIPs больше не зависит от наличия IPv6-адреса,
    // ::/0 добавляется всегда — иначе библиотека разблокирует IPv6 мимо туннеля
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
        /*
        ::/0 в маршрутах туннеля стоит всегда, даже без IPv6-адреса у
        интерфейса, — как и в ветке раздельного туннелирования ниже. Иначе
        библиотека awg при полном отсутствии IPv6-маршрутов зовёт
        allowFamily(AF_INET6), и весь IPv6 уходит МИМО туннеля с настоящим
        адресом абонента: на мобильных сетях с IPv6 (обычных у операторов, и
        особенно у Huawei) двухстековые сайты открывались напрямую и видели
        реальную страну — «VPN как будто не работает». Прежняя ветка без ::/0
        именно этот перекос и давала. Узел без IPv6-аплинка завёрнутый IPv6
        гасит, и приложения переходят на IPv4 через туннель — без утечки.
        */
        val withDns = SplitTunnel.ensureMtu(SplitTunnel.ensureDns(base))
        if (!splitTunnelEnabled) {
            return SplitTunnel.applyToConfig(withDns, "0.0.0.0/0, ::/0")
        }
        val allowed = cachedAllowedIps ?: withContext(Dispatchers.Default) {
            SplitTunnel.allowedIpsExcept(excludeCidrs())
        }.also { cachedAllowedIps = it }
        return SplitTunnel.applyToConfig(withDns, allowed)
    }

    // --- Серверы ---

    var selectedServerIndex by mutableIntStateOf(prefs.getInt("selectedServer", 0))
        private set

    fun selectServer(index: Int) {
        // Переключение страны меняет и конфиг, который уйдёт в туннель.
        panelServers.getOrNull(index)?.let {
            server = it
            persistServer()
        }
        selectedServerIndex = index
        prefs.edit().putInt("selectedServer", index).apply()
    }

    fun displayServers(): List<DisplayServer> {
        // Стран из панели может быть несколько, и выбирает человек.
        if (panelServers.isNotEmpty()) {
            return panelServers.map { item ->
                DisplayServer(
                    flag = item.countryCode?.takeIf { it.isNotEmpty() }?.let { flagEmoji(it) }.orEmpty(),
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
            // Когда геолокация не определилась, обе строки падали в один и тот же
            // хост, и карточка показывала один IP дважды — вместо этого оставляем
            // вторую строку пустой
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
            )
            refreshGeo()
        }
        loadTunnelFiles()
        if (selectedServerIndex >= displayServers().size) {
            selectServer(0)
        }
        restoreRunningTunnel()
        // Сессия могла протухнуть, а список стран — измениться, пока
        // приложение было закрыто. И дальше сверяемся раз в минуту.
        refreshPanelServers()
        startAccountWatch()
        // Версию спрашиваем сразу, не дожидаясь захода в настройки:
        // обязательное обновление должно встретить человека баннером на
        // главном — и дойти даже до того, кто ещё не вошёл.
        updates.check()
    }

    /**
     * Подхватывает уже поднятый туннель при запуске приложения.
     *
     * Систему VPN переживает смерть процесса, а на Huawei и Honor процесс
     * убивают постоянно. Без этого приложение открывалось с «Отключено»
     * при работающем VPN, и нажатие на кнопку пыталось поднять туннель
     * поверх живого.
     */
    private fun restoreRunningTunnel() {
        viewModelScope.launch {
            val up = withContext(tunnelDispatcher) { tunnel.isUp }
            if (up && phase == Phase.OFF) {
                phase = Phase.ON
                startForegroundNotice()
                startTimer()
            }
        }
    }

    // --- Вход ---

    /**
     * Вход по логину и паролю из панели.
     *
     * Пароль проверяет сервер: страны выдаются только оплаченной учётной
     * записи, и обойти это, вставив чужой ключ, нельзя.
     */
    /**
     * Вход по ключу vpn://.
     *
     * Второй способ рядом с логином и паролем: ключ подключает один
     * конкретный сервер и работает без учётной записи в панели.
     */
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

    /**
     * Постоянный идентификатор установки — для лимита устройств.
     *
     * Без него панель считала переустановку приложения вторым телефоном:
     * каждая переустановка съедала слот тарифа, и лимит забивался копиями
     * одного и того же устройства. Случайный UUID, а не ANDROID_ID: тот
     * привязан к прошивке и утекать ему в панель незачем.
     */
    private fun installId(): String {
        prefs.getString("installId", null)?.let { return it }
        val fresh = java.util.UUID.randomUUID().toString()
        prefs.edit().putString("installId", fresh).apply()
        return fresh
    }

    /** «Samsung SM-S911B» в списке устройств понятнее, чем пустая строка. */
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

    /**
     * Переносит подписку из ответа панели в состояние и настройки.
     *
     * Одним местом на оба вызова — вход и обновление списка стран. Пока их
     * было два, любое новое поле требовалось не забыть дважды.
     */
    private fun applySubscription(subscription: PanelApi.Subscription, notice: String?) {
        subscriptionDaysLeft = subscription.daysLeft
        trafficUsedBytes = subscription.trafficUsedBytes
        trafficLimitBytes = subscription.trafficLimitBytes ?: -1L
        trafficLeftBytes = subscription.trafficLeftBytes ?: -1L
        trafficLow = subscription.trafficLow
        expiresSoon = subscription.expiresSoon
        renewUrl = subscription.renewUrl.orEmpty()
        // notice в prefs не пишем: это объяснение конкретного ответа панели,
        // протухшее показывать хуже, чем никакое
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

    private fun applyPanelServers(list: List<ServerInfo>) {
        panelServers = list
        if (list.isEmpty()) {
            server = null
            return
        }
        if (selectedServerIndex !in list.indices) selectServer(0)
        server = list[selectedServerIndex.coerceIn(list.indices)]
        persistServer()
    }

    /** Перечитывает страны: подписку могли продлить или закрыть. */
    fun refreshPanelServers() {
        val token = panelToken
        if (token.isEmpty()) return
        viewModelScope.launch(Dispatchers.IO) {
            val result = runCatching { PanelApi.servers(token) }
            withContext(Dispatchers.Main) {
                result
                    .onSuccess { reply ->
                        // Страны были, а теперь их нет — доступ закрыли, пока
                        // приложение работало: кончился трафик, срок или
                        // устройство отвязали из кабинета.
                        val lostAccess = reply.servers.isEmpty() && panelServers.isNotEmpty()
                        applySubscription(reply.subscription, reply.notice)
                        applyPanelServers(reply.servers.map { it.toServerInfo() })
                        if (lostAccess && (phase == Phase.ON || phase == Phase.CONNECTING)) {
                            disconnect()
                        }
                    }
                    .onFailure { error ->
                        // Разлогиниваем ТОЛЬКО когда панель прямо сказала, что
                        // токен не годится. Раньше сюда попадала любая неудача:
                        // пятисотка, перезапуск панели, моргнувшая сеть — и
                        // человек, ничего не делавший, обнаруживал себя на
                        // экране входа с потёртыми настройками. Недоступная
                        // панель — это временно, а стирание сессии необратимо.
                        val status = (error as? PanelApi.PanelException)?.status ?: 0
                        if (status == 401 || status == 403) {
                            logout()
                            // Именно ПОСЛЕ logout: он чистит prefs и состояние,
                            // а причина живёт в памяти и должна дожить до
                            // экрана входа.
                            signedOutReason = s.noticeRemoteSignout
                        }
                    }
            }
        }
    }

    /**
     * Периодический опрос панели, пока экран жив.
     *
     * До этого refreshPanelServers не звал вообще никто: список стран
     * замирал на момент входа, отвязанное из кабинета устройство работало
     * до переустановки, а о кончившемся трафике человек узнавал только по
     * переставшему работать интернету. Минута — тот же ритм, что у
     * десктопного клиента и у стража в [TunnelManager]; сам запрос — лёгкий
     * GET, посильный панели даже от тысяч приложений.
     */
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
        prefs.edit().clear().apply()
        // Язык сохраняем, а флаг миграции возвращаем сразу: без него дефолты
        // полей в памяти и в prefs разъедутся до перезапуска
        prefs.edit()
            .putString("lang", language)
            .putBoolean("fulltunnel.migrated", true)
            .putBoolean("split.enabled", false)
            .apply()
        cachedAllowedIps = null
        // Полный туннель — как дефолт после установки
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
        // Foreground с первой секунды: рукопожатие на плохой сети занимает до
        // минуты, и без уведомления оболочка (особенно Huawei) успевает убить
        // процесс, стоит человеку свернуть приложение или погасить экран.
        startConnectingNotice()
        connectJob = viewModelScope.launch {
            val prepared = buildConfigForConnect(config)
            // Без withContext: connect сам сериализуется и сам уходит на IO,
            // а ожидание рукопожатия обязано оставаться отменяемым
            val result = tunnel.connect(prepared)
            when (result) {
                TunnelManager.Result.CONNECTED -> {
                    phase = Phase.ON
                    startForegroundNotice()
                    startTimer()
                }
                TunnelManager.Result.NO_HANDSHAKE -> {
                    // Туннель поднялся, но сервер молчит — честно говорим об
                    // этом, а не показываем ложное «подключено»
                    phase = Phase.OFF
                    connectionError = s.errNoHandshake
                    stopForegroundNotice()
                }
                TunnelManager.Result.FAILED -> {
                    phase = Phase.OFF
                    connectionError = s.errTunnelFailed
                    stopForegroundNotice()
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
        // Гостевой режим: туннеля нет, соединение имитированное. Проверять
        // живость нечего — иначе через два промаха таймер «обрывал» связь,
        // которой не было.
        val real = server?.config?.isNotBlank() == true
        timerJob = viewModelScope.launch {
            var misses = 0
            var nextCheck = 5
            var lastRx = -1L
            while (true) {
                delay(500)
                val elapsed = ((System.currentTimeMillis() - startedAt) / 1000L).toInt()
                if (elapsed != seconds) seconds = elapsed
                if (!real) continue

                /*
                Туннель может умереть сам: сервер пропал, сеть сменилась,
                система прибила процесс. Без этой проверки экран показывал
                «подключено» и бодро считал секунды, пока наружу не уходило
                ничего. Проверяем раз в пять секунд, а не каждые полсекунды:
                опрос движка не бесплатный.
                */
                if (elapsed < nextCheck) continue
                nextCheck = elapsed + 5

                val alive = withContext(tunnelDispatcher) {
                    if (!tunnel.isUp) return@withContext false
                    // Идущий трафик — доказательство жизни даже до того, как
                    // подойдёт срок следующего рукопожатия
                    val rx = tunnel.receivedBytes()
                    val moving = rx >= 0 && lastRx >= 0 && rx > lastRx
                    lastRx = rx
                    tunnel.isHealthy() || moving
                }

                // Одиночный промах не считаем: опрос изредка не проходит,
                // а ложное отключение хуже пяти секунд задержки
                misses = if (alive) 0 else misses + 1
                if (misses >= 2) {
                    timerJob = null
                    phase = Phase.OFF
                    connectionError = s.errTunnelDropped
                    stopForegroundNotice()
                    viewModelScope.launch { runCatching { tunnel.disconnect() } }
                    return@launch
                }
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
            runCatching { tunnel.disconnect() }
            // Уведомление снимаем только когда интерфейс действительно снят: пока
            // он жив, «подключено» в шторке — правда, а не задержка отрисовки
            stopForegroundNotice()
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
