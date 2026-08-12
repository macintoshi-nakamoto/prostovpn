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
import kotlinx.coroutines.runBlocking

/**
 * Держит процесс живым, пока поднят туннель.
 *
 * Туннель wg-go исполняется внутри процесса приложения, а не в системе: как
 * только процесс убит, VPN рвётся. Голого [android.net.VpnService] для выживания
 * не хватает — оболочки Huawei/Honor (PowerGenie), Xiaomi и Oppo чистят фон по
 * своим спискам и штатный приоритет VPN-приложения не учитывают. Постоянное
 * уведомление переводит процесс в foreground-состояние, которое они уважают.
 *
 * Сервис ничего не знает о туннеле сверх кнопки «отключить»: состоянием
 * по-прежнему владеет [AppState].
 */
class VpnForegroundService : Service() {

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            // Отключение из шторки: процесс приложения может быть без Activity,
            // поэтому дёргаем общий на процесс туннель напрямую. runBlocking здесь
            // уместен — снятие занимает миллисекунды, а сервис всё равно уходит.
            runCatching { runBlocking { TunnelManager.getInstance(applicationContext).disconnect() } }
            stopForegroundCompat()
            stopSelf()
            return START_NOT_STICKY
        }

        intent?.getStringExtra(EXTRA_STATUS)?.let { status = it }
        intent?.getStringExtra(EXTRA_STOP_LABEL)?.let { stopLabel = it }

        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
        } else {
            0
        }
        /*
        Android 14+ роняет приложение с MissingForegroundServiceTypeException, если
        тип не объявлен; на 13+ уведомление не покажется без POST_NOTIFICATIONS —
        в обоих случаях падать нельзя, VPN важнее уведомления.
        */
        runCatching {
            ServiceCompat.startForeground(this, NOTIFICATION_ID, buildNotification(), type)
        }
        return START_NOT_STICKY
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

        // Переживают пересоздание сервиса системой, чтобы уведомление не осталось пустым
        private var status: String = "Подключено"
        private var stopLabel: String = "Отключить"

        private fun ensureChannel(context: Context) {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
            val manager = context.getSystemService(NotificationManager::class.java) ?: return
            if (manager.getNotificationChannel(CHANNEL_ID) != null) return
            manager.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ID,
                    "Состояние VPN",
                    // LOW: постоянное уведомление не должно звенеть и всплывать
                    NotificationManager.IMPORTANCE_LOW,
                ).apply {
                    description = "Показывает, что туннель поднят, и не даёт системе выгрузить приложение"
                    setShowBadge(false)
                    enableVibration(false)
                    enableLights(false)
                }
            )
        }

        /** Поднимает уведомление. [status] и [stopLabel] уже локализованы вызывающим. */
        fun start(context: Context, status: String, stopLabel: String) {
            val intent = Intent(context, VpnForegroundService::class.java)
                .putExtra(EXTRA_STATUS, status)
                .putExtra(EXTRA_STOP_LABEL, stopLabel)
            /*
            С Android 12 запуск foreground-сервиса из фона запрещён. Сюда приходим
            только по действию пользователя или из уже видимой Activity, но на
            гонке «свернули в момент подключения» система всё равно может отказать —
            туннель из-за этого ронять нельзя.
            */
            runCatching { ContextCompat.startForegroundService(context, intent) }
        }

        fun stop(context: Context) {
            runCatching {
                context.stopService(Intent(context, VpnForegroundService::class.java))
            }
        }
    }
}
