package com.prostovpn.app

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings

object BackgroundWork {
    fun isUnrestricted(context: Context): Boolean {
        val power = context.getSystemService(PowerManager::class.java) ?: return true
        return runCatching { power.isIgnoringBatteryOptimizations(context.packageName) }
            .getOrDefault(false)
    }

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

    fun openOemAutoStart(context: Context): Boolean =
        OEM_SCREENS.any { start(context, Intent().setComponent(it)) }

    fun hasOemAutoStart(context: Context): Boolean =
        OEM_SCREENS.any { resolves(context, Intent().setComponent(it)) }

    private val OEM_SCREENS = listOf(

        ComponentName("com.huawei.systemmanager", "com.huawei.systemmanager.startupmgr.ui.StartupNormalAppListActivity"),
        ComponentName("com.huawei.systemmanager", "com.huawei.systemmanager.appcontrol.activity.StartupAppControlActivity"),
        ComponentName("com.huawei.systemmanager", "com.huawei.systemmanager.optimize.process.ProtectActivity"),

        ComponentName("com.hihonor.systemmanager", "com.hihonor.systemmanager.startupmgr.ui.StartupNormalAppListActivity"),

        ComponentName("com.miui.securitycenter", "com.miui.permcenter.autostart.AutoStartManagementActivity"),

        ComponentName("com.coloros.safecenter", "com.coloros.safecenter.permission.startup.StartupAppListActivity"),
        ComponentName("com.coloros.safecenter", "com.coloros.safecenter.startupapp.StartupAppListActivity"),
        ComponentName("com.oppo.safe", "com.oppo.safe.permission.startup.StartupAppListActivity"),

        ComponentName("com.vivo.permissionmanager", "com.vivo.permissionmanager.activity.BgStartUpManagerActivity"),
        ComponentName("com.iqoo.secure", "com.iqoo.secure.ui.phoneoptimize.BgStartUpManager"),

        ComponentName("com.samsung.android.lool", "com.samsung.android.sm.ui.battery.BatteryActivity"),

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
