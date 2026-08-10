package com.prostovpn.app

import android.app.Application
import android.util.Log
import org.amnezia.awg.backend.GoBackend
import java.util.Locale
import kotlin.concurrent.thread

class App : Application() {

    override fun onCreate() {
        super.onCreate()
        /*
        Система дёргает этот колбэк, когда пользователь включил «Постоянная VPN»
        и наш VpnService стартовал без участия приложения — на загрузке телефона
        или после сбоя. Раньше колбэк не регистрировался вовсе: библиотека писала
        «Service started by Always-on VPN feature» в лог и ничего не делала.
        Тумблер в системных настройках был, туннель не поднимался, а вместе с
        «Блокировать соединения без VPN» телефон оставался без интернета до
        ручного запуска приложения.
        */
        GoBackend.setAlwaysOnCallback {
            // connect() блокирует до рукопожатия — с главного потока нельзя
            thread(name = "always-on-vpn") {
                val base = ConnectConfig.storedConfig(this) ?: return@thread
                val prepared = runCatching { ConnectConfig.build(this, base) }.getOrDefault(base)
                val result = TunnelManager.getInstance(this).connect(prepared)
                Log.i(TAG, "always-on поднял туннель: $result")
                if (result == TunnelManager.Result.CONNECTED) {
                    val lang = getSharedPreferences("prosto", 0).getString("lang", null)
                        ?: if (Locale.getDefault().language == "ru") "ru" else "en"
                    val s = strings(lang)
                    VpnForegroundService.start(this, s.connected, s.notifDisconnect)
                }
            }
        }
    }

    private companion object {
        const val TAG = "ProstoApp"
    }
}
