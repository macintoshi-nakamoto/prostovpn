package com.prostovpn.app

import android.content.Context
import android.content.Intent
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
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

    enum class Result {
        CONNECTED,

        NO_HANDSHAKE,

        FAILED,

        /** Подключение отменили (кнопкой в уведомлении) — это не ошибка. */
        CANCELLED,
    }

    enum class Status { OFF, CONNECTING, ON, RECONNECTING }

    /**
     * Какую часть списка портов перебирать. FIRST — только первый кандидат,
     * и коротким окном: за ним ждёт второй протокол, и полминуты тишины на
     * UDP — это полминуты, которые человек на сотовой сети просидел бы зря.
     * REST — всё, что после первого. ALL — как есть, когда запасного
     * протокола у узла нет.
     */
    enum class Stage { ALL, FIRST, REST }

    private val _status = MutableStateFlow(Status.OFF)
    val status: StateFlow<Status> = _status.asStateFlow()

    @Volatile
    var lastFailure: Result? = null
        private set

    private val backend: Backend = GoBackend(context.applicationContext)

    private val mutex = Mutex()

    @OptIn(ExperimentalCoroutinesApi::class)
    private val tunnelDispatcher = Dispatchers.IO.limitedParallelism(1)

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

    @Volatile
    private var wanted: String? = null

    @Volatile
    private var alternatives: List<Int> = emptyList()

    private var rememberedPort: Int
        get() = prefs().getInt(PREF_PORT, 0)
        set(value) {
            prefs().edit().putInt(PREF_PORT, value).apply()
        }

    private fun prefs() = appContext.getSharedPreferences("prosto", 0)

    suspend fun connect(
        configText: String,
        alternativePorts: List<Int> = emptyList(),
        stage: Stage = Stage.ALL,
    ): Result {
        wanted = configText
        alternatives = alternativePorts
        _status.value = Status.CONNECTING
        val result = attemptConnect(configText, alternativePorts, stage)

        if (wanted == null) return Result.CANCELLED

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

    private suspend fun attemptConnect(
        configText: String,
        alternativePorts: List<Int>,
        stage: Stage = Stage.ALL,
    ): Result = withContext(tunnelDispatcher) {
        mutex.withLock {
            val basePort = Endpoints.portOf(configText)
            val ports = Endpoints.order(basePort, rememberedPort, alternativePorts)
            var outcome = Result.NO_HANDSHAKE

            val full: List<Int?> = if (ports.isEmpty()) listOf(null) else ports
            val plan: List<Int?> = when (stage) {
                Stage.ALL -> full
                Stage.FIRST -> full.take(1)
                Stage.REST -> full.drop(1)
            }
            if (plan.isEmpty()) return@withLock Result.NO_HANDSHAKE
            val quick = stage == Stage.FIRST && full.size > 1

            try {
                for ((index, port) in plan.withIndex()) {
                    if (wanted == null) break
                    val text =
                        if (port == null) configText else Endpoints.withPort(configText, port)
                    val result = tryEndpoint(
                        text,
                        port,
                        first = index == 0 && stage != Stage.REST,
                        ofPorts = full.size,
                        quick = quick,
                    )
                    if (result == Result.CONNECTED) {
                        if (port != null) rememberedPort = port
                        return@withLock Result.CONNECTED
                    }

                    if (result == Result.FAILED) return@withLock Result.FAILED
                    outcome = result
                }
                outcome
            } finally {
                if (!isUp || wanted == null) {
                    withContext(NonCancellable) { tearDown() }
                } else if (!isHealthy(staleMillis = HANDSHAKE_FRESH_MS)) {
                    withContext(NonCancellable) { tearDown() }
                }
            }
        }
    }

    private suspend fun tryEndpoint(
        configText: String,
        port: Int?,
        first: Boolean = true,
        ofPorts: Int = 1,
        quick: Boolean = false,
    ): Result {
        val config = runCatching { parseConfig(configText) }

            .onFailure { Log.e(TAG, "не удалось разобрать конфиг", it) }
            .getOrNull() ?: return Result.FAILED

        val attempts = when {
            quick -> 1
            ofPorts <= 1 -> ATTEMPTS
            first -> ATTEMPTS_FIRST_PORT
            else -> ATTEMPTS_OTHER_PORT
        }

        var outcome = Result.NO_HANDSHAKE
        for (attempt in 1..attempts) {
            if (wanted == null) return Result.NO_HANDSHAKE
            if (!bringUp(config)) return Result.FAILED

            delay(STARTUP_SETTLE_MS)

            val window = when {
                quick -> PROBE_WINDOW_MS
                ofPorts > 1 && !first -> OTHER_PORT_WINDOW_MS
                attempt == 1 -> FIRST_WINDOW_MS
                else -> RETRY_WINDOW_MS
            }
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
                    Log.w(TAG, "нет рукопожатия за $window мс (порт ${port ?: "-"}, попытка $attempt из $attempts)")

                    if (attempt < attempts) {
                        tearDown()
                        delay(RETRY_GAP_MS)
                    }
                }
            }
        }

        withContext(NonCancellable) { tearDown() }
        return outcome
    }

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

    private suspend fun tearDown() = withContext(NonCancellable + Dispatchers.IO) {
        runCatching { backend.setState(tunnel, Tunnel.State.DOWN, null) }
        Unit
    }

    private suspend fun awaitHandshake(windowMs: Long): Handshake {
        val deadline = System.currentTimeMillis() + windowMs
        while (System.currentTimeMillis() < deadline) {
            if (lastHandshakeMillis() > 0L) return Handshake.OK

            if (!isUp) return Handshake.INTERFACE_DOWN

            if (wanted == null) return Handshake.INTERFACE_DOWN
            delay(POLL_MS)
        }
        return Handshake.TIMEOUT
    }

    private fun lastHandshakeMillis(): Long {
        val seconds = runCatching { backend.getLastHandshake(tunnel) }.getOrDefault(-1L)
        return if (seconds > 0L) seconds * 1000L else 0L
    }

    fun isHealthy(staleMillis: Long = 180_000): Boolean {
        val last = lastHandshakeMillis()
        return last > 0 && System.currentTimeMillis() - last < staleMillis
    }

    fun receivedBytes(): Long =
        runCatching { backend.getStatistics(tunnel).totalRx() }.getOrDefault(-1L)

    fun sentBytes(): Long =
        runCatching { backend.getStatistics(tunnel).totalTx() }.getOrDefault(-1L)

    suspend fun disconnect(): Boolean {
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

    fun adopt(configText: String, alternativePorts: List<Int> = emptyList()): Boolean {
        if (!isUp) return false
        wanted = configText
        alternatives = alternativePorts
        _status.value = Status.ON
        startSupervision()
        return true
    }

    fun requestDisconnect(onDone: () -> Unit) {
        wanted = null
        watchScope.launch {
            withTimeoutOrNull(DISCONNECT_TIMEOUT_MS) { disconnect() }
            onDone()
        }
    }

    val isUp: Boolean
        get() = runCatching { backend.getState(tunnel) == Tunnel.State.UP }.getOrDefault(false)

    private val watchScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private var superviseJob: Job? = null

    @Volatile
    private var networkChangedAt: Long = 0L

    private var unwatchNetwork: (() -> Unit)? = null

    private fun startSupervision() {
        superviseJob?.cancel()
        watchNetwork()
        superviseJob = watchScope.launch {
            var misses = 0
            var lastRx = -1L
            var lastTx = -1L
            var oneWay = 0
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

                val rx = receivedBytes()
                val tx = sentBytes()

                // Односторонняя связь: мы шлём, в ответ тишина. Так выглядит
                // задушенный порт — туннель формально жив и рукопожатие было,
                // а страницы не открываются. Проверка на «мёртв» этого не
                // видит: там ждут полного молчания, здесь же трафик идёт,
                // просто впустую.
                val sending = lastTx >= 0 && tx - lastTx > ONE_WAY_TX_BYTES
                val silent = lastRx >= 0 && rx - lastRx < ONE_WAY_RX_BYTES
                oneWay = if (sending && silent) oneWay + 1 else 0

                val alive = oneWay < ONE_WAY_CHECKS && aliveNow(previousRx = lastRx, rx = rx)
                lastRx = rx
                lastTx = tx
                if (alive) {
                    misses = 0
                    backoff = 0
                    if (_status.value != Status.ON) _status.value = Status.ON
                    continue
                }
                if (oneWay >= ONE_WAY_CHECKS) {
                    Log.i(TAG, "связь односторонняя — уходим с этого порта")
                    oneWay = 0
                    // Порт, на котором это случилось, удачным больше не
                    // считаем: пусть перебор ищет заново, а не возвращается
                    // к нему первым же заходом.
                    rememberedPort = 0
                }

                val afterNetChange = networkChangedAt > 0 &&
                    System.currentTimeMillis() - networkChangedAt < NET_GRACE_MS
                misses = if (afterNetChange) MISSES_BEFORE_RECONNECT else misses + 1
                if (misses < MISSES_BEFORE_RECONNECT) continue

                misses = 0
                networkChangedAt = 0
                _status.value = Status.RECONNECTING

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

                    if (result == Result.FAILED && backoff >= FAILED_GIVE_UP) {
                        Log.w(TAG, "поднять туннель не удаётся — прекращаем")
                        wanted = null
                        _status.value = Status.OFF
                        // Иначе уведомление «Подключено» висит при снятом туннеле.
                        runCatching {
                            appContext.stopService(
                                Intent(appContext, VpnForegroundService::class.java),
                            )
                        }
                        return@launch
                    }
                }
            }
        }
    }

    private fun aliveNow(previousRx: Long, rx: Long): Boolean {
        if (!isUp) return false
        val moving = rx >= 0 && previousRx >= 0 && rx > previousRx
        return isHealthy() || moving
    }

    private fun backoffMs(step: Int): Long =
        BACKOFF_MS.getOrElse(step - 1) { BACKOFF_MS.last() }

    private fun accessRevoked(): Boolean {
        val token = prefs().getString("panelToken", "").orEmpty()
        if (token.isEmpty()) return false
        return try {
            val (servers, _) = PanelApi.servers(token)
            servers.isEmpty()
        } catch (error: PanelApi.PanelException) {
            // Только решение самой панели: 401 или 403 с её X-Error-Code.
            // Голая 403 — WAF/анти-DDoS по пути, туннель из-за неё не рвём.
            error.status == 401 || (error.status == 403 && error.code.isNotEmpty())
        } catch (_: Exception) {
            false
        }
    }

    private fun watchNetwork() {
        if (unwatchNetwork != null) return
        unwatchNetwork = NetworkInfo.watch(appContext) {
            if (wanted != null) networkChangedAt = System.currentTimeMillis()
        }
    }

    companion object {
        private const val TAG = "ProstoTunnel"
        private const val PREF_PORT = "tunnel.workingPort"

        private const val CHECK_INTERVAL_MS = 5_000L

        private const val PANEL_CHECK_MS = 60_000L

        private const val MISSES_BEFORE_RECONNECT = 2

        // Пороги «односторонней связи»: мы шлём, в ответ тишина. Проверка идёт
        // раз в пять секунд, поэтому три подряд — пятнадцать секунд молчания
        // при живой отправке. Меньше брать нельзя: короткая заминка бывает и
        // на здоровой сети. 64 КБ отправленного отсекают keepalive и одиночные
        // запросы; 4 КБ принятого — порог шума, чтобы редкие служебные ответы
        // не сходили за полноценный обмен.
        private const val ONE_WAY_TX_BYTES = 64 * 1024L

        private const val ONE_WAY_RX_BYTES = 4 * 1024L

        private const val ONE_WAY_CHECKS = 3

        private const val NET_GRACE_MS = 8_000L

        private val BACKOFF_MS = listOf(0L, 3_000L, 8_000L, 15_000L, 30_000L, 60_000L)

        private const val FAILED_GIVE_UP = 3

        private const val ATTEMPTS = 4

        private const val ATTEMPTS_FIRST_PORT = 2
        private const val ATTEMPTS_OTHER_PORT = 1
        private const val OTHER_PORT_WINDOW_MS = 12_000L

        // Окно первого порта, когда следом ждёт второй протокол: рукопожатие
        // на живом UDP приходит за секунды, а 15 секунд тишины — уже не
        // заминка, а признак, что UDP здесь не ходит.
        private const val PROBE_WINDOW_MS = 15_000L

        private const val HANDSHAKE_FRESH_MS = 60_000L

        private const val DISCONNECT_TIMEOUT_MS = 25_000L

        private const val STARTUP_SETTLE_MS = 1_000L
        private const val FIRST_WINDOW_MS = 30_000L
        private const val RETRY_WINDOW_MS = 20_000L
        private const val RETRY_GAP_MS = 1_000L

        private const val POLL_MS = 300L

        private const val BRING_UP_TIMEOUT_MS = 20_000L

        @Volatile
        private var instance: TunnelManager? = null

        fun getInstance(context: Context): TunnelManager =
            instance ?: synchronized(this) {
                instance ?: TunnelManager(context.applicationContext).also { instance = it }
            }
    }
}
