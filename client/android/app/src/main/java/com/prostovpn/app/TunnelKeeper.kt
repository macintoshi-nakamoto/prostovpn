package com.prostovpn.app

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.util.Log

/**
 * Что вокруг туннеля знает о сети.
 *
 * Отдельно от [TunnelManager] по одной причине: туннелю нужен ответ на вопрос
 * «сеть вообще есть и не та ли это сеть, что была», а не весь
 * [ConnectivityManager]. Держать эти три метода внутри менеджера значило бы
 * смешать управление туннелем с опросом системы, а проверять их по отдельности
 * из двух мест — получить два разных представления о том, что происходит.
 */
object NetworkInfo {

    private fun manager(context: Context): ConnectivityManager? =
        runCatching { context.getSystemService(ConnectivityManager::class.java) }.getOrNull()

    /**
     * Есть ли сейчас сеть, через которую вообще можно подключаться.
     *
     * Без этой проверки надзор за туннелем в метро или в лифте молотит
     * попытку за попыткой: каждая поднимает интерфейс, ждёт рукопожатия и
     * ничего не получает — просто потому, что сети нет. Это и батарею жжёт,
     * и загоняет счётчик неудач в потолок к тому моменту, когда сеть
     * вернётся.
     */
    fun isOnline(context: Context): Boolean {
        val cm = manager(context) ?: return true
        val network = runCatching { cm.activeNetwork }.getOrNull() ?: return false
        val caps = runCatching { cm.getNetworkCapabilities(network) }.getOrNull() ?: return false
        return caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
    }

    /**
     * Метка текущей сети: по её смене видно, что маршрут наружу стал другим.
     *
     * Сравниваем идентификатор объекта [Network]: система выдаёт новый при
     * КАЖДОЙ смене подключения — Wi-Fi на LTE, LTE на другую соту с новым
     * адресом, возврат из авиарежима. Именно в этот момент сокет wg-go
     * остаётся привязанным к исчезнувшему маршруту: туннель формально поднят,
     * а пакеты не уходят никуда. Снаружи это «VPN включён, интернета нет».
     */
    fun currentNetworkId(context: Context): String {
        val cm = manager(context) ?: return ""
        return runCatching { cm.activeNetwork?.toString() }.getOrNull().orEmpty()
    }

    /** Тип сети словом — для диагностики в панели, не для логики. */
    fun kind(context: Context): String {
        val cm = manager(context) ?: return "unknown"
        val caps = runCatching { cm.getNetworkCapabilities(cm.activeNetwork) }.getOrNull()
            ?: return "none"
        return when {
            caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "cellular"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "ethernet"
            else -> "other"
        }
    }

    /**
     * Подписка на смену сети по умолчанию.
     *
     * Возвращает функцию отписки; null — система не дала подписаться (такое
     * бывает на урезанных прошивках), и тогда надзор обходится своим опросом.
     */
    fun watch(context: Context, onChanged: () -> Unit): (() -> Unit)? {
        val cm = manager(context) ?: return null
        val callback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) = onChanged()
            override fun onLost(network: Network) = onChanged()
            override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) {
                // Смена возможностей — это и переход между сотами с новым
                // адресом, и подъём Wi-Fi поверх мобильной сети. Для нас
                // событие то же: маршрут наружу мог стать другим.
                onChanged()
            }
        }
        return runCatching {
            cm.registerDefaultNetworkCallback(callback)
            val undo: () -> Unit = { runCatching { cm.unregisterNetworkCallback(callback) } }
            undo
        }.onFailure { Log.w(TAG, "не удалось подписаться на смену сети", it) }.getOrNull()
    }

    private const val TAG = "ProstoNet"
}

/**
 * Перебор точек подключения.
 *
 * Узел один, а портов у него может быть несколько: канонический 51820 у
 * заметной части операторов просто не проходит — его режут как известный порт
 * WireGuard, и человек видит вечное «подключение» на исправном приложении и
 * исправном сервере. Пробовать другой порт — единственное, что здесь помогает
 * со стороны клиента.
 *
 * Список запасных портов приходит от панели вместе с конфигом. Пустой список —
 * поведение ровно прежнее: один эндпоинт, как было. Это намеренно: клиент не
 * должен гадать, какие порты слушает узел, иначе он будет упорно стучаться
 * туда, где никого нет, и тратить на это минуты вместо секунд.
 */
object Endpoints {

    private val ENDPOINT = Regex("""(?im)^(\s*Endpoint\s*=\s*)(\S+?)(?::(\d+))?\s*$""")

    /** Порт из конфига; 0 — не нашли. */
    fun portOf(config: String): Int =
        ENDPOINT.find(config)?.groupValues?.getOrNull(3)?.toIntOrNull() ?: 0

    /** Тот же конфиг, но с другим портом эндпоинта. */
    fun withPort(config: String, port: Int): String =
        ENDPOINT.replace(config) { m -> "${m.groupValues[1]}${m.groupValues[2]}:$port" }

    /**
     * Порядок перебора: сначала тот, что уже работал, потом основной, потом запасные.
     *
     * Запомненный порт идёт первым не ради скорости, а ради предсказуемости:
     * если у человека в сети проходит только 443, он не должен каждый раз
     * заново терять полминуты на основном порту.
     */
    fun order(configPort: Int, remembered: Int, alternatives: List<Int>): List<Int> {
        val out = ArrayList<Int>(alternatives.size + 2)
        if (remembered > 0) out.add(remembered)
        if (configPort > 0 && configPort !in out) out.add(configPort)
        for (p in alternatives) if (p > 0 && p !in out) out.add(p)
        return out
    }
}
