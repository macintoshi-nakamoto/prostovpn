package com.prostovpn.app

import android.content.Context
import android.os.ParcelFileDescriptor
import android.util.Log
import libv2ray.CoreCallbackHandler
import libv2ray.CoreController
import libv2ray.Libv2ray
import org.json.JSONArray
import org.json.JSONObject

/**
 * Запасной протокол: VLESS поверх Reality.
 *
 * Нужен там, где AmneziaWG не проходит вовсе. Тот идёт по UDP, и сеть, которая
 * режет UDP целиком, не оставляет ему ни одного шанса — сколько портов ни
 * перебирай. Reality идёт по TCP на 443 и от настоящего HTTPS к донорскому
 * сайту неотличим.
 *
 * На Android всё проще, чем на настольной машине: ядро xray умеет работать с
 * дескриптором, который выдаёт VpnService, — отдельная прослойка вроде
 * tun2socks не нужна. Дескриптор уходит в ядро вторым аргументом StartLoop,
 * а туда, где его ждут, ядро кладёт себе в окружение само.
 */
class XrayTunnel(private val context: Context) {

    data class Access(
        // Резолвер без рекламы — адрес узла; пусто — обычный 1.1.1.1.
        val dns: String? = null,
        val host: String,
        val port: Int,
        val id: String,
        val publicKey: String,
        val shortId: String,
        val serverName: String,
        val fingerprint: String,
        val flow: String,
    )

    private var controller: CoreController? = null

    @Volatile
    private var lastError: String = ""

    val error: String get() = lastError

    /**
     * MTU туннеля. Меньше обычного: пакет уезжает в TCP-соединение поверх
     * TLS, и заголовков по дороге набирается прилично. С запасом надёжнее —
     * фрагментация здесь стоит дороже сотни-другой байт.
     */
    val mtu: Int get() = 1400

    private fun buildConfig(access: Access): String {
        // Вход — сам дескриптор VpnService. Адрес и маршруты уже расставлены
        // на той стороне, ядру остаётся читать и писать.
        val inbound = JSONObject()
            .put("tag", "tun")
            .put("protocol", "tun")
            // Порт этому входу не нужен и не используется, но разбор конфига
            // требует поле — без него ядро спотыкается ещё до чтения настроек.
            .put("port", 0)
            .put(
                "settings",
                JSONObject()
                    .put("name", "tun0")
                    .put("mtu", mtu),
            )
            .put("sniffing", JSONObject().put("enabled", false))

        val user = JSONObject()
            .put("id", access.id)
            .put("encryption", "none")
        if (access.flow.isNotBlank()) user.put("flow", access.flow)

        val reality = JSONObject()
            .put("serverName", access.serverName)
            .put("fingerprint", access.fingerprint.ifBlank { "chrome" })
            .put("publicKey", access.publicKey)
        if (access.shortId.isNotBlank()) reality.put("shortId", access.shortId)

        val outbound = JSONObject()
            .put("tag", "proxy")
            .put("protocol", "vless")
            .put(
                "settings",
                JSONObject().put(
                    "vnext",
                    JSONArray().put(
                        JSONObject()
                            .put("address", access.host)
                            .put("port", access.port)
                            .put("users", JSONArray().put(user)),
                    ),
                ),
            )
            .put(
                "streamSettings",
                JSONObject()
                    .put("network", "tcp")
                    .put("security", "reality")
                    .put("realitySettings", reality),
            )

        return JSONObject()
            .put("log", JSONObject().put("loglevel", "warning"))
            .put("inbounds", JSONArray().put(inbound))
            .put("outbounds", JSONArray().put(outbound))
            .toString()
    }

    /**
     * Поднимает ядро на уже готовом дескрипторе. `true` — получилось.
     *
     * Дескриптор остаётся за вызывающим: закрывать его здесь нельзя, иначе
     * туннель схлопнется вместе с ним при первой же ошибке.
     */
    fun start(access: Access, tun: ParcelFileDescriptor): Boolean {
        stop()
        lastError = ""

        return try {
            // Каталог с ассетами ядру нужен всегда, даже когда баз гео нет:
            // без него оно ругается на пустой путь ещё до чтения конфига.
            Libv2ray.initCoreEnv(context.filesDir.absolutePath, "")

            val core = Libv2ray.newCoreController(object : CoreCallbackHandler {
                override fun startup(): Long = 0
                override fun shutdown(): Long = 0
                override fun onEmitStatus(code: Long, message: String?): Long {
                    if (!message.isNullOrBlank()) Log.i(TAG, "ядро: $message")
                    return 0
                }
            })
            core.startLoop(buildConfig(access), tun.fd)
            controller = core
            Log.i(TAG, "запасной протокол поднят на ${access.host}:${access.port}")
            true
        } catch (error: Throwable) {
            lastError = error.message.orEmpty().take(600)
            Log.w(TAG, "запасной протокол не поднялся: $lastError")
            stop()
            false
        }
    }

    fun stop() {
        controller?.let { core ->
            runCatching { core.stopLoop() }
                .onFailure { Log.w(TAG, "ядро не остановилось: ${it.message}") }
        }
        controller = null
    }

    val isRunning: Boolean
        get() = runCatching { controller?.isRunning == true }.getOrDefault(false)

    /**
     * Принято и отправлено байт с прошлого вызова.
     *
     * Счётчики у ядра нарастающие не бывают: `queryAllOutboundTrafficStats`
     * их обнуляет при чтении. Поэтому наружу отдаём именно приращение — тем,
     * кто следит за жизнью туннеля, только оно и нужно.
     *
     * Формат строки — `тег,направление,значение;` через точку с запятой.
     */
    fun trafficDelta(): Pair<Long, Long> {
        val raw = runCatching { controller?.queryAllOutboundTrafficStats() }
            .getOrNull().orEmpty()
        if (raw.isBlank()) return 0L to 0L

        var down = 0L
        var up = 0L
        for (chunk in raw.split(';')) {
            val parts = chunk.split(',')
            if (parts.size < 3) continue
            val value = parts[2].trim().toLongOrNull() ?: continue
            when (parts[1].trim()) {
                "downlink" -> down += value
                "uplink" -> up += value
            }
        }
        return down to up
    }

    private companion object {
        const val TAG = "ProstoXray"
    }
}
