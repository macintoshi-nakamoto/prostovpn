package com.prostovpn.desktop

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.UUID
import java.util.concurrent.TimeUnit
import java.util.prefs.Preferences
import java.util.zip.Inflater
import kotlin.system.exitProcess

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
 * DISCONNECTING — не косметика. Снятие туннеля занимает секунды: пока не
 * исчез адаптер, трафик всё ещё идёт в VPN. Показывать в это время
 * «отключено» — врать пользователю о том, куда уходят его пакеты.
 */
enum class Phase { OFF, CONNECTING, DISCONNECTING, ON }

/** Что сейчас происходит с обновлением. */
enum class UpdateStage { CHECKING, IDLE, DOWNLOADING, INSTALLING }

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
    /** Токен сессии в панели. Пусто — человек не вошёл. */
    var panelToken by mutableStateOf(prefs.get("panelToken", "") ?: "")
        private set
    var accountName by mutableStateOf(prefs.get("accountName", "") ?: "")
        private set
    var accountPublicId by mutableStateOf(prefs.get("accountPublicId", "") ?: "")
        private set
    var subscriptionDaysLeft by mutableIntStateOf(prefs.getInt("daysLeft", 0))
        private set
    var trafficUsedBytes by mutableStateOf(prefs.getLong("trafficUsed", 0L))
        private set
    /** -1 — безлимит. */
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
    var renewUrl by mutableStateOf(prefs.get("renewUrl", "") ?: "")
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

    /** Страны, выданные панелью. Пусто — подписка кончилась. */
    var panelServers by mutableStateOf<List<ServerInfo>>(emptyList())
        private set

    // Вход только по аккаунту: гостевого режима нет, страны выдаёт панель.
    val isLoggedIn get() = panelToken.isNotEmpty() || server != null

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

    fun changeAutoStart(enabled: Boolean) {
        val previous = autoStart
        autoStart = enabled
        prefs.putBoolean("autoStart", enabled)

        val exePath = if (enabled) appExePath() else null
        // Запуск из Gradle или IDE: пути до exe нет, и прописывать вместо
        // приложения java.exe нельзя. Меняем только настройку — и тумблер
        // не откатываем, иначе разработчик увидит вечно выключенный.
        if (!WindowsTunnel.isWindows || (enabled && exePath == null)) return

        scope.launch(Dispatchers.IO) {
            val ok = writeAutoStartEntry(exePath)
            withContext(Dispatchers.Main) {
                if (ok) {
                    if (exePath != null) prefs.put("autoStart.path", exePath) else prefs.remove("autoStart.path")
                } else {
                    // Реестр не поддался — тумблер обязан показать правду.
                    // Иначе интерфейс обещает автозапуск, которого нет.
                    autoStart = previous
                    prefs.putBoolean("autoStart", previous)
                }
            }
        }
    }

    /**
     * Путь до установленного приложения.
     *
     * jpackage.app-path выставляет лаунчер установленной сборки. Полагаться
     * на ProcessHandle нельзя: под Gradle он вернёт java.exe, и в
     * автозагрузку попадёт JVM вместо приложения, поэтому всё, что не
     * заканчивается на .exe, отбрасываем.
     */
    private fun appExePath(): String? {
        val path = System.getProperty("jpackage.app-path")
            ?: runCatching { ProcessHandle.current().info().command().orElse(null) }.getOrNull()
        return path?.takeIf { it.endsWith(".exe", ignoreCase = true) }
    }

    /**
     * Прописывает приложение в автозагрузку текущего пользователя или
     * убирает оттуда ([exePath] = null).
     *
     * Ветка HKCU — прав администратора не требует. Путь пишем в кавычках:
     * приложение стоит в «C:\Program Files\Prosto VPN\», а без кавычек
     * Windows на таком пути сначала пробует запустить C:\Program.exe.
     * Скрипт отдаём base64 (-EncodedCommand), как и при поднятии прав в
     * WindowsTunnel: пути с пробелами и кириллицей не ломаются о двойное
     * экранирование.
     *
     * @return изменился ли реестр на самом деле
     */
    private fun writeAutoStartEntry(exePath: String?): Boolean {
        if (!WindowsTunnel.isWindows) return false
        fun psQuote(value: String) = "'" + value.replace("'", "''") + "'"

        val action = if (exePath == null) {
            // Значения может и не быть — это не ошибка, а нормальный случай.
            "Remove-ItemProperty -Path ${psQuote(RUN_KEY)} -Name ${psQuote(RUN_VALUE)} -ErrorAction SilentlyContinue"
        } else {
            "Set-ItemProperty -Path ${psQuote(RUN_KEY)} -Name ${psQuote(RUN_VALUE)} " +
                "-Value ${psQuote("\"" + exePath + "\"")}"
        }
        val script = """
            ${'$'}ErrorActionPreference = 'Stop'
            try { $action; exit 0 } catch { exit 1 }
        """.trimIndent()
        val encoded = java.util.Base64.getEncoder()
            .encodeToString(script.toByteArray(Charsets.UTF_16LE))

        return runCatching {
            val process = ProcessBuilder(
                "powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded,
            ).redirectErrorStream(true).start()
            if (!process.waitFor(15, TimeUnit.SECONDS)) {
                process.destroyForcibly()
                return false
            }
            process.exitValue() == 0
        }.getOrDefault(false)
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

    /** Для какого адреса сервера посчитан [cachedAllowedIps]. */
    private var cachedAllowedIpsKey: String? = null

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
        // Переключение страны меняет и конфиг, который уйдёт в туннель.
        panelServers.getOrNull(index)?.let {
            server = it
            persistServer()
        }
    }

    fun displayServers(): List<DisplayServer> {
        val t = s
        // Страны из панели: их может быть несколько, и выбирает человек.
        if (panelServers.isNotEmpty()) {
            return panelServers.map { item ->
                val flag = item.countryCode?.takeIf { it.isNotEmpty() }?.let { flagEmoji(it) } ?: "🌐"
                DisplayServer(
                    flag = flag,
                    name = item.countryFor(lang).orEmpty(),
                    sub = item.cityFor(lang).orEmpty(),
                )
            }
        }
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
        }
        loadTunnelFiles()
        /*
        Индекс выбранной страны здесь не трогаем. Список панели ещё не
        получен, displayServers() отдаёт один восстановленный сервер — и
        сохранённый выбор второй или третьей страны затирался нулём прямо
        в настройках, то есть навсегда. Индекс проверяет applyPanelServers
        по фактическому списку, а показ прикрывает coerceAtMost
        в currentServer.
        */
        // Сессия могла протухнуть, а список стран — измениться, пока
        // приложение было закрыто.
        refreshPanelServers()
        // Обновление ставится в другой каталог, и в автозагрузке остаётся
        // путь до прежнего exe — автозапуск молча ломается. Поэтому сверяем
        // сохранённый путь с фактическим, а не наличие значения.
        if (autoStart) {
            val exePath = appExePath()
            if (exePath != null && exePath != prefs.get("autoStart.path", null)) {
                scope.launch(Dispatchers.IO) {
                    if (writeAutoStartEntry(exePath)) {
                        withContext(Dispatchers.Main) { prefs.put("autoStart.path", exePath) }
                    }
                }
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
        // Сам ключ не сохраняем: его никто не читал, а java.util.prefs
        // бросает на значении длиннее 8192 символов — контейнер Amnezia
        // легко перешагивает предел, и вход по ключу валил корутину
        // композиции вместо ошибки на экране. Сессия переживает перезапуск
        // за счёт server.host и server.config.
        panelServers = emptyList()
        server = info
        selectServer(0)
        persistServer()
        return true
    }

    suspend fun login(login: String, password: String): Result<Unit> =
        PanelApi.login(login, password).map { applySession(it) }

    private fun applySession(session: PanelApi.Session) {
        panelToken = session.token
        accountName = session.name ?: session.login
        accountPublicId = session.publicId
        applySubscription(session)

        prefs.put("panelToken", session.token)
        prefs.put("accountName", accountName)
        prefs.put("accountPublicId", accountPublicId)
        // Сбрасываем на диск немедленно. Preferences пишутся отложенно,
        // фоновым потоком, и внезапная перезагрузка теряет последние
        // записи — а теряется при этом именно токен, то есть вход.
        runCatching { prefs.flush() }

        applyPanelServers(session.servers)
    }

    /**
     * Переносит подписку из ответа панели в состояние и настройки.
     *
     * Одним местом на оба вызова — вход и обновление списка стран. Пока их
     * было два, любое новое поле требовалось не забыть дважды.
     */
    private fun applySubscription(session: PanelApi.Session) {
        subscriptionDaysLeft = session.daysLeft
        trafficUsedBytes = session.trafficUsedBytes
        trafficLimitBytes = session.trafficLimitBytes ?: -1L
        trafficLeftBytes = session.trafficLeftBytes ?: -1L
        trafficLow = session.trafficLow
        expiresSoon = session.expiresSoon
        renewUrl = session.renewUrl.orEmpty()
        panelNotice = session.notice.orEmpty()

        prefs.putInt("daysLeft", session.daysLeft)
        prefs.putLong("trafficUsed", session.trafficUsedBytes)
        prefs.putLong("trafficLimit", trafficLimitBytes)
        prefs.putLong("trafficLeft", trafficLeftBytes)
        prefs.putBoolean("trafficLow", trafficLow)
        prefs.putBoolean("expiresSoon", expiresSoon)
        prefs.put("renewUrl", renewUrl)
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
        scope.launch {
            PanelApi.servers(token)
                .onSuccess { session ->
                    applySubscription(session)
                    applyPanelServers(session.servers)
                }
                .onFailure { error ->
                    // Разлогиниваем ТОЛЬКО когда панель прямо сказала, что
                    // токен не годится. Раньше сюда попадала любая неудача:
                    // пятисотка, перезапуск панели, срабатывание защиты от
                    // частых запросов — и человек, ничего не делавший,
                    // обнаруживал себя на экране входа с потёртыми
                    // настройками. Недоступная панель — это временно, а
                    // стирание сессии необратимо.
                    val status = (error as? PanelApi.PanelException)?.status ?: 0
                    if (status == 401 || status == 403) logout()
                }
        }
    }

    /**
     * Почему вход не состоялся — на языке интерфейса.
     *
     * Раньше на экран уходил текст панели, а он написан по-русски: человек с
     * английским интерфейсом на неверный пароль получал русскую строку.
     * Причину панель называет кодом (`X-Error-Code`), перевод к нему — наш.
     *
     * Панель без кодов — старая. Её текст всё ещё лучше нашего домысла, если
     * интерфейс русский; для английского берём своё, пусть и общее.
     */
    fun loginError(error: Throwable): String {
        val failure = error as? PanelApi.PanelException ?: return s.errPanelUnreachable

        when (failure.code) {
            "bad_credentials" -> return s.errBadCredentials
            "blocked" -> return s.errAccountBlocked
            "disabled" -> return s.errAccountDisabled
            "throttled" -> return tooManyTries(failure.retryAfterSeconds)
        }

        val panelText = failure.message?.takeIf { it.isNotBlank() && lang != "en" }
        return when {
            failure.status == 429 -> tooManyTries(failure.retryAfterSeconds)
            failure.status == 401 || failure.status == 403 -> panelText ?: s.errBadCredentials
            failure.status >= 500 -> panelText ?: s.errPanelFault
            else -> panelText ?: s.errPanelFault
        }
    }

    private fun tooManyTries(retryAfterSeconds: Int): String {
        if (retryAfterSeconds <= 0) return s.errTooManyTries
        // Округляем вверх: «через 0 мин» — это не ответ на вопрос «когда».
        val minutes = ((retryAfterSeconds + 59) / 60).coerceAtLeast(1)
        return s.errTooManyTriesIn.format(minutes)
    }

    // --- Обновление ---

    /**
     * Ответ панели про новую версию.
     *
     * Живёт здесь, а не на экране настроек: значок на шестерёнке должен
     * появляться сам, до того как в настройки зайдут.
     */
    var updateCheck by mutableStateOf<Result<PanelUpdate.Info>?>(null)
        private set

    var updateStage by mutableStateOf(UpdateStage.CHECKING)
        private set

    var updatePercent by mutableIntStateOf(0)
        private set

    /**
     * Что помешало обновиться. Держим исключением, а не текстом: перевод у
     * него на экране настроек, вместе с остальными словами про обновление.
     */
    var updateFailure by mutableStateOf<Throwable?>(null)
        private set

    private var updateJob: Job? = null

    /** Есть ли новая версия — по этому рисуется значок на кнопке настроек. */
    val updateAvailable: Boolean
        get() = updateCheck?.getOrNull()?.available == true

    val updateInfo: PanelUpdate.Info?
        get() = updateCheck?.getOrNull()?.takeIf { it.available }

    /**
     * Спрашивает панель о новой версии.
     *
     * Проверка не должна перебивать начатую установку, поэтому во время неё
     * ничего не делаем.
     */
    fun checkUpdate() {
        if (updateStage == UpdateStage.DOWNLOADING || updateStage == UpdateStage.INSTALLING) return
        updateJob?.cancel()
        updateJob = scope.launch {
            updateStage = UpdateStage.CHECKING
            updateFailure = null
            updateCheck = PanelUpdate.check(BuildInfo.VERSION)
            updateStage = UpdateStage.IDLE
        }
    }

    /**
     * Скачивает и ставит обновление: приложение закроется и откроется уже
     * новым. Мастер установки человек не видит, запускать заново не нужно.
     *
     * Порядок именно такой. Сначала права: не дали — рвать VPN было не за
     * чем, остаёмся работать и показываем причину. И только когда помощник
     * с правами запущен, снимаем туннель и уходим с дороги: служба держит
     * prostovpn-tunnel.exe и wintun.dll внутри папки установки, и без этого
     * MSI упрётся в занятые файлы даже после выхода JVM.
     */
    fun installUpdate() {
        val info = updateInfo ?: return
        if (updateStage == UpdateStage.DOWNLOADING || updateStage == UpdateStage.INSTALLING) return

        updateJob?.cancel()
        updateJob = scope.launch {
            updateFailure = null
            updatePercent = 0
            updateStage = UpdateStage.DOWNLOADING

            val file = PanelUpdate.download(info) { updatePercent = it }.getOrElse { problem ->
                updateStage = UpdateStage.IDLE
                updateFailure = problem
                return@launch
            }

            updateStage = UpdateStage.INSTALLING
            val started = PanelUpdate.installAndRestart(file, info.sha256.orEmpty())
            if (started.isFailure) {
                file.delete()
                updateStage = UpdateStage.IDLE
                updateFailure = started.exceptionOrNull()
                return@launch
            }

            if (phase != Phase.OFF) {
                disconnect()
                // Снятие блокирующее и небыстрое; если туннель так и не ушёл,
                // всё равно уходим — помощник уже ждёт нашего выхода.
                withTimeoutOrNull(35_000) { snapshotFlow { phase }.first { it == Phase.OFF } }
            }

            // Штатного exitApplication сюда не дотянуть — окно живёт в Main.kt.
            exitProcess(0)
        }
    }

    fun logout() {
        disconnect()
        // Гасим сессию и на стороне панели: иначе она останется висеть
        // в списке устройств администратора.
        panelToken.takeIf { it.isNotEmpty() }?.let { token ->
            scope.launch { PanelApi.logout(token) }
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
        runCatching { prefs.clear() }
        prefs.put("lang", language)
        // Как и при первом запуске: список исключений разворачивается в
        // ~2000 маршрутов, поэтому по умолчанию выключено (см. split.enabled)
        splitTunnelEnabled = false
        // Значение в автозагрузке переживает prefs.clear(): без явного
        // удаления приложение продолжало бы стартовать с системой после
        // выхода из аккаунта.
        if (autoStart) scope.launch(Dispatchers.IO) { writeAutoStartEntry(null) }
        autoStart = false
        autoConnect = false
        logging = true
        loadTunnelFiles()
    }

    /**
     * java.util.prefs режет значение на 8192 символах и бросает
     * IllegalArgumentException прямо в вызывающую корутину — конфиг из
     * ключа Amnezia легко перешагивает предел и вместо ошибки на экране
     * гасил композицию. Слишком длинное значение не сохраняем, а прежнее
     * стираем: показать чужой конфиг хуже, чем не показать никакого.
     */
    private fun putSafe(key: String, value: String) {
        if (value.length > Preferences.MAX_VALUE_LENGTH) {
            runCatching { prefs.remove(key) }
            return
        }
        runCatching { prefs.put(key, value) }
    }

    /**
     * Пустое значение именно стирает ключ.
     *
     * Пока пустые поля просто пропускались, гео прежнего сервера оставалось
     * в настройках и прилипало к новому: на экране висел чужой город, а
     * refreshGeo уже не перезапрашивал — поля не null, только протухшие.
     */
    private fun putOrRemove(key: String, value: String?) {
        if (value.isNullOrEmpty()) runCatching { prefs.remove(key) } else putSafe(key, value)
    }

    private fun persistServer() {
        val current = server ?: return
        // Именно put: у серверов панели host пустой, а init поднимает
        // сохранённый сервер как раз по наличию этого ключа.
        prefs.put("server.host", current.host)
        putOrRemove("server.country", current.country)
        putOrRemove("server.city", current.city)
        putOrRemove("server.countryEn", current.countryEn)
        putOrRemove("server.cityEn", current.cityEn)
        putOrRemove("server.countryCode", current.countryCode)
        putOrRemove("server.config", current.config)
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
            // Снятие уже идёт — повторное нажатие не должно его перебивать
            Phase.DISCONNECTING -> Unit
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
                // ключи он отвергает целиком, без Address не будет маршрутов.
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
                        WindowsTunnel.Reason.AddressInUse ->
                            s.errAddressInUse + " «" + result.detail + "»"
                        WindowsTunnel.Reason.NoHandshake ->
                            // Журнал движка различает четыре разные беды — без
                            // этого все они выглядят как «просто не работает»
                            listOfNotNull(
                                when (result.diag) {
                                    WindowsTunnel.HandshakeDiag.SILENCE -> s.errHsSilence
                                    WindowsTunnel.HandshakeDiag.PORT_CLOSED -> s.errHsPortClosed
                                    WindowsTunnel.HandshakeDiag.HEADER_MISMATCH -> s.errHsHeader
                                    WindowsTunnel.HandshakeDiag.REJECTED -> s.errHsRejected
                                    WindowsTunnel.HandshakeDiag.BLACKHOLE -> s.errHsBlackhole
                                    WindowsTunnel.HandshakeDiag.KILLSWITCH -> s.errHsKillSwitch
                                    null -> s.errNoHandshake
                                },
                                WgConfig.unsupportedKeys(config)
                                    .takeIf { it.isNotEmpty() }
                                    ?.let { s.errUnsupportedObfuscation + " " + it.joinToString(", ") },
                                s.errLogHint,
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
        /*
        Сам VPN-сервер в туннель не заворачиваем: список исключений
        разворачивается в тысячи подсетей, и адрес сервера легко попадает
        в одну из них — тогда маршрут до него ведёт в туннель, которого ещё
        нет. Адрес зависит от выбранного сервера, поэтому он часть ключа кэша.
        */
        val endpoint = SplitTunnel.endpointCidr(base)
        val cached = cachedAllowedIps
        if (cached != null && cachedAllowedIpsKey == endpoint) {
            return SplitTunnel.applyToConfig(base, cached)
        }

        val content = activeListContent()
        val fromList = if (content == null) emptyList() else SplitTunnel.parseCidrList(content)
        val excluded = fromList + listOfNotNull(endpoint)
        val allowed = SplitTunnel.allowedIpsExcept(excluded)
        cachedAllowedIps = allowed
        cachedAllowedIpsKey = endpoint
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
        /*
        Держим DISCONNECTING, пока туннель действительно не снят. Раньше
        здесь сразу ставилось OFF, а снятие уходило в фон: несколько секунд
        интерфейс показывал «отключено», хотя адаптер жил и весь трафик
        по-прежнему шёл через VPN.
        */
        phase = Phase.DISCONNECTING
        // seconds не обнуляем: уходящий таймер дофейдится с последним значением
        connectJob = scope.launch {
            val down = withContext(Dispatchers.IO) {
                runCatching { tunnel.disconnect() }.getOrDefault(false)
            }
            phase = Phase.OFF
            connectJob = null
            if (!down) connectionError = s.errDisconnectStuck
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

    /*
    Геолокацию сервера у стороннего сервиса больше не спрашиваем.

    Запрос уходил открытым HTTP и содержал в адресе IP узла, к которому
    человек собирается подключиться, — то есть провайдеру и любому
    промежуточному узлу выдавался ровно тот адрес, который надо
    заблокировать. Гео серверов панели и так приходит вместе со списком
    стран, а утекал именно путь без панели: вход по ключу vpn://, где узел
    чужой и цензору неизвестен. Страна и город там — косметика в одной
    строке, displayServers() на этот случай показывает host.

    Если гео понадобится вернуть — только через панель (свой эндпоинт,
    запрос через PanelApi.request с пиннингом), а не через чужой сервис.
    */

    /** Только для офскрин-скриншотов (задача gradle screenshots). */
    internal fun previewAs(loggedIn: Boolean, previewPhase: Phase, previewSeconds: Int = 754) {
        panelToken = if (loggedIn) "preview" else ""
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

    companion object {
        const val DEFAULT_FILE_ID = "default"
        const val DEFAULT_FILE_NAME = "ru-split-tunnel.json"

        private const val RUN_KEY = "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run"

        /** Имя значения в Run — то же, что packageName у jpackage. */
        private const val RUN_VALUE = "Prosto VPN"

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
