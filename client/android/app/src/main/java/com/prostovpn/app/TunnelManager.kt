package com.prostovpn.app

import android.content.Context
import android.content.Intent
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.runInterruptible
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import org.amnezia.awg.backend.Backend
import org.amnezia.awg.backend.GoBackend
import org.amnezia.awg.backend.Tunnel
import org.amnezia.awg.config.Config
import java.io.BufferedReader
import java.io.StringReader

class TunnelManager(context: Context) {

    private val appContext = context.applicationContext

    /**
     * Чем закончилось подключение.
     *
     * UP тут — это не «интерфейс поднялся», а «сервер ответил рукопожатием».
     * Голый VpnService поднимается всегда, даже когда сервер молчит, и
     * приложение показывало «подключено», хотя наружу не уходило ничего.
     */
    enum class Result {
        /** Рукопожатие состоялось — VPN действительно работает. */
        CONNECTED,

        /** Интерфейс поднят, но сервер не ответил: молчит порт, ключ или сеть. */
        NO_HANDSHAKE,

        /** Туннель не удалось поднять вовсе — неверный конфиг или отказ VpnService. */
        FAILED,
    }

    /**
     * Состояние туннеля для интерфейса.
     *
     * Живёт здесь, а не в [AppState], потому что туннель переживает экран:
     * процесс с поднятым VPN работает, когда Activity давно уничтожена, и
     * состоянием в этот момент владеть некому. Экран на него ПОДПИСЫВАЕТСЯ —
     * тогда вернувшийся человек видит то, что есть на самом деле, а не то,
     * что было в момент закрытия окна.
     */
    enum class Status { OFF, CONNECTING, ON, RECONNECTING }

    private val _status = MutableStateFlow(Status.OFF)
    val status: StateFlow<Status> = _status.asStateFlow()

    /** Последняя причина, по которой подключиться не удалось; null — нет причины. */
    @Volatile
    var lastFailure: Result? = null
        private set

    private val backend: Backend = GoBackend(context.applicationContext)

    /*
    Подключение и отключение сериализуем здесь, а не у вызывающего: владельцев
    туннеля трое — экран ([AppState]), Always-on VPN ([App]), который стартует
    вообще без Activity, и собственный надзор. Без общего замка они могли войти
    в setState одновременно.
    */
    private val mutex = Mutex()

    private val tunnel = object : Tunnel {
        override fun getName(): String = "prosto"
        override fun onStateChange(newState: Tunnel.State) {
            onStateChange?.invoke(newState == Tunnel.State.UP)
        }
    }

    var onStateChange: ((Boolean) -> Unit)? = null

    fun parseConfig(configText: String): Config =
        Config.parse(BufferedReader(StringReader(configText)))

    private enum class Handshake { OK, TIMEOUT, INTERFACE_DOWN }

    // --- то, что надо удерживать -------------------------------------------
    //
    // «Хотим быть подключены» — отдельный факт, не выводимый из состояния
    // интерфейса. Интерфейс может быть снят системой, оболочкой или сменой
    // сети; из этого не следует, что человек передумал. Именно этот факт
    // отличает «упало, поднимаем обратно» от «выключили, и правильно».

    @Volatile
    private var wanted: String? = null

    @Volatile
    private var alternatives: List<Int> = emptyList()

    /** Порт, на котором в последний раз получилось; 0 — ещё не получалось. */
    private var rememberedPort: Int
        get() = prefs().getInt(PREF_PORT, 0)
        set(value) {
            prefs().edit().putInt(PREF_PORT, value).apply()
        }

    private fun prefs() = appContext.getSharedPreferences("prosto", 0)

    /**
     * Поднимает туннель и ждёт реального рукопожатия с сервером.
     *
     * `alternativePorts` — запасные порты того же узла. Основной порт
     * WireGuard у части операторов просто не проходит, и перебор — это
     * единственное, чем клиент может себе помочь. Пустой список означает
     * «перебирать нечего», и поведение остаётся ровно прежним.
     *
     * Отменяемо: ожидание идёт на [delay], поэтому нажатие «отключить» во время
     * подключения срабатывает сразу.
     */
    suspend fun connect(configText: String, alternativePorts: List<Int> = emptyList()): Result {
        wanted = configText
        alternatives = alternativePorts
        _status.value = Status.CONNECTING
        val result = attemptConnect(configText, alternativePorts)
        if (result == Result.CONNECTED) {
            lastFailure = null
            _status.value = Status.ON
            startSupervision()
        } else {
            lastFailure = result
            wanted = null
            _status.value = Status.OFF
        }
        return result
    }

    /**
     * Один заход подключения: перебор портов, на каждом — несколько попыток.
     *
     * Порядок портов задаёт [Endpoints.order]: сперва тот, что работал в
     * прошлый раз. Человеку, у которого проходит только запасной порт, незачем
     * терять полминуты на основном при каждом включении.
     */
    private suspend fun attemptConnect(configText: String, alternativePorts: List<Int>): Result =
        mutex.withLock {
            val basePort = Endpoints.portOf(configText)
            val ports = Endpoints.order(basePort, rememberedPort, alternativePorts)
            var outcome = Result.NO_HANDSHAKE

            // Портов может не быть вовсе (эндпоинт без порта в конфиге) —
            // тогда работаем с конфигом как есть, одним заходом.
            val plan: List<Int?> = if (ports.isEmpty()) listOf(null) else ports

            for (port in plan) {
                val text = if (port == null) configText else Endpoints.withPort(configText, port)
                val result = tryEndpoint(text, port)
                if (result == Result.CONNECTED) {
                    if (port != null) rememberedPort = port
                    return@withLock Result.CONNECTED
                }
                // Конфиг не разобрался или VpnService отказал — другой порт
                // этого не исправит, дальше перебирать бессмысленно.
                if (result == Result.FAILED) return@withLock Result.FAILED
                outcome = result
            }
            outcome
        }

    /** Попытки на одном эндпоинте. Возвращает исход по этому порту. */
    private suspend fun tryEndpoint(configText: String, port: Int?): Result {
        val config = runCatching { parseConfig(configText) }
            // runCatching ловит и ошибки загрузки классов: без записи в лог такой
            // отказ выглядел бы как «просто не подключается» и не поддавался разбору
            .onFailure { Log.e(TAG, "не удалось разобрать конфиг", it) }
            .getOrNull() ?: return Result.FAILED

        var outcome = Result.NO_HANDSHAKE
        for (attempt in 1..ATTEMPTS) {
            if (!bringUp(config)) return Result.FAILED

            /*
            Стабилизация перед отсчётом. На Huawei/Honor сразу после поднятия
            VpnService маршруты ещё доустанавливаются, и первый init-пакет
            движка уходит в никуда. Короткая пауза даёт оболочке доустановить
            маршрут — тот самый «прогрев сети», из-за которого подключалось
            через раз.
            */
            delay(STARTUP_SETTLE_MS)

            /*
            Первое окно длинное намеренно. Движок сам ретрансмитит handshake
            init примерно раз в пять секунд, поэтому за долгое окно он делает
            много попыток внутри ОДНОГО интерфейса — не теряя маршруты и
            junk-состояние обфускации на пересоздании. Пересоздание интерфейса
            (следующая попытка) — крайняя мера, а не первый ход: на Huawei
            каждое пересоздание VpnService само роняет пакеты, пока заново
            расставляет маршруты.
            */
            val window = if (attempt == 1) FIRST_WINDOW_MS else RETRY_WINDOW_MS
            when (awaitHandshake(window)) {
                Handshake.OK -> {
                    Log.i(TAG, "рукопожатие получено, порт ${port ?: "из конфига"}, попытка $attempt")
                    return Result.CONNECTED
                }
                Handshake.INTERFACE_DOWN -> {
                    Log.w(TAG, "интерфейс снят во время ожидания рукопожатия")
                    tearDown()
                    return Result.FAILED
                }
                Handshake.TIMEOUT -> {
                    outcome = Result.NO_HANDSHAKE
                    Log.w(TAG, "нет рукопожатия за $window мс (порт ${port ?: "-"}, попытка $attempt из $ATTEMPTS)")
                    /*
                    Пересоздаём интерфейс: новая эфемерная пара и новый
                    исходящий порт с нуля проходят фильтры сети, если прежний
                    порт попал под блокировку DPI. Между попытками — пауза,
                    чтобы оболочка успела снять старый интерфейс до нового.
                    */
                    if (attempt < ATTEMPTS) {
                        tearDown()
                        delay(RETRY_GAP_MS)
                    }
                }
            }
        }

        // Не оставляем мёртвый туннель поднятым, иначе весь трафик уходит в него
        // и снаружи это выглядит как «интернета нет»
        tearDown()
        return outcome
    }

    /**
     * Поднимает интерфейс — со сроком и с правом на прерывание.
     *
     * Внутри setState(UP) есть места, где можно застрять надолго: ожидание
     * старта VpnService (оболочки Huawei/Honor умеют его придержать) и
     * разрешение имени эндпоинта через системный резолвер. Без срока это
     * выглядело как бесконечное «подключение», причём замок туннеля
     * оставался занятым — и следующее нажатие кнопки тоже висло уже на
     * замке. runInterruptible переводит отмену корутины в прерывание
     * потока, которое блокирующие ожидания внутри библиотеки понимают.
     */
    private suspend fun bringUp(config: Config): Boolean =
        withTimeoutOrNull(BRING_UP_TIMEOUT_MS) {
            runInterruptible(Dispatchers.IO) {
                runCatching { backend.setState(tunnel, Tunnel.State.UP, config) }
                    .onFailure { Log.e(TAG, "setState(UP) не удался", it) }
                    .getOrNull() == Tunnel.State.UP
            }
        } ?: run {
            Log.e(TAG, "setState(UP) не уложился в $BRING_UP_TIMEOUT_MS мс — снимаем")
            tearDown()
            false
        }

    /** Снятие не должно срываться отменой: иначе туннель останется висеть. */
    private suspend fun tearDown() = withContext(NonCancellable + Dispatchers.IO) {
        runCatching { backend.setState(tunnel, Tunnel.State.DOWN, null) }
        Unit
    }

    private suspend fun awaitHandshake(windowMs: Long): Handshake {
        val deadline = System.currentTimeMillis() + windowMs
        while (System.currentTimeMillis() < deadline) {
            if (lastHandshakeMillis() > 0L) return Handshake.OK
            // Туннель мог отвалиться сам (отзыв разрешения, смена сети)
            if (!isUp) return Handshake.INTERFACE_DOWN
            delay(POLL_MS)
        }
        return Handshake.TIMEOUT
    }

    /**
     * Время последнего рукопожатия, epoch-миллисекунды; 0 — не было.
     *
     * Движок отдаёт `last_handshake_time_sec` — СЕКУНДЫ, а не миллисекунды.
     * Без пересчёта разница с [System.currentTimeMillis] выходила порядка 1.7e12
     * при пороге 180000, поэтому [isHealthy] не возвращала true никогда: живость
     * держалась только на приросте трафика, и десяти секунд тишины хватало,
     * чтобы приложение само оборвало исправный туннель.
     *
     * Отрицательные значения — служебные коды движка (нет туннеля, не удалось
     * разобрать конфиг), их приводим к «рукопожатия не было».
     */
    private fun lastHandshakeMillis(): Long {
        val seconds = runCatching { backend.getLastHandshake(tunnel) }.getOrDefault(-1L)
        return if (seconds > 0L) seconds * 1000L else 0L
    }

    /** Рукопожатие ещё живо? WireGuard обновляет его чаще двух минут. */
    fun isHealthy(staleMillis: Long = 180_000): Boolean {
        val last = lastHandshakeMillis()
        return last > 0 && System.currentTimeMillis() - last < staleMillis
    }

    /**
     * Принято байт с начала сессии; -1 — статистика недоступна.
     *
     * Нужна вместе с рукопожатием: пока идёт трафик, туннель заведомо жив,
     * даже если очередное рукопожатие ещё не подошло по времени.
     */
    fun receivedBytes(): Long =
        runCatching { backend.getStatistics(tunnel).totalRx() }.getOrDefault(-1L)

    /**
     * Снимает туннель по воле человека и прекращает надзор.
     *
     * Пока интерфейс VpnService жив, весь трафик идёт через него, поэтому
     * показывать «отключено» до этого момента — врать о том, куда уходят
     * пакеты. Ответ нужен интерфейсу, чтобы дождаться.
     */
    suspend fun disconnect(): Boolean {
        // Снимаем намерение ДО замка: надзор, ждущий своей очереди, должен
        // увидеть «держать нечего» и не поднять туннель обратно.
        wanted = null
        superviseJob?.cancel()
        superviseJob = null
        val down = mutex.withLock {
            tearDown()
            !isUp
        }
        _status.value = Status.OFF
        return down
    }

    val isUp: Boolean
        get() = runCatching { backend.getState(tunnel) == Tunnel.State.UP }.getOrDefault(false)

    // --- надзор -------------------------------------------------------------

    /** Свой scope, а не viewModelScope: живёт с процессом, а не с экраном. */
    private val watchScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private var superviseJob: Job? = null

    /** Момент последней смены сети; 0 — сеть не менялась с подключения. */
    @Volatile
    private var networkChangedAt: Long = 0L

    private var unwatchNetwork: (() -> Unit)? = null

    /**
     * Надзор за поднятым туннелем — то, чего не было вовсе.
     *
     * Раньше здоровье туннеля проверял таймер внутри [AppState], то есть внутри
     * ViewModel экрана. Он умирал вместе с Activity — а VPN человек держит
     * включённым именно тогда, когда приложение закрыто. Получалось, что за
     * туннелем никто не следил ровно всё то время, когда им пользуются. Хуже
     * того: обнаружив смерть туннеля, тот таймер просто показывал ошибку и
     * оставлял человека отключённым — до следующего РУЧНОГО нажатия кнопки.
     * Отсюда и «подключается раз в день»: любая заминка в сети обрывала VPN
     * навсегда.
     *
     * Здесь надзор живёт в синглтоне процесса и делает три вещи:
     * следит за живостью, сам поднимает туннель обратно и сверяется с панелью.
     */
    private fun startSupervision() {
        superviseJob?.cancel()
        watchNetwork()
        superviseJob = watchScope.launch {
            var misses = 0
            var lastRx = -1L
            var sincePanelCheck = 0L
            var backoff = 0

            while (true) {
                delay(CHECK_INTERVAL_MS)
                val config = wanted ?: return@launch

                sincePanelCheck += CHECK_INTERVAL_MS
                if (sincePanelCheck >= PANEL_CHECK_MS) {
                    sincePanelCheck = 0
                    if (accessRevoked()) {
                        Log.i(TAG, "доступ закрыт панелью — снимаем туннель")
                        disconnect()
                        runCatching {
                            appContext.stopService(
                                Intent(appContext, VpnForegroundService::class.java),
                            )
                        }
                        return@launch
                    }
                }

                val alive = aliveNow(lastRx).also { lastRx = receivedBytes() }
                if (alive) {
                    misses = 0
                    backoff = 0
                    if (_status.value != Status.ON) _status.value = Status.ON
                    continue
                }

                /*
                Смена сети — не «может быть, промах», а точно известный повод
                пересобрать туннель. Сокет движка остался на исчезнувшем
                маршруте: интерфейс поднят, рукопожатие ещё «свежее» по
                времени, а наружу не уходит ничего. Ждать здесь двух промахов
                по десять секунд — это десять секунд молчащего интернета на
                каждом переходе Wi-Fi в LTE.
                */
                val afterNetChange = networkChangedAt > 0 &&
                    System.currentTimeMillis() - networkChangedAt < NET_GRACE_MS
                misses = if (afterNetChange) MISSES_BEFORE_RECONNECT else misses + 1
                if (misses < MISSES_BEFORE_RECONNECT) continue

                misses = 0
                networkChangedAt = 0
                _status.value = Status.RECONNECTING

                // Сети нет вовсе — поднимать нечего. Ждём её возвращения, а не
                // жжём батарею попытками в пустоту.
                if (!NetworkInfo.isOnline(appContext)) {
                    Log.i(TAG, "сети нет — ждём")
                    continue
                }

                if (backoff > 0) delay(backoffMs(backoff))
                Log.i(TAG, "туннель мёртв — поднимаем заново (заход ${backoff + 1})")
                val result = attemptConnect(config, alternatives)
                if (result == Result.CONNECTED) {
                    backoff = 0
                    lastRx = -1L
                    _status.value = Status.ON
                } else {
                    backoff++
                    lastFailure = result
                    /*
                    FAILED — это отказ VpnService или негодный конфиг: разрешение
                    отозвали, профиль стёрли. Такое повторами не лечится, и
                    держать человека в вечном «переподключении» нечестно.
                    */
                    if (result == Result.FAILED && backoff >= FAILED_GIVE_UP) {
                        Log.w(TAG, "поднять туннель не удаётся — прекращаем")
                        wanted = null
                        _status.value = Status.OFF
                        return@launch
                    }
                }
            }
        }
    }

    /** Жив ли туннель прямо сейчас: рукопожатие свежее или идёт трафик. */
    private fun aliveNow(previousRx: Long): Boolean {
        if (!isUp) return false
        val rx = receivedBytes()
        val moving = rx >= 0 && previousRx >= 0 && rx > previousRx
        return isHealthy() || moving
    }

    private fun backoffMs(step: Int): Long =
        BACKOFF_MS.getOrElse(step - 1) { BACKOFF_MS.last() }

    /**
     * Панель прямо сказала, что доступа нет?
     *
     * Рвём туннель ровно в двух случаях: токен отозван (401/403) или пустой
     * список стран — кончился срок, трафик или устройство отвязали. Всё
     * остальное — сетевые ошибки и пятисотки — терпим молча: недоступная
     * панель не повод рвать работающий VPN. Тем более что при поднятом
     * туннеле запрос к панели идёт через сам туннель.
     */
    private fun accessRevoked(): Boolean {
        val token = prefs().getString("panelToken", "").orEmpty()
        if (token.isEmpty()) return false
        return try {
            val (servers, _) = PanelApi.servers(token)
            servers.isEmpty()
        } catch (error: PanelApi.PanelException) {
            error.status == 401 || error.status == 403
        } catch (_: Exception) {
            false
        }
    }

    /**
     * Подписка на смену сети.
     *
     * Ставится один раз на процесс и снимается только вместе с ним: подписка
     * дешёвая, а её пересоздание на каждое подключение — лишний повод потерять
     * событие ровно в тот момент, когда оно важно.
     */
    private fun watchNetwork() {
        if (unwatchNetwork != null) return
        unwatchNetwork = NetworkInfo.watch(appContext) {
            if (wanted != null) networkChangedAt = System.currentTimeMillis()
        }
    }

    companion object {
        private const val TAG = "ProstoTunnel"
        private const val PREF_PORT = "tunnel.workingPort"

        /** Как часто надзор смотрит на туннель. */
        private const val CHECK_INTERVAL_MS = 5_000L

        /** Как часто сверяемся с панелью. */
        private const val PANEL_CHECK_MS = 60_000L

        /** Сколько промахов подряд считаем смертью туннеля. */
        private const val MISSES_BEFORE_RECONNECT = 2

        /**
         * Сколько ждём восстановления после смены сети, прежде чем пересобрать.
         *
         * Движок умеет пережить смену сети сам, и если переживёт — трафик
         * возобновится за секунды. Но когда не переживает, ждать штатного
         * перезапуска рукопожатия бессмысленно: WireGuard возьмётся за него
         * только через десятки секунд, и всё это время интернета нет.
         */
        private const val NET_GRACE_MS = 8_000L

        /** Паузы между заходами: сразу, потом всё реже, потолок — минута. */
        private val BACKOFF_MS = listOf(0L, 3_000L, 8_000L, 15_000L, 30_000L, 60_000L)

        /** Столько отказов VpnService подряд — и мы перестаём мучить человека. */
        private const val FAILED_GIVE_UP = 3

        private const val ATTEMPTS = 4
        private const val STARTUP_SETTLE_MS = 1_000L
        private const val FIRST_WINDOW_MS = 30_000L
        private const val RETRY_WINDOW_MS = 20_000L
        private const val RETRY_GAP_MS = 1_000L
        // Поллим часто: успех ловим почти сразу, а не через полсекунды.
        private const val POLL_MS = 300L

        /*
        Потолок на само поднятие интерфейса. Обычно оно занимает доли секунды;
        двадцать — это уже «служба не стартует» или «резолвер молчит», и ждать
        дальше бессмысленно: лучше честная ошибка, чем вечный спиннер.
        */
        private const val BRING_UP_TIMEOUT_MS = 20_000L

        @Volatile
        private var instance: TunnelManager? = null

        /**
         * Туннель на процесс один, и владельцев у него трое: экран ([AppState]),
         * уведомление ([VpnForegroundService]) и собственный надзор. Второй
         * экземпляр [GoBackend] завёл бы вторую копию состояния, и кнопка
         * «отключить» в шторке снимала бы не тот туннель, который показан на экране.
         */
        fun getInstance(context: Context): TunnelManager =
            instance ?: synchronized(this) {
                instance ?: TunnelManager(context.applicationContext).also { instance = it }
            }
    }
}
