package com.prostovpn.app

import android.content.Context
import android.content.SharedPreferences
import org.json.JSONArray
import java.io.File

object ConnectConfig {
    private fun prefs(context: Context): SharedPreferences =
        context.getSharedPreferences("prosto", 0)

    fun storedConfig(context: Context): String? =
        prefs(context).getString("server.config", null)?.takeIf { it.isNotBlank() }

    fun storedAltPorts(context: Context): List<Int> =
        (prefs(context).getString("server.altPorts", "") ?: "")
            .split(',')
            .mapNotNull { it.trim().toIntOrNull() }

    fun defaultListJson(context: Context): String? = runCatching {
        context.assets.open(AppState.DEFAULT_FILE_NAME).bufferedReader().use { it.readText() }
    }.getOrNull()

    private fun activeListContent(context: Context): String? {
        val p = prefs(context)
        val activeId = p.getString("tunnel.active", AppState.DEFAULT_FILE_ID) ?: AppState.DEFAULT_FILE_ID
        if (activeId == AppState.DEFAULT_FILE_ID) return defaultListJson(context)
        val name = runCatching {
            val arr = JSONArray(p.getString("tunnel.files", "[]") ?: "[]")
            (0 until arr.length()).asSequence()
                .mapNotNull { arr.optJSONObject(it) }
                .firstOrNull { it.optString("id") == activeId }
                ?.optString("name")
        }.getOrNull()
        if (name.isNullOrEmpty()) return defaultListJson(context)
        return runCatching { File(File(context.filesDir, "tunneling"), name).readText() }.getOrNull()
            ?: defaultListJson(context)
    }

    fun build(context: Context, base: String): String {
        val withDns = SplitTunnel.ensureExcludedApps(
            SplitTunnel.ensureMtu(SplitTunnel.ensureDns(base)),
            AppExclusions.installed(context),
        )
        if (!prefs(context).getBoolean("split.enabled", false)) {
            return SplitTunnel.applyToConfig(withDns, FULL_TUNNEL)
        }
        val content = activeListContent(context)
            ?: return SplitTunnel.applyToConfig(withDns, FULL_TUNNEL)
        val allowed = SplitTunnel.allowedIpsExcept(SplitTunnel.parseCidrList(content))
        return SplitTunnel.applyToConfig(withDns, allowed)
    }

    private const val FULL_TUNNEL = "0.0.0.0/0, ::/0"
}
