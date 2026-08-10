package com.prostovpn.app

import android.content.Context
import android.util.Log
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

    private val tunnel = object : Tunnel {
        override fun getName(): String = "prosto"
        override fun onStateChange(newState: Tunnel.State) {
            onStateChange?.invoke(newState == Tunnel.State.UP)
        }
    }

    var onStateChange: ((Boolean) -> Unit)? = null

    fun parseConfig(configText: String): Config =
        Config.parse(BufferedReader(StringReader(configText)))

    /**
     * Поднимает туннель и ждёт реального рукопожатия с сервером.
     *
     * Блокирующий вызов — запускать вне главного потока. Возвращается, когда
     * сервер ответил, либо когда стало ясно, что не ответит.
     */
    fun connect(configText: String): Result {
        val config = runCatching { parseConfig(configText) }.getOrNull() ?: return Result.FAILED

        val up = runCatching { backend.setState(tunnel, Tunnel.State.UP, config) }
            .getOrElse {
                Log.e(TAG, "setState(UP) не удался", it)
                return Result.FAILED
            }
        if (up != Tunnel.State.UP) return Result.FAILED

        /*
        Интерфейс поднят — но это ещё не связь. Ждём, пока движок сообщит о
        рукопожатии: пустой last_handshake значит, что сервер пока молчит.
        20 секунд с запасом на четыре повторные инициации AmneziaWG.
        */
        val deadline = System.currentTimeMillis() + HANDSHAKE_TIMEOUT_MS
        while (System.currentTimeMillis() < deadline) {
            if (lastHandshakeMillis() > 0L) return Result.CONNECTED
            // Туннель мог отвалиться сам (отзыв разрешения, смена сети)
            if (runCatching { backend.getState(tunnel) }.getOrNull() != Tunnel.State.UP) {
                return Result.FAILED
            }
            Thread.sleep(POLL_MS)
        }

        // Рукопожатия не случилось — не оставляем мёртвый туннель поднятым,
        // иначе весь трафик уходит в него и «интернета нет».
        runCatching { backend.setState(tunnel, Tunnel.State.DOWN, null) }
        return Result.NO_HANDSHAKE
    }

    /** Время последнего рукопожатия, epoch-миллисекунды; 0 — не было. */
    private fun lastHandshakeMillis(): Long =
        runCatching { backend.getLastHandshake(tunnel) }.getOrDefault(0L).coerceAtLeast(0L)

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
    fun disconnect(): Boolean = runCatching {
        backend.setState(tunnel, Tunnel.State.DOWN, null)
        backend.getState(tunnel) != Tunnel.State.UP
    }.getOrElse { false }

    val isUp: Boolean
        get() = runCatching { backend.getState(tunnel) == Tunnel.State.UP }.getOrDefault(false)

    private companion object {
        const val TAG = "ProstoTunnel"
        const val HANDSHAKE_TIMEOUT_MS = 20_000L
        const val POLL_MS = 500L
    }
}
