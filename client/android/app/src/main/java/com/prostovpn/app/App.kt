package com.prostovpn.app

import android.app.Application
import android.util.Log
import kotlinx.coroutines.runBlocking
import org.amnezia.awg.backend.GoBackend
import java.util.Locale
import kotlin.concurrent.thread

class App : Application() {
    override fun onCreate() {
        super.onCreate()

        GoBackend.setAlwaysOnCallback {
            thread(name = "always-on-vpn") {
                runCatching {
                val base = ConnectConfig.storedConfig(this) ?: return@runCatching
                val prepared = runCatching { ConnectConfig.build(this, base) }.getOrDefault(base)
                val ports = ConnectConfig.storedAltPorts(this)
                val result = runBlocking {
                    TunnelManager.getInstance(this@App).connect(prepared, ports)
                }
                Log.i(TAG, "always-on поднял туннель: $result")
                if (result == TunnelManager.Result.CONNECTED) {
                    val lang = getSharedPreferences("prosto", 0).getString("lang", null)
                        ?: if (Locale.getDefault().language == "ru") "ru" else "en"
                    val s = strings(lang)
                    VpnForegroundService.start(this, s.connected, s.notifDisconnect)
                }
                }.onFailure { Log.e(TAG, "always-on не поднялся", it) }
            }
        }
    }

    private companion object {
        const val TAG = "ProstoApp"
    }
}
