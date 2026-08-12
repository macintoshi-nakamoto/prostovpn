package com.prostovpn.app

import android.content.Context
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.delay
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
     * Снимает туннель и отвечает, снят ли он на самом деле.
     *
     * Пока интерфейс VpnService жив, весь трафик идёт через него, поэтому
     * показывать «отключено» до этого момента — врать о том, куда уходят
     * пакеты. Ответ нужен интерфейсу, чтобы дождаться.
     */
    suspend fun disconnect(): Boolean = mutex.withLock {
        tearDown()
        !isUp
    }

    val isUp: Boolean
        get() = runCatching { backend.getState(tunnel) == Tunnel.State.UP }.getOrDefault(false)

    companion object {
        private const val TAG = "ProstoTunnel"

        /*
        Было 20 секунд одной попыткой. WireGuard повторяет инициацию примерно раз
        в пять секунд, то есть окно давало всего четыре попытки — на загруженном
        мобильном канале этого не хватало, и исправное подключение объявлялось
        отказом.

        Теперь три захода с пересозданием интерфейса между ними: каждый заход —
        новый интерфейс, новая эфемерная пара и новое разрешение эндпоинта.
        Третий добавлен по жалобам с телефонов Huawei: там первые секунды после
        поднятия интерфейса сеть нередко «прогревается» (оболочка заново
        решает, каким каналом пускать трафик), и двух заходов не хватало.
        */
        private const val ATTEMPTS = 3
        private const val FIRST_WINDOW_MS = 20_000L
        private const val RETRY_WINDOW_MS = 15_000L
        private const val RETRY_GAP_MS = 700L
        private const val POLL_MS = 500L

        /*
        Потолок на само поднятие интерфейса. Обычно оно занимает доли секунды;
        двадцать — это уже «служба не стартует» или «резолвер молчит», и ждать
        дальше бессмысленно: лучше честная ошибка, чем вечный спиннер.
        */
        private const val BRING_UP_TIMEOUT_MS = 20_000L

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
