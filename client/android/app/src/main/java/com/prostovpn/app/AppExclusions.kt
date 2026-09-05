package com.prostovpn.app

import android.content.Context
import android.content.Intent
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.core.graphics.drawable.toBitmap

/**
 * Приложения, которые ходят мимо VPN.
 *
 * Раздельное туннелирование по адресам живёт списком из тысяч подсетей и
 * устаревает всякий раз, когда банк переезжает в облако. Исключение по
 * приложению этого не знает и знать не хочет: Android сам не пускает в
 * туннель ни одного пакета отмеченного приложения, куда бы оно ни ходило.
 * Работает для обоих протоколов — AmneziaWG берёт список из конфига,
 * Reality — прямо в своей службе.
 *
 * Список лежит в тех же настройках, что и остальное: его читает и обычное
 * подключение, и always-on, который поднимает туннель без приложения.
 */
object AppExclusions {
    private const val KEY = "apps.excluded"

    data class Entry(val packageName: String, val label: String)

    private fun prefs(context: Context) = context.getSharedPreferences("prosto", 0)

    fun load(context: Context): Set<String> =
        prefs(context).getString(KEY, "").orEmpty()
            .split(',')
            .map { it.trim() }
            .filter { it.isNotEmpty() }
            .toSet()

    fun save(context: Context, packages: Set<String>) {
        prefs(context).edit().putString(KEY, packages.sorted().joinToString(",")).apply()
    }

    /**
     * Только те из списка, что ещё установлены.
     *
     * Библиотека AmneziaWG на незнакомом пакете роняет подъём туннеля
     * целиком, а человек снёс приложение и забыл — VPN из-за этого
     * отваливаться не должен.
     */
    fun installed(context: Context, packages: Collection<String> = load(context)): List<String> {
        if (packages.isEmpty()) return emptyList()
        val pm = context.packageManager
        return packages.filter { pkg ->
            pkg != context.packageName &&
                runCatching { pm.getApplicationInfo(pkg, 0) }.isSuccess
        }.sorted()
    }

    /**
     * Приложения, у которых есть значок на рабочем столе, — то, что человек
     * вообще может назвать «приложением». Системные службы без иконки в
     * списке ни к чему: их всё равно никто не узнает.
     */
    fun launchable(context: Context): List<Entry> {
        val pm = context.packageManager
        val seen = LinkedHashMap<String, Entry>()
        for (category in listOf(Intent.CATEGORY_LAUNCHER, Intent.CATEGORY_LEANBACK_LAUNCHER)) {
            val intent = Intent(Intent.ACTION_MAIN).addCategory(category)
            @Suppress("DEPRECATION")
            val resolved = runCatching { pm.queryIntentActivities(intent, 0) }
                .getOrDefault(emptyList())
            for (info in resolved) {
                val pkg = info.activityInfo?.packageName ?: continue
                if (pkg == context.packageName || pkg in seen) continue
                val label = runCatching { info.loadLabel(pm).toString() }.getOrDefault("")
                seen[pkg] = Entry(pkg, label.ifBlank { pkg })
            }
        }
        return seen.values.sortedWith(compareBy(String.CASE_INSENSITIVE_ORDER) { it.label })
    }

    fun icon(context: Context, packageName: String, sizePx: Int): ImageBitmap? = runCatching {
        context.packageManager.getApplicationIcon(packageName)
            .toBitmap(sizePx, sizePx)
            .asImageBitmap()
    }.getOrNull()
}
