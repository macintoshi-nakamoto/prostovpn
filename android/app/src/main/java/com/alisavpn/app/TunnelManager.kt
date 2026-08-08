package com.alisavpn.app

import android.content.Context
import org.amnezia.awg.backend.Backend
import org.amnezia.awg.backend.GoBackend
import org.amnezia.awg.backend.Tunnel
import org.amnezia.awg.config.Config
import java.io.BufferedReader
import java.io.StringReader

class TunnelManager(context: Context) {

    private val backend: Backend = GoBackend(context.applicationContext)

    private val tunnel = object : Tunnel {
        override fun getName(): String = "alisa"
        override fun onStateChange(newState: Tunnel.State) {
            onStateChange?.invoke(newState == Tunnel.State.UP)
        }
    }

    var onStateChange: ((Boolean) -> Unit)? = null

    fun parseConfig(configText: String): Config =
        Config.parse(BufferedReader(StringReader(configText)))

    fun connect(configText: String): Boolean = runCatching {
        val config = parseConfig(configText)
        backend.setState(tunnel, Tunnel.State.UP, config)
        backend.getState(tunnel) == Tunnel.State.UP
    }.getOrElse { false }

    fun disconnect() {
        runCatching { backend.setState(tunnel, Tunnel.State.DOWN, null) }
    }

    val isUp: Boolean
        get() = runCatching { backend.getState(tunnel) == Tunnel.State.UP }.getOrDefault(false)
}
