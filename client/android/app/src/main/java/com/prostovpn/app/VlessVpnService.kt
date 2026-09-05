package com.prostovpn.app

import android.content.Context
import android.content.Intent
import android.net.VpnService
import android.os.ParcelFileDescriptor
import android.util.Log

/**
 * Туннель запасного протокола.
 *
 * Основной протокол поднимает своя служба из библиотеки AmneziaWG, и чужой
 * дескриптор она наружу не отдаёт — поэтому у Reality служба своя. Работают
 * они по очереди, а не разом: Android держит один туннель на приложение, да и
 * смысла в двух нет — это два пути до одного узла.
 */
class VlessVpnService : VpnService() {

    private var tun: ParcelFileDescriptor? = null
    private var xray: XrayTunnel? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            teardown()
            stopSelf()
            return START_NOT_STICKY
        }

        val access = intent?.let(::accessFrom)
        if (access == null) {
            Log.w(TAG, "нет данных для подключения — останавливаемся")
            state = State.FAILED
            stopSelf()
            return START_NOT_STICKY
        }

        return if (connect(access)) {
            state = State.RUNNING
            START_STICKY
        } else {
            teardown()
            state = State.FAILED
            stopSelf()
            START_NOT_STICKY
        }
    }

    private fun connect(access: XrayTunnel.Access): Boolean {
        val core = XrayTunnel(applicationContext)
        xray = core

        val builder = Builder()
            .setSession("ProstoVPN")
            .setMtu(core.mtu)
            .addAddress(TUN_ADDRESS, TUN_PREFIX)
            .apply {
                // «Без рекламы»: резолвер узла вместо публичного. Он отвечает
                // только из туннеля, поэтому и адрес — самого узла.
                val dns = access.dns?.takeIf { it.isNotBlank() }
                if (dns != null) addDnsServer(dns) else {
                    addDnsServer("1.1.1.1")
                    addDnsServer("1.0.0.1")
                }
            }

        // Весь трафик в туннель — двумя половинами вместо 0.0.0.0/0. Так
        // принято на Android: половинки перебивают маршрут по умолчанию, не
        // трогая его самого, и система не спорит за приоритет.
        builder.addRoute("0.0.0.0", 1)
        builder.addRoute("128.0.0.0", 1)

        // Себя в туннель не пускаем. Иначе трафик ядра до узла ушёл бы в
        // туннель, который это же ядро и держит, — и всё встало бы намертво.
        runCatching { builder.addDisallowedApplication(packageName) }
            .onFailure { Log.w(TAG, "не вышло исключить себя из туннеля: ${it.message}") }

        // Приложения, которые человек пустил мимо VPN, — те же, что у
        // AmneziaWG, только там их применяет библиотека из конфига.
        for (pkg in AppExclusions.installed(applicationContext)) {
            runCatching { builder.addDisallowedApplication(pkg) }
                .onFailure { Log.w(TAG, "не вышло исключить $pkg: ${it.message}") }
        }

        val descriptor = runCatching { builder.establish() }.getOrNull()
        if (descriptor == null) {
            Log.w(TAG, "система не выдала туннель")
            failure = "туннель не создан"
            return false
        }
        tun = descriptor

        if (!core.start(access, descriptor)) {
            failure = core.error.ifBlank { "ядро не запустилось" }
            return false
        }
        return true
    }

    private fun teardown() {
        xray?.stop()
        xray = null
        runCatching { tun?.close() }
        tun = null
        if (state == State.RUNNING) state = State.STOPPED
    }

    override fun onDestroy() {
        teardown()
        super.onDestroy()
    }

    override fun onRevoke() {
        // Человек отозвал разрешение или другой VPN перехватил туннель.
        teardown()
        state = State.STOPPED
        stopSelf()
        super.onRevoke()
    }

    private fun accessFrom(intent: Intent): XrayTunnel.Access? {
        val host = intent.getStringExtra(EXTRA_HOST).orEmpty()
        val port = intent.getIntExtra(EXTRA_PORT, 0)
        val id = intent.getStringExtra(EXTRA_ID).orEmpty()
        val publicKey = intent.getStringExtra(EXTRA_PUBLIC_KEY).orEmpty()
        if (host.isEmpty() || port !in 1..65535 || id.isEmpty() || publicKey.isEmpty()) return null
        return XrayTunnel.Access(
            host = host,
            port = port,
            id = id,
            publicKey = publicKey,
            shortId = intent.getStringExtra(EXTRA_SHORT_ID).orEmpty(),
            serverName = intent.getStringExtra(EXTRA_SERVER_NAME).orEmpty(),
            fingerprint = intent.getStringExtra(EXTRA_FINGERPRINT).orEmpty().ifEmpty { "chrome" },
            flow = intent.getStringExtra(EXTRA_FLOW).orEmpty(),
            dns = intent.getStringExtra(EXTRA_DNS),
        )
    }

    /** Сколько прошло с прошлого спроса: принято, отправлено. */
    fun trafficDelta(): Pair<Long, Long> = xray?.trafficDelta() ?: (0L to 0L)

    enum class State { IDLE, RUNNING, STOPPED, FAILED }

    companion object {
        private const val TAG = "ProstoVless"

        private const val TUN_ADDRESS = "10.10.10.2"
        private const val TUN_PREFIX = 32

        private const val ACTION_STOP = "com.prostovpn.app.VLESS_STOP"

        private const val EXTRA_HOST = "host"
        private const val EXTRA_PORT = "port"
        private const val EXTRA_ID = "id"
        private const val EXTRA_PUBLIC_KEY = "publicKey"
        private const val EXTRA_SHORT_ID = "shortId"
        private const val EXTRA_SERVER_NAME = "serverName"
        private const val EXTRA_FINGERPRINT = "fingerprint"
        private const val EXTRA_FLOW = "flow"
        private const val EXTRA_DNS = "dns"

        /**
         * Состояние службы. Через статическое поле, а не через привязку:
         * служба живёт своей жизнью, а спрашивать её состояние нужно из
         * корутины подключения, которой не за что держать соединение.
         */
        @Volatile
        var state: State = State.IDLE
            internal set

        @Volatile
        var failure: String = ""
            internal set

        fun start(context: Context, access: XrayTunnel.Access) {
            state = State.IDLE
            failure = ""
            val intent = Intent(context, VlessVpnService::class.java)
                .putExtra(EXTRA_HOST, access.host)
                .putExtra(EXTRA_PORT, access.port)
                .putExtra(EXTRA_ID, access.id)
                .putExtra(EXTRA_PUBLIC_KEY, access.publicKey)
                .putExtra(EXTRA_SHORT_ID, access.shortId)
                .putExtra(EXTRA_SERVER_NAME, access.serverName)
                .putExtra(EXTRA_FINGERPRINT, access.fingerprint)
                .putExtra(EXTRA_FLOW, access.flow)
                .putExtra(EXTRA_DNS, access.dns)
            context.startService(intent)
        }

        fun stop(context: Context) {
            runCatching {
                context.startService(
                    Intent(context, VlessVpnService::class.java).setAction(ACTION_STOP),
                )
            }
        }
    }
}
