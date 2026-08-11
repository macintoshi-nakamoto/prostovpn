package com.prostovpn.desktop

import java.io.File
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.TimeUnit

/**
 * Реальный VPN-туннель на Windows.
 *
 * Движок — наш собственный `prostovpn-tunnel.exe` (каталог `windows/tunnel`):
 * он поднимает адаптер Wintun, регистрирует службу `ProstoVPNTunnel$prostovpn`
 * и пишет журнал. Отдельный клиент Amnezia не нужен и не используется.
 *
 * Права администратора нужны один раз — на подключение: создать службу и
 * загрузить драйвер обычный пользователь не может. Отключение идёт без UAC:
 * служба сама слушает событие остановки.
 */
class WindowsTunnel {

    /** Что пошло не так — для показа пользователю понятным текстом. */
    sealed class Result {
        data object Success : Result()
        data class Failure(
            val reason: Reason,
            val detail: String = "",
            val diag: HandshakeDiag? = null,
        ) : Result()
    }

    /**
     * Почему не состоялось рукопожатие — по журналу движка.
     *
     * «Сервер не отвечает» — это четыре разные беды с разным лечением,
     * и без журнала они неотличимы друг от друга.
     */
    enum class HandshakeDiag {
        /** Ни одного пакета в ответ: сервер выключен или сеть блокирует. */
        SILENCE,

        /** Пришёл ICMP «порт закрыт»: машина жива, VPN на порту не слушает. */
        PORT_CLOSED,

        /** Ответы приходят, но заголовок не распознан: маскировка не совпадает. */
        HEADER_MISMATCH,

        /** Ответы распознаны, но не проходят криптопроверку: ключ не от сервера. */
        REJECTED,

        /**
         * Больше не выставляется: с тех пор как WgConfig всегда дописывает
         * `KillSwitch = off`, блокирующие правила не взводятся вовсе и такое
         * молчание неотличимо от [SILENCE]. Значение оставлено, пока его
         * разбирают AppState и Loc; удалять — вместе с ними.
         */
        KILLSWITCH,

        /**
         * Windows не дал движку исходящий адаптер и он ушёл в «чёрную дыру»:
         * пакеты не покидают машину вообще.
         */
        BLACKHOLE,
    }

    enum class Reason {
        /** Движок туннеля не найден рядом с приложением. */
        NoBackend,

        /** Пользователь отклонил запрос прав администратора. */
        ElevationDenied,

        /** Служба не поднялась: неверный конфиг, занятый адаптер, блокировка. */
        TunnelFailed,

        /**
         * Адрес туннеля уже занят другим работающим VPN — Windows не отдаёт
         * один адрес двум адаптерам. В [Result.Failure.detail] имя виновника.
         */
        AddressInUse,

        /** Туннель поднят, но сервер не отвечает на рукопожатие. */
        NoHandshake,

        /** Не Windows. */
        UnsupportedOs,
    }

    companion object {
        const val TUNNEL_NAME = "prostovpn"

        private const val ENGINE = "prostovpn-tunnel.exe"

        val isWindows: Boolean =
            System.getProperty("os.name").orEmpty().startsWith("Windows", ignoreCase = true)

        /** Каталог для конфига и журналов: %LOCALAPPDATA%\ProstoVPN. */
        fun dataDir(): File {
            val base = System.getenv("LOCALAPPDATA")
                ?: System.getProperty("user.home")
            return File(base, "ProstoVPN").apply { mkdirs() }
        }

        /**
         * Ищем движок: jpackage кладёт содержимое appResourcesRootDir
         * в <install>\app\ и отдаёт путь системным свойством. Рядом с jar —
         * запасной вариант для запуска из исходников.
         */
        fun findBackend(): File? {
            val candidates = mutableListOf<File>()

            System.getProperty("compose.application.resources.dir")?.let { dir ->
                candidates += File(dir, ENGINE)
            }
            runCatching {
                val here = File(
                    WindowsTunnel::class.java.protectionDomain.codeSource.location.toURI()
                ).parentFile
                candidates += File(here, ENGINE)
                candidates += File(here.parentFile, "app\\$ENGINE")
            }
            // Запуск из исходников: собранный движок лежит в ресурсах проекта
            candidates += File("resources/windows/$ENGINE")
            candidates += File("windows/resources/windows/$ENGINE")

            return candidates.firstOrNull { it.isFile }
        }
    }

    /**
     * Что движок сообщает о живом туннеле.
     *
     * [handshakeAt] — время последнего рукопожатия (unix-секунды), 0 —
     * сервер ещё ни разу не ответил.
     */
    data class Live(val handshakeAt: Long, val rx: Long, val tx: Long, val updatedAt: Long) {
        /** Рукопожатие есть и не протухло: WireGuard обновляет его чаще двух минут. */
        fun isHealthy(staleSeconds: Long = 180): Boolean =
            handshakeAt > 0 && (System.currentTimeMillis() / 1000 - handshakeAt) < staleSeconds
    }

    private var backend: File? = null

    /** Служба туннеля запущена? */
    fun isUp(): Boolean = state() == "RUNNING"

    /**
     * Состояние живого туннеля; null — движок его ещё не выложил.
     * Файл пишет служба: приложению управляющий канал движка недоступен.
     */
    fun live(): Live? {
        val file = File(dataDir(), "state.txt")
        if (!file.isFile) return null
        val values = runCatching {
            file.readLines().mapNotNull { line ->
                val (key, value) = line.split('=', limit = 2).takeIf { it.size == 2 } ?: return@mapNotNull null
                key.trim() to (value.trim().toLongOrNull() ?: return@mapNotNull null)
            }.toMap()
        }.getOrNull() ?: return null

        return Live(
            handshakeAt = values["handshake"] ?: return null,
            rx = values["rx"] ?: 0,
            tx = values["tx"] ?: 0,
            updatedAt = values["updated"] ?: 0,
        )
    }

    /** Туннель поднят и сервер отвечает. */
    fun isHealthy(): Boolean = isUp() && live()?.isHealthy() == true

    /**
     * Поднимает туннель по конфигу AmneziaWG/WireGuard.
     * Блокирующий вызов — запускать вне UI-потока.
     */
    fun connect(configText: String): Result {
        if (!isWindows) {
            return Result.Failure(Reason.UnsupportedOs, "Туннель поддерживается только на Windows")
        }

        val exe = findBackend() ?: return Result.Failure(Reason.NoBackend)
        backend = exe

        /*
        Ключ задаёт клиенту фиксированный адрес. Если тем же ключом уже поднят
        другой VPN, адрес занят его адаптером, и служба всё равно умрёт с
        «The object already exists». Ловим это до UAC: незачем спрашивать
        права ради заведомо провального запуска.
        */
        AdapterConflict.holderOf(configText)?.let { holder ->
            return Result.Failure(Reason.AddressInUse, holder)
        }

        // Имя файла задаёт имя туннеля и имя службы — менять нельзя.
        val configFile = File(dataDir(), "$TUNNEL_NAME.conf")

        /*
        Прошлый туннель обязан быть снят до старта нового. Конфиг у нас один
        файл на все подключения, а движок на «/start» уже запущенной службы
        просто возвращает 0, ничего не перезапуская: служба продолжает жить
        со своим прежним конфигом — прежняя страна, возможно уже отозванный
        ключ. Её же свежее рукопожатие в state.txt мы приняли бы за своё и
        отрапортовали «подключено», хотя сменить сервер не удалось.
        */
        var forceInstall = false
        if (state() !in setOf("ABSENT", "STOPPED")) {
            if (!disconnect()) {
                /*
                Служба жива и не снимается — «/start» на ней бесполезен.
                Идём сразу в установку с правами: она снимет и пересоздаст
                службу, и та прочитает уже новый конфиг.
                */
                forceInstall = true
            }
        }

        runCatching { configFile.writeText(configText.normalizeNewlines()) }
            .getOrElse { return Result.Failure(Reason.TunnelFailed, "Не удалось записать конфиг: ${it.message}") }

        // Прошлую службу движок снимает сам — второй запрос UAC не нужен.
        val report = File(dataDir(), "install.log")
        report.delete()
        File(dataDir(), "tunnel.log").delete()
        // Чужое состояние от прошлого подключения приняли бы за своё. Чистим
        // только после снятия прошлого туннеля: живая служба переписывает
        // этот файл каждые 400 мс и тут же воскресила бы его.
        File(dataDir(), "state.txt").delete()

        /*
        Служба туннеля остаётся в системе между подключениями, а право её
        запускать выдано тому, кто сидит за машиной. Поэтому обычное
        подключение — это просто старт службы, без запроса прав.

        Права нужны, только когда службы ещё нет, она от прошлой сборки или
        не снялась выше: тогда ставим заново. Так UAC остаётся ровно на первом
        подключении и после обновления приложения.

        45 секунд на «/start»: диспетчер служб ждёт запуска до 30 секунд
        (ServicesPipeTimeout), и более короткий таймаут рвал бы штатно долгий
        первый старт.
        */
        if (forceInstall || run(exe, "/start", configFile.absolutePath, timeoutSeconds = 45) == null) {
            // 60 секунд: на чистой машине первое подключение ещё ставит драйвер Wintun
            val install = runElevated(
                exe,
                listOf("/installtunnelservice", configFile.absolutePath, report.absolutePath),
                waitSeconds = 60,
            )
            if (install == ElevationResult.Denied) {
                return Result.Failure(Reason.ElevationDenied)
            }
        }

        /*
        90 секунд, а не 20: движок ставит службу и сразу выходит, не дожидаясь
        RUNNING, а первое подключение на чистой машине ещё грузит драйвер
        Wintun и резолвит имя сервера. С коротким окном мы отказывались,
        пока служба честно стартовала, — через пару секунд она доходила до
        RUNNING и забирала весь трафик под надписью «отключено».
        */
        val deadline = System.currentTimeMillis() + 90_000
        var running = false
        while (!running && System.currentTimeMillis() < deadline) {
            when (state()) {
                "RUNNING" -> running = true
                // Служба стартовала и сразу умерла либо не создалась вовсе
                "STOPPED", "ABSENT" -> return Result.Failure(Reason.TunnelFailed, lastTunnelError())
                else -> Thread.sleep(400)
            }
        }
        if (!running) {
            // Бросать стартующую службу нельзя: она дойдёт до RUNNING уже
            // после нашего отказа. Снимаем — и честно говорим, если не вышло.
            val down = disconnect()
            return Result.Failure(
                Reason.TunnelFailed,
                listOfNotNull(
                    lastTunnelError().takeIf { it.isNotBlank() },
                    "туннель не снялся — адаптер может забирать трафик".takeIf { !down },
                ).joinToString(" · "),
            )
        }

        /*
        Служба поднялась — но это ещё не связь. Адаптер и маршруты уже стоят,
        и если сервер не ответит, весь трафик уйдёт в мёртвый туннель: со
        стороны это выглядит как «подключено, а интернета нет». Поэтому ждём
        рукопожатие, а не дождавшись — снимаем туннель, чтобы вернуть сеть.
        */
        val handshakeDeadline = System.currentTimeMillis() + 20_000
        while (System.currentTimeMillis() < handshakeDeadline) {
            if (live()?.handshakeAt?.let { it > 0 } == true) return Result.Success
            if (state() != "RUNNING") {
                return Result.Failure(Reason.TunnelFailed, lastTunnelError())
            }
            Thread.sleep(500)
        }

        if (!disconnect()) {
            /*
            Живой адаптер важнее диагноза молчащего сервера: текст отказа для
            NoHandshake собирается по diag и про неснятый туннель промолчал бы,
            а человек тем временем сидит с трафиком в мёртвом VPN.
            */
            return Result.Failure(
                Reason.TunnelFailed,
                "рукопожатия нет, и туннель не снялся — адаптер может забирать трафик",
            )
        }
        return Result.Failure(Reason.NoHandshake, diag = classifyHandshakeFailure())
    }

    /**
     * Ставит диагноз по журналу движка после неудачного рукопожатия.
     *
     * Журнал выкладывает служба при остановке — она только что остановлена
     * из [disconnect], поэтому файл дожидаемся с небольшим запасом.
     */
    private fun classifyHandshakeFailure(): HandshakeDiag? {
        val logFile = File(dataDir(), "tunnel.log")
        var log: String? = null
        repeat(12) {
            log = logFile.takeIf { it.isFile }?.readTextSafely()
            if (log != null) return@repeat
            Thread.sleep(300)
        }
        val text = log ?: return null

        return when {
            /*
            Движок сам сообщает, что остался без исходящего адаптера. Так
            бывает, когда маршрут по умолчанию уводит в сам туннель: тогда
            сокет привязывается к «чёрной дыре» и наружу не уходит ничего.
            Проверяем первым — иначе это выглядит как молчащий сервер.

            Только про IPv4: без IPv6 наружу движок штатно глушит v6-сокет
            («Binding v6 socket to interface 0 (blackhole=true)»), и это не
            беда, а норма. Раньше проверка ловила именно эту строку и ставила
            ложный диагноз на каждом обычном отказе.
            */
            BLACKHOLE_V4.containsMatchIn(text) -> HandshakeDiag.BLACKHOLE

            // Ответы дошли, но не прошли криптопроверку — ключ не подходит
            listOf("invalid mac1", "invalid response message", "invalid initiation message")
                .any { text.contains(it, ignoreCase = true) } -> HandshakeDiag.REJECTED

            // Пакеты приходят, но заголовок не наш — маскировка не совпадает
            text.contains("Received message with unknown type", ignoreCase = true) ->
                HandshakeDiag.HEADER_MISMATCH

            // Windows превращает ICMP «порт недоступен» в ошибку чтения сокета
            listOf("forcibly closed", "connection reset", "refused")
                .any { text.contains(it, ignoreCase = true) } -> HandshakeDiag.PORT_CLOSED

            // Инициации уходили, ответа не было ни одного
            text.contains("Sending handshake initiation") -> HandshakeDiag.SILENCE

            else -> null
        }
    }

    /**
     * Настоящая причина отказа: отчёт установки пишет наш повышенный процесс,
     * журнал туннеля выкладывает сама служба (кольцевой журнал движка лежит
     * там, куда пускают только SYSTEM и администраторов).
     */
    private fun lastTunnelError(): String {
        val tunnelLog = File(dataDir(), "tunnel.log").takeIf { it.isFile }?.readTextSafely()
        val installLog = File(dataDir(), "install.log").takeIf { it.isFile }?.readTextSafely()

        // Строка «РЕЗУЛЬТАТ: ОШИБКА — …» из отчёта установки самая точная
        installLog?.lineSequence()
            ?.map { it.trim() }
            ?.lastOrNull { it.startsWith("РЕЗУЛЬТАТ: ОШИБКА") }
            ?.let { return it.substringAfter("— ").take(200) }

        val meaningful = tunnelLog
            ?.lineSequence()
            ?.map { it.trim() }
            ?.filter { it.isNotEmpty() }
            ?.lastOrNull { line ->
                listOf("error", "invalid", "must", "unable", "failed", "cannot", "ошибка")
                    .any { line.contains(it, ignoreCase = true) }
            }
        return meaningful?.substringAfterLast("] ")?.take(200).orEmpty()
    }

    /**
     * Снимает туннель. Возвращается, только когда он действительно снят.
     *
     * Вся работа — один вызов движка: он останавливает службу, дожидается
     * исчезновения адаптера и чистит кэш DNS. Прав не требует.
     *
     * Раньше здесь была цепочка запусков — спросить состояние, послать
     * сигнал, снова спросить, — и всё это время приложение уже показывало
     * «отключено», хотя адаптер жил и уводил трафик в VPN.
     *
     * Ждём именно исчезновения адаптера, а не остановки службы: маршруты
     * снимаются вместе с ним, и до этого момента трафик идёт в туннель.
     *
     * @return снят ли туннель на самом деле
     */
    fun disconnect(): Boolean {
        if (!isWindows) return true
        val exe = backend ?: findBackend() ?: return false

        if (run(exe, "/down", TUNNEL_NAME, timeoutSeconds = 30) != null) return true

        /*
        Не снялся сам. Висящий туннель держит адаптер и маршруты — это
        хуже запроса прав, поэтому сносим службу принудительно.
        */
        runElevated(exe, listOf("/uninstalltunnelservice", TUNNEL_NAME), waitSeconds = 20)
        return state() in setOf("ABSENT", "STOPPED")
    }

    // --- Служебное ---

    private enum class ElevationResult { Ok, Denied, Error }

    /**
     * Запускает движок с правами администратора.
     *
     * Поднять права внутри JVM нельзя — UAC срабатывает только через
     * ShellExecuteEx с глаголом runas, поэтому идём через PowerShell.
     * Отказ пользователя в UAC приходит исключением Win32 с кодом 1223
     * (ERROR_CANCELLED), а не кодом возврата процесса, поэтому ловим его
     * явно. Скрипт передаём base64 (-EncodedCommand): так пути с пробелами
     * и кириллицей не ломаются о двойное экранирование.
     */
    private fun runElevated(exe: File, args: List<String>, waitSeconds: Long): ElevationResult {
        fun psQuote(value: String) = "'" + value.replace("'", "''") + "'"
        val argList = args.joinToString(",") { psQuote(it) }

        // Отказ в UAC приходит как Win32Exception, но PowerShell 5.1 при
        // ErrorActionPreference=Stop заворачивает её в ActionPreferenceStop-
        // Exception — поэтому разворачиваем цепочку InnerException, иначе
        // отказ пользователя выглядел бы как «туннель не поднялся».
        val script = """
            ${'$'}ErrorActionPreference = 'Stop'
            try {
                ${'$'}p = Start-Process -FilePath ${psQuote(exe.absolutePath)} -ArgumentList $argList -Verb RunAs -WindowStyle Hidden -Wait -PassThru
                exit ${'$'}p.ExitCode
            } catch {
                ${'$'}e = ${'$'}_.Exception
                while (${'$'}e -ne ${'$'}null -and -not (${'$'}e -is [System.ComponentModel.Win32Exception])) {
                    ${'$'}e = ${'$'}e.InnerException
                }
                if (${'$'}e -is [System.ComponentModel.Win32Exception]) { exit ${'$'}e.NativeErrorCode }
                exit $GENERIC_FAILURE
            }
        """.trimIndent()

        val encoded = java.util.Base64.getEncoder()
            .encodeToString(script.toByteArray(Charsets.UTF_16LE))

        return runCatching {
            val process = ProcessBuilder(
                "powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded,
            ).redirectErrorStream(true).start()

            if (!process.waitFor(waitSeconds, TimeUnit.SECONDS)) {
                process.destroyForcibly()
                return ElevationResult.Error
            }
            when (process.exitValue()) {
                0 -> ElevationResult.Ok
                ERROR_CANCELLED -> ElevationResult.Denied
                else -> ElevationResult.Error
            }
        }.getOrDefault(ElevationResult.Error)
    }

    /**
     * Состояние службы: RUNNING / STARTING / STOPPED / ABSENT.
     *
     * Спрашиваем движок, а не PowerShell: `sc query` печатает локализованные
     * подписи, а запуск PowerShell на каждый опрос — лишние сотни миллисекунд.
     */
    private fun state(): String {
        if (!isWindows) return "ABSENT"
        val exe = backend ?: findBackend() ?: return "ABSENT"
        return run(exe, "/status", TUNNEL_NAME)?.trim()?.uppercase() ?: "ABSENT"
    }

    /** Запуск движка без повышения прав; null — не удалось выполнить. */
    private fun run(exe: File, vararg args: String, timeoutSeconds: Long = 15): String? = runCatching {
        val process = ProcessBuilder(listOf(exe.absolutePath) + args)
            .redirectErrorStream(true)
            .start()
        try {
            /*
            Вывод сливаем параллельно ожиданию, отдельным потоком. Читать его
            до waitFor нельзя: readText() возвращается только когда движок
            закроет stdout, поэтому зависший «/down» держал бы нас вечно —
            таймаут ниже до destroyForcibly просто не доходил. Просто не читать
            тоже нельзя: движок уснёт на записи в заполненный буфер пайпа.
            */
            val output = ArrayBlockingQueue<String>(1)
            Thread {
                runCatching { process.inputStream.bufferedReader().use { output.put(it.readText()) } }
            }.apply { isDaemon = true }.start()

            if (!process.waitFor(timeoutSeconds, TimeUnit.SECONDS)) {
                process.destroyForcibly()
                return null
            }
            // stdout закрыт вместе с процессом, так что поток уже дочитывает;
            // запас нужен только на то, чтобы он успел отдать результат.
            val text = output.poll(2, TimeUnit.SECONDS) ?: return null
            if (process.exitValue() != 0) null else text
        } finally {
            // Исключение при чтении раньше глотал runCatching, а процесс
            // оставался висеть — некому было его снять.
            if (process.isAlive) process.destroyForcibly()
        }
    }.getOrNull()
}

/**
 * «Чёрная дыра» именно на IPv4-сокете. Глушение IPv6 — штатное поведение
 * на сетях без IPv6 и о неисправности не говорит.
 */
private val BLACKHOLE_V4 = Regex("""Binding v4 socket to interface \d+ \(blackhole=true\)""")

/** Win32 ERROR_CANCELLED — пользователь отклонил запрос UAC. */
private const val ERROR_CANCELLED = 1223

/** Наш код для «сорвалось не из-за Windows» — не пересекается с кодами Win32. */
private const val GENERIC_FAILURE = 9009

/** Windows-служба туннеля требует CRLF и завершающего перевода строки. */
private fun String.normalizeNewlines(): String =
    replace("\r\n", "\n").trimEnd().replace("\n", "\r\n") + "\r\n"

private fun File.readTextSafely(): String? = runCatching { readText() }.getOrNull()
