package com.prostovpn.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat

class VpnForegroundService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            status = stoppingLabel
            runCatching {
                ServiceCompat.startForeground(this, NOTIFICATION_ID, buildNotification(), fgsType())
            }
            TunnelManager.getInstance(applicationContext).requestDisconnect {
                stopForegroundCompat()
                stopSelf(startId)
            }
            return START_NOT_STICKY
        }

        intent?.getStringExtra(EXTRA_STATUS)?.let { status = it }
        intent?.getStringExtra(EXTRA_STOP_LABEL)?.let { stopLabel = it }

        runCatching {
            ServiceCompat.startForeground(this, NOTIFICATION_ID, buildNotification(), fgsType())
        }
        return START_NOT_STICKY
    }

    private fun fgsType(): Int =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
        } else {
            0
        }

    override fun onDestroy() {
        stopForegroundCompat()
        super.onDestroy()
    }

    private fun stopForegroundCompat() {
        runCatching {
            ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
        }
    }

    private fun buildNotification(): Notification {
        ensureChannel(this)

        val openApp = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val stop = PendingIntent.getService(
            this,
            1,
            Intent(this, VpnForegroundService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(APP_NAME)
            .setContentText(status)
            .setContentIntent(openApp)
            .addAction(0, stopLabel, stop)
            .setOngoing(true)
            .setShowWhen(false)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .build()
    }

    companion object {
        private const val APP_NAME = "Prosto VPN"
        private const val CHANNEL_ID = "vpn_status"
        private const val NOTIFICATION_ID = 1001
        private const val ACTION_STOP = "com.prostovpn.app.STOP_TUNNEL"
        private const val EXTRA_STATUS = "status"
        private const val EXTRA_STOP_LABEL = "stopLabel"

        private var status: String = "Подключено"
        private var stopLabel: String = "Отключить"

        private var stoppingLabel: String = "Отключаем…"

        private fun ensureChannel(context: Context) {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
            val manager = context.getSystemService(NotificationManager::class.java) ?: return
            if (manager.getNotificationChannel(CHANNEL_ID) != null) return
            manager.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ID,
                    "Состояние VPN",

                    NotificationManager.IMPORTANCE_LOW,
                ).apply {
                    description = "Показывает, что туннель поднят, и не даёт системе выгрузить приложение"
                    setShowBadge(false)
                    enableVibration(false)
                    enableLights(false)
                }
            )
        }

        fun setStoppingLabel(text: String) {
            stoppingLabel = text
        }

        fun start(context: Context, status: String, stopLabel: String) {
            val intent = Intent(context, VpnForegroundService::class.java)
                .putExtra(EXTRA_STATUS, status)
                .putExtra(EXTRA_STOP_LABEL, stopLabel)

            runCatching { ContextCompat.startForegroundService(context, intent) }
        }

        fun stop(context: Context) {
            runCatching {
                context.stopService(Intent(context, VpnForegroundService::class.java))
            }
        }
    }
}
