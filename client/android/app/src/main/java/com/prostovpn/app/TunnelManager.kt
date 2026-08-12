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
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
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

    private val backend: Backend = GoBackend(context.applicationContext)

    /*
    Подключение и отключение сериализуем здесь, а не у вызывающего: владельцев
    туннеля двое — экран ([AppState]) и Always-on VPN ([App]), который стартует
    вообще без Activity. Без общего замка они могли войти в setState одновременно.
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

    /**
     * Поднимает туннель и ждёт реального рукопожатия с сервером.
     *
     * Отменяемо: ожидание идёт на [delay], поэтому нажатие «отключить» во время
     * подключения срабатывает сразу. Раньше цикл крутился на Thread.sleep внутри
     * односоточного диспетчера, и кнопка не отвечала до конца всего таймаута.
     */
    suspend fun connect(configText: String): Result = mutex.withLock {
        val config = runCatching { parseConfig(configText) }
            // runCatching ловит и ошибки загрузки классов: без записи в лог такой
            // отказ выглядел бы как «просто не подключается» и не поддавался разбору
            .onFailure { Log.e(TAG, "не удалось разобрать конфиг", it) }
            .getOrNull() ?: return@withLock Result.FAILED

        var outcome = Result.NO_HANDSHAKE
        for (attempt in 1..ATTEMPTS) {
            if (!bringUp(config)) {
                outcome = Result.FAILED
                break
            }
            val window = if (attempt == 1) FIRST_WINDOW_MS else RETRY_WINDOW_MS
            when (awaitHandshake(window)) {
                Handshake.OK -> {
                    Log.i(TAG, "рукопожатие получено с попытки $attempt")
                    startSessionWatch()
                    return@withLock Result.CONNECTED
                }
                Handshake.INTERFACE_DOWN -> {
                    Log.w(TAG, "интерфейс снят во время ожидания рукопожатия")
                    outcome = Result.FAILED
                    break
                }
                Handshake.TIMEOUT -> {
                    outcome = Result.NO_HANDSHAKE
                    Log.w(TAG, "нет рукопожатия за $window мс (попытка $attempt из $ATTEMPTS)")
                    /*
                    Пересоздаём интерфейс, а не ждём дольше одним куском: первая
                    инициация могла потеряться безвозвратно, а новая попытка идёт
                    с новой эфемерной парой ключей и с нуля проходит фильтры сети.
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
        outcome
    }

    private suspend fun bringUp(config: Config): Boolean = withContext(Dispatchers.IO) {
        runCatching { backend.setState(tunnel, Tunnel.State.UP, config) }
            .onFailure { Log.e(TAG, "setState(UP) не удался", it) }
            .getOrNull() == Tunnel.State.UP
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
     * Снимает туннель и отвечает, снят ли он на самом деле.
     *
     * Пока интерфейс VpnService жив, весь трафик идёт через него, поэтому
     * показывать «отключено» до этого момента — врать о том, куда уходят
     * пакеты. Ответ нужен интерфейсу, чтобы дождаться.
     */
    suspend fun disconnect(): Boolean = mutex.withLock {
        watchJob?.cancel()
        watchJob = null
        tearDown()
        !isUp
    }

    val isUp: Boolean
        get() = runCatching { backend.getState(tunnel) == Tunnel.State.UP }.getOrDefault(false)

    // --- страж сессии -------------------------------------------------------

    /** Свой scope, а не viewModelScope: живёт с процессом, а не с экраном. */
    private val watchScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private var watchJob: Job? = null

    /**
     * Страж сессии: пока туннель поднят, раз в минуту сверяется с панелью.
     *
     * «Отключить» в кабинете и в админке гасит сессию на сервере, но туннель —
     * это ключи WireGuard, о сессии он ничего не знает и продолжал бы работать
     * до перезапуска приложения. Экранный опрос ([AppState]) живёт вместе с
     * Activity и умирает вместе с ней, а процесс с туннелем переживает
     * закрытие окна — поэтому страж стоит здесь, в синглтоне процесса, и
     * заводится самим подключением.
     *
     * Туннель рвётся ровно в двух случаях: панель прямо сказала, что токен
     * отозван (401/403), или отдала пустой список стран — доступ закрыт:
     * кончился срок, трафик или устройство отвязали. Всё остальное — сетевые
     * ошибки и пятисотки — терпим молча: недоступная панель не повод рвать
     * работающий VPN.
     */
    private fun startSessionWatch() {
        watchJob?.cancel()
        watchJob = watchScope.launch {
            while (true) {
                delay(WATCH_INTERVAL_MS)
                if (!isUp) return@launch

                // Токен читаем каждый раз: выход из аккаунта на экране стирает
                // его, и стражу после этого проверять нечего.
                val token = appContext.getSharedPreferences("prosto", 0)
                    .getString("panelToken", "").orEmpty()
                if (token.isEmpty()) return@launch

                val revoked = try {
                    val (servers, _) = PanelApi.servers(token)
                    servers.isEmpty()
                } catch (error: PanelApi.PanelException) {
                    error.status == 401 || error.status == 403
                } catch (_: Exception) {
                    false
                }

                if (revoked) {
                    Log.i(TAG, "сессия отозвана панелью — снимаем туннель")
                    // Сервис уведомления гасим отдельно: о туннеле он не
                    // узнает сам, и «подключено» висело бы над мёртвым VPN.
                    disconnect()
                    runCatching {
                        appContext.stopService(Intent(appContext, VpnForegroundService::class.java))
                    }
                    return@launch
                }
            }
        }
    }

    companion object {
        private const val TAG = "ProstoTunnel"

        /** Как часто страж сверяется с панелью. Та же минута, что у экрана. */
        private const val WATCH_INTERVAL_MS = 60_000L

        /*
        Было 20 секунд одной попыткой. WireGuard повторяет инициацию примерно раз
        в пять секунд, то есть окно давало всего четыре попытки — на загруженном
        мобильном канале этого не хватало, и исправное подключение объявлялось
        отказом. Теперь два захода с пересозданием интерфейса между ними.
        */
        private const val ATTEMPTS = 2
        private const val FIRST_WINDOW_MS = 20_000L
        private const val RETRY_WINDOW_MS = 15_000L
        private const val RETRY_GAP_MS = 700L
        private const val POLL_MS = 500L

        @Volatile
        private var instance: TunnelManager? = null

        /**
         * Туннель на процесс один, и владельцев у него двое: экран ([AppState]) и
         * уведомление ([VpnForegroundService]). Второй экземпляр [GoBackend] завёл бы
         * вторую копию состояния, и кнопка «отключить» в шторке снимала бы не тот
         * туннель, который показан на экране.
         */
        fun getInstance(context: Context): TunnelManager =
            instance ?: synchronized(this) {
                instance ?: TunnelManager(context.applicationContext).also { instance = it }
            }
    }
}
