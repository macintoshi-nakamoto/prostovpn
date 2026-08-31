package com.prostovpn.desktop

import java.io.File
import java.util.Base64
import java.util.concurrent.TimeUnit
import org.json.JSONArray
import org.json.JSONObject

/**
 * Запасной протокол: VLESS поверх Reality.
 *
 * Нужен там, где AmneziaWG не проходит вовсе. Тот идёт по UDP, и сеть, которая
 * режет UDP целиком, не оставляет ему ни одного шанса — сколько портов ни
 * перебирай. Reality же идёт по TCP на 443 и от настоящего HTTPS к донорскому
 * сайту неотличим: чтобы его закрыть, пришлось бы закрыть и половину интернета.
 *
 * Собран из двух готовых частей, потому что VLESS — прокси, а не туннель:
 *   * `xray.exe` поднимает у себя внутри SOCKS5 на localhost и уводит всё,
 *     что туда попало, на узел через Reality;
 *   * `tun2socks.exe` создаёт сетевой адаптер и заворачивает в этот SOCKS5
 *     весь трафик машины — без него через прокси пошёл бы только браузер.
 *
 * Права администратора нужны один раз и только второй половине: адаптер и
 * маршруты. Сам xray живёт обычным процессом — он слушает localhost, и просить
 * ради него UAC не за что.
 */
object XrayTunnel {

    data class Access(
        val host: String,
        val port: Int,
        val id: String,
        val publicKey: String,
        val shortId: String,
        val serverName: String,
        val fingerprint: String,
        val flow: String,
    )

    enum class Reason { NoBackend, ElevationDenied, NoRoute, ProxyFailed, TunnelFailed }

    sealed interface Result {
        data object Success : Result
        data class Failure(val reason: Reason, val detail: String = "") : Result
    }

    private const val ADAPTER = "prostovpn-vless"

    // Адрес адаптера. Диапазон 172.19 выбран не глядя в потолок: 10.x занят
    // самим VPN, 192.168.x — домашние сети, а 172.19 в быту почти не
    // встречается, и наш адаптер не подерётся с чужой подсетью.
    private const val TUN_ADDRESS = "172.19.0.2"
    private const val TUN_GATEWAY = "172.19.0.1"

    // Порт SOCKS выбран из «частного» диапазона и заведомо не занят службами.
    private const val SOCKS_PORT = 10808

    private const val HANDSHAKE_TIMEOUT_MS = 20_000L

    private val isWindows: Boolean
        get() = System.getProperty("os.name").orEmpty().startsWith("Windows", ignoreCase = true)

    private var xrayProcess: Process? = null

    private fun dataDir(): File = WindowsTunnel.dataDir()

    private fun binary(name: String): File? {
        val candidates = mutableListOf<File>()
        System.getProperty("compose.application.resources.dir")?.let { candidates += File(it, name) }
        runCatching {
            val here = File(
                XrayTunnel::class.java.protectionDomain.codeSource.location.toURI()
            ).parentFile
            candidates += File(here, name)
            candidates += File(here.parentFile, "app\\$name")
        }
        candidates += File("resources/windows/$name")
        candidates += File("windows/resources/windows/$name")
        return candidates.firstOrNull { it.isFile }
    }

    /**
     * Конфиг xray: SOCKS внутрь, Reality наружу.
     *
     * `sockopt.mark` и прочую экзотику не трогаем — трафик до узла уходит через
     * обычный маршрут, который мы отдельно прибиваем к физическому шлюзу.
     */
    private fun buildConfig(access: Access): String {
        val inbound = JSONObject()
            .put("tag", "socks")
            .put("listen", "127.0.0.1")
            .put("port", SOCKS_PORT)
            .put("protocol", "socks")
            .put("settings", JSONObject().put("udp", true).put("auth", "noauth"))
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
            .put("log", JSONObject().put("loglevel", "warning").put("access", "none"))
            .put("inbounds", JSONArray().put(inbound))
            .put("outbounds", JSONArray().put(outbound))
            .toString(2)
    }

    /**
     * Скрипт, который поднимает адаптер и разводит маршруты.
     *
     * Всё делается одним заходом с правами администратора: просить UAC на
     * каждую команду по отдельности — верный способ, чтобы человек нажал
     * «нет» на третьем окне.
     *
     * Порядок важен. Сперва прибиваем дорогу до самого узла через нынешний
     * шлюз: если этого не сделать, трафик xray до сервера уйдёт в туннель,
     * который сам же собой и является, и всё встанет намертво. Только потом
     * уводим в адаптер весь остальной трафик.
     */
    private fun upScript(serverHost: String, tun2socks: File, socksPort: Int): String = """
        ${'$'}ErrorActionPreference = 'Stop'

        # Шлюз запоминаем ДО того, как появится наш адаптер: после он сам
        # станет маршрутом по умолчанию, и «нынешний шлюз» будет уже нашим.
        ${'$'}gateway = (Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction Stop |
            Sort-Object -Property RouteMetric | Select-Object -First 1).NextHop
        if (-not ${'$'}gateway) { throw 'не нашёлся шлюз по умолчанию' }

        # Дорога до узла — первым делом и через физический шлюз. Иначе трафик
        # xray до сервера уйдёт в туннель, которым xray сам и является, и всё
        # встанет намертво. Ставим её прежде, чем поднимется адаптер: между
        # его появлением и этой строкой не должно быть ни одного мгновения.
        route delete $serverHost mask 255.255.255.255 2>${'$'}null | Out-Null
        route add $serverHost mask 255.255.255.255 ${'$'}gateway metric 5 | Out-Null

        # Флаги только в длинной форме и с двумя дефисами: разбор здесь на
        # pflag, и '-device' он молча не понимает — печатает справку и выходит,
        # то есть запасной протокол просто не поднимется. Драйвер задаётся как
        # tun://имя: 'wintun://' эта сборка не знает.
        Start-Process -FilePath '${tun2socks.absolutePath}' -WindowStyle Hidden -ArgumentList @(
            '--device', 'tun://$ADAPTER',
            '--proxy', 'socks5://127.0.0.1:$socksPort',
            '--loglevel', 'warn'
        )

        ${'$'}deadline = (Get-Date).AddSeconds(15)
        do {
            Start-Sleep -Milliseconds 400
            ${'$'}iface = Get-NetAdapter -Name '$ADAPTER' -ErrorAction SilentlyContinue
        } while (-not ${'$'}iface -and (Get-Date) -lt ${'$'}deadline)
        if (-not ${'$'}iface) {
            route delete $serverHost mask 255.255.255.255 2>${'$'}null | Out-Null
            throw 'адаптер $ADAPTER не появился'
        }

        # Адрес без -DefaultGateway: иначе Windows заведёт маршрут по
        # умолчанию сама, со своей метрикой и в свой момент — а нам важно
        # поставить его последним и с известной метрикой.
        New-NetIPAddress -InterfaceAlias '$ADAPTER' -IPAddress '$TUN_ADDRESS' `
            -PrefixLength 24 -ErrorAction SilentlyContinue | Out-Null
        Set-DnsClientServerAddress -InterfaceAlias '$ADAPTER' -ServerAddresses ('1.1.1.1','1.0.0.1')

        route add 0.0.0.0 mask 0.0.0.0 $TUN_GATEWAY metric 6 if ${'$'}(${'$'}iface.ifIndex) | Out-Null
        exit 0
    """.trimIndent()

    private fun downScript(serverHost: String): String = """
        ${'$'}ErrorActionPreference = 'SilentlyContinue'
        route delete 0.0.0.0 mask 0.0.0.0 $TUN_GATEWAY | Out-Null
        route delete $serverHost mask 255.255.255.255 | Out-Null
        Get-Process -Name 'tun2socks' | Stop-Process -Force
        exit 0
    """.trimIndent()

    private fun runElevated(script: String, waitSeconds: Long): ElevationResult {
        val encoded = Base64.getEncoder().encodeToString(script.toByteArray(Charsets.UTF_16LE))
        val outer = "Start-Process -FilePath powershell.exe -Verb RunAs -WindowStyle Hidden -Wait " +
            "-ArgumentList '-NoProfile','-EncodedCommand','$encoded'"
        return runCatching {
            val process = ProcessBuilder(
                "powershell.exe", "-NoProfile", "-NonInteractive", "-Command", outer,
            ).redirectErrorStream(true).start()
            if (!process.waitFor(waitSeconds, TimeUnit.SECONDS)) {
                process.destroyForcibly()
                return ElevationResult.Error
            }
            // 1223 — человек нажал «нет» в окне UAC. Это не поломка, а отказ,
            // и говорить о нём надо иначе, чем о сбое.
            when (process.exitValue()) {
                0 -> ElevationResult.Ok
                1223 -> ElevationResult.Denied
                else -> ElevationResult.Error
            }
        }.getOrDefault(ElevationResult.Error)
    }

    private enum class ElevationResult { Ok, Denied, Error }

    fun connect(access: Access): Result {
        if (!isWindows) return Result.Failure(Reason.NoBackend, "не Windows")

        val xray = binary("xray.exe")
            ?: return Result.Failure(Reason.NoBackend, "xray.exe не найден")
        val tun2socks = binary("tun2socks.exe")
            ?: return Result.Failure(Reason.NoBackend, "tun2socks.exe не найден")

        disconnect()

        val config = File(dataDir(), "xray.json")
        runCatching { config.writeText(buildConfig(access)) }
            .onFailure { return Result.Failure(Reason.ProxyFailed, "не записать конфиг: ${it.message}") }

        val log = File(dataDir(), "xray.log")
        runCatching { log.delete() }

        val started = runCatching {
            ProcessBuilder(xray.absolutePath, "run", "-c", config.absolutePath)
                .directory(dataDir())
                .redirectErrorStream(true)
                .redirectOutput(log)
                .start()
        }.getOrNull() ?: return Result.Failure(Reason.ProxyFailed, "xray не запустился")
        xrayProcess = started

        // Ждём, пока SOCKS начнёт принимать: поднимать адаптер раньше нельзя —
        // трафик уйдёт в прокси, которого ещё нет, и первые секунды человек
        // проведёт без сети.
        if (!waitForSocks()) {
            // Сюда доходим до всякой возни с правами: поднялся только xray,
            // маршруты не трогали — хватит обычной остановки процесса.
            stopXray()
            val detail = runCatching { log.readText().lines().lastOrNull { it.isNotBlank() } }
                .getOrNull().orEmpty()
            return Result.Failure(Reason.ProxyFailed, detail.take(200))
        }

        return when (runElevated(upScript(access.host, tun2socks, SOCKS_PORT), waitSeconds = 60)) {
            ElevationResult.Denied -> {
                // Прав не дали — значит ни адаптера, ни маршрутов не появилось,
                // и убирать нечего. Гасим только свой процесс: второе окно UAC
                // сразу после «нет» — издевательство над человеком.
                stopXray()
                Result.Failure(Reason.ElevationDenied)
            }
            ElevationResult.Error -> {
                // А здесь права дали, и скрипт мог успеть наполовину: маршрут
                // до узла есть, адаптера нет. Прибираем по-настоящему.
                disconnect(access.host)
                Result.Failure(Reason.TunnelFailed, "адаптер не поднялся")
            }
            ElevationResult.Ok -> Result.Success
        }
    }

    /** Гасит только xray — без прав и без окон. */
    private fun stopXray() {
        xrayProcess?.let { process ->
            runCatching {
                process.destroy()
                if (!process.waitFor(5, TimeUnit.SECONDS)) process.destroyForcibly()
            }
        }
        xrayProcess = null
    }

    private fun waitForSocks(): Boolean {
        val deadline = System.currentTimeMillis() + HANDSHAKE_TIMEOUT_MS
        while (System.currentTimeMillis() < deadline) {
            if (xrayProcess?.isAlive == false) return false
            val open = runCatching {
                java.net.Socket().use { socket ->
                    socket.connect(java.net.InetSocketAddress("127.0.0.1", SOCKS_PORT), 500)
                    true
                }
            }.getOrDefault(false)
            if (open) return true
            Thread.sleep(300)
        }
        return false
    }

    fun disconnect(serverHost: String = "") {
        if (!isWindows) return
        if (serverHost.isNotBlank() || isUp()) {
            runElevated(downScript(serverHost.ifBlank { "0.0.0.0" }), waitSeconds = 30)
        }
        stopXray()
    }

    fun isUp(): Boolean = xrayProcess?.isAlive == true

    /**
     * Признак жизни: адаптер на месте и процесс жив.
     *
     * Байты через SOCKS не считаем — их у xray не спросишь без отдельного
     * api-порта, а поднимать его ради счётчика значит открыть ещё один вход.
     */
    fun isHealthy(): Boolean {
        if (!isUp()) return false
        return runCatching {
            java.net.NetworkInterface.getNetworkInterfaces().toList().any {
                it.name.equals(ADAPTER, ignoreCase = true) ||
                    it.displayName.orEmpty().contains(ADAPTER, ignoreCase = true)
            }
        }.getOrDefault(false)
    }
}
