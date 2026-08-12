package com.prostovpn.app

import android.content.Context
import android.content.SharedPreferences
import org.json.JSONArray
import java.io.File

/**
 * Сборка итогового wg-quick конфига из сохранённых настроек.
 *
 * Вынесено из [AppState], потому что нужно и без UI: Always-on VPN поднимает
 * туннель на загрузке телефона, когда ни одной Activity ещё нет. Логика
 * зеркалит [AppState.buildConfigForConnect] без его кэшей — на пути always-on
 * это разовый вызов.
 */
object ConnectConfig {

    private fun prefs(context: Context): SharedPreferences =
        context.getSharedPreferences("prosto", 0)

    /** Сохранённый конфиг подключённого сервера; null — входа не было. */
    fun storedConfig(context: Context): String? =
        prefs(context).getString("server.config", null)?.takeIf { it.isNotBlank() }

    fun defaultListJson(context: Context): String? = runCatching {
        context.assets.open(AppState.DEFAULT_FILE_NAME).bufferedReader().use { it.readText() }
    }.getOrNull()

    /** Содержимое активного списка исключений; по мере отказов — встроенный список. */
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

    /** Итоговый конфиг с учётом сплит-туннеля. */
    fun build(context: Context, base: String): String {
        val withDns = SplitTunnel.ensureMtu(SplitTunnel.ensureDns(base))
        if (!prefs(context).getBoolean("split.enabled", false)) {
            return SplitTunnel.applyToConfig(withDns, FULL_TUNNEL)
        }
        val content = activeListContent(context)
            ?: return SplitTunnel.applyToConfig(withDns, FULL_TUNNEL)
        val allowed = SplitTunnel.allowedIpsExcept(SplitTunnel.parseCidrList(content))
        return SplitTunnel.applyToConfig(withDns, allowed)
    }

    /*
    ::/0 в маршрутах туннеля обязателен, даже когда у интерфейса нет
    IPv6-адреса, и это не опечатка. Библиотека awg при ПОЛНОМ отсутствии
    IPv6-маршрутов зовёт allowFamily(AF_INET6) у VpnService — и весь IPv6
    уходит МИМО туннеля, с настоящим адресом абонента. На мобильных сетях с
    IPv6 (обычных у операторов и особенно заметных на Huawei) это выглядело
    как «VPN не работает»: IPv4 шёл через туннель, а двухстековые сайты —
    YouTube, Google — открывались напрямую по IPv6 и видели реальную страну.

    Раньше при полном туннеле без v6-адреса ставилось только «0.0.0.0/0», и
    ветка раздельного туннелирования (там ::/0 стоит всегда) вела себя иначе,
    чем полный туннель, — ровно этот перекос и утекал. С ::/0 весь IPv6
    заворачивается в туннель; узел без IPv6-аплинка его гасит, и приложения
    сами переходят на IPv4 через туннель. Никакой утечки.
    */
    private const val FULL_TUNNEL = "0.0.0.0/0, ::/0"
}
