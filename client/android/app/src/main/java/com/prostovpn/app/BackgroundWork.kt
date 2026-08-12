package com.prostovpn.app

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings

/**
 * Снятие ограничений на фоновую работу.
 *
 * Туннель wg-go исполняется в процессе приложения: выгрузили процесс — оборвался
 * VPN. Постоянное уведомление ([VpnForegroundService]) спасает от штатного
 * механизма Android, но не от вендорских «оптимизаторов»: PowerGenie у Huawei и
 * Honor, «Автозапуск» у Xiaomi, «Спящие приложения» у Samsung чистят фон по
 * собственным спискам и foreground-состояние учитывают не всегда.
 *
 * Ни один из этих списков не правится из приложения — только руками пользователя
 * в системных настройках. Здесь мы умеем лишь отвести его туда кратчайшим путём.
 */
object BackgroundWork {

    /** Приложение уже выведено из-под оптимизации батареи? */
    fun isUnrestricted(context: Context): Boolean {
        val power = context.getSystemService(PowerManager::class.java) ?: return true
        return runCatching { power.isIgnoringBatteryOptimizations(context.packageName) }
            .getOrDefault(false)
    }

    /**
     * Системный диалог «разрешить работу в фоне».
     *
     * Открываем именно диалог для нашего пакета: общий список
     * [Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS] заставляет искать
     * приложение среди сотни других. Если производитель диалог вырезал —
     * откатываемся на общий экран, а затем на страницу приложения.
     */
    fun request(context: Context) {
        val direct = Intent(
            Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
            Uri.parse("package:${context.packageName}"),
        )
        if (start(context, direct)) return

        if (start(context, Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))) return

        start(
            context,
            Intent(
                Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                Uri.parse("package:${context.packageName}"),
            ),
        )
    }

    /**
     * Экран автозапуска оболочки, если он тут есть.
     *
     * Отдельная от оптимизации батареи вещь: на EMUI приложение может быть
     * выведено из-под оптимизации и всё равно выгружаться, пока не отмечено в
     * «Запуск приложений». Возвращает false, если оболочка не опознана —
     * на чистом Android это норма, и звать пользователя никуда не нужно.
     */
    fun openOemAutoStart(context: Context): Boolean =
        OEM_SCREENS.any { start(context, Intent().setComponent(it)) }

    /** true, если такой экран в системе есть — по нему решаем, показывать ли пункт. */
    fun hasOemAutoStart(context: Context): Boolean =
        OEM_SCREENS.any { resolves(context, Intent().setComponent(it)) }

    private val OEM_SCREENS = listOf(
        // Huawei и Honor (EMUI / Magic UI): «Запуск приложений»
        ComponentName("com.huawei.systemmanager", "com.huawei.systemmanager.startupmgr.ui.StartupNormalAppListActivity"),
        ComponentName("com.huawei.systemmanager", "com.huawei.systemmanager.appcontrol.activity.StartupAppControlActivity"),
        ComponentName("com.huawei.systemmanager", "com.huawei.systemmanager.optimize.process.ProtectActivity"),
        // Honor после отделения от Huawei
        ComponentName("com.hihonor.systemmanager", "com.hihonor.systemmanager.startupmgr.ui.StartupNormalAppListActivity"),
        // Xiaomi / Redmi / POCO (MIUI, HyperOS)
        ComponentName("com.miui.securitycenter", "com.miui.permcenter.autostart.AutoStartManagementActivity"),
        // Oppo и Realme (ColorOS)
        ComponentName("com.coloros.safecenter", "com.coloros.safecenter.permission.startup.StartupAppListActivity"),
        ComponentName("com.coloros.safecenter", "com.coloros.safecenter.startupapp.StartupAppListActivity"),
        ComponentName("com.oppo.safe", "com.oppo.safe.permission.startup.StartupAppListActivity"),
        // Vivo (Funtouch OS / OriginOS)
        ComponentName("com.vivo.permissionmanager", "com.vivo.permissionmanager.activity.BgStartUpManagerActivity"),
        ComponentName("com.iqoo.secure", "com.iqoo.secure.ui.phoneoptimize.BgStartUpManager"),
        // Samsung (One UI): экран батареи, где живут «Спящие приложения»
        ComponentName("com.samsung.android.lool", "com.samsung.android.sm.ui.battery.BatteryActivity"),
        // Meizu (Flyme)
        ComponentName("com.meizu.safe", "com.meizu.safe.security.SHOW_APPSEC"),
    )

    private fun resolves(context: Context, intent: Intent): Boolean =
        runCatching {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                context.packageManager.resolveActivity(
                    intent,
                    android.content.pm.PackageManager.ResolveInfoFlags.of(0L),
                )
            } else {
                @Suppress("DEPRECATION")
                context.packageManager.resolveActivity(intent, 0)
            } != null
        }.getOrDefault(false)

    private fun start(context: Context, intent: Intent): Boolean {
        if (!resolves(context, intent)) return false
        return runCatching {
            context.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            true
        }.getOrDefault(false)
    }
}
