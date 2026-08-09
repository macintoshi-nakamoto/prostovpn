package com.prostovpn.desktop

import java.io.File
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

        // Имя файла задаёт имя туннеля и имя службы — менять нельзя.
        val configFile = File(dataDir(), "$TUNNEL_NAME.conf")
        runCatching { configFile.writeText(configText.normalizeNewlines()) }
            .getOrElse { return Result.Failure(Reason.TunnelFailed, "Не удалось записать конфиг: ${it.message}") }

        // Прошлую службу движок снимает сам — второй запрос UAC не нужен.
        val report = File(dataDir(), "install.log")
        report.delete()
        File(dataDir(), "tunnel.log").delete()
        // Чужое состояние от прошлого подключения приняли бы за своё
        File(dataDir(), "state.txt").delete()

        // 60 секунд: на чистой машине первое подключение ещё ставит драйвер Wintun
        val install = runElevated(
            exe,
            listOf("/installtunnelservice", configFile.absolutePath, report.absolutePath),
            waitSeconds = 60,
        )
        if (install == ElevationResult.Denied) {
            return Result.Failure(Reason.ElevationDenied)
        }

        val deadline = System.currentTimeMillis() + 20_000
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
            return Result.Failure(Reason.TunnelFailed, lastTunnelError())
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

        disconnect()
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
            */
            text.contains("blackhole=true", ignoreCase = true) -> HandshakeDiag.BLACKHOLE

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
     * Снимает туннель. Блокирующий вызов.
     *
     * Сначала просим службу остановиться сама — это не требует прав и не
     * дёргает UAC. Мёртвую (остановленную) службу удалит следующее
     * подключение. Если событие не сработало, снимаем с повышением прав.
     */
    fun disconnect() {
        if (!isWindows) return
        val exe = backend ?: findBackend() ?: return
        // Службы нет или она уже мертва — снимет следующее подключение,
        // ради этого не стоит показывать запрос прав.
        if (state() in setOf("ABSENT", "STOPPED")) return

        if (run(exe, "/stop", TUNNEL_NAME) != null) {
            val deadline = System.currentTimeMillis() + 8_000
            while (System.currentTimeMillis() < deadline) {
                val current = state()
                if (current == "STOPPED" || current == "ABSENT") return
                Thread.sleep(300)
            }
        }

        runElevated(exe, listOf("/uninstalltunnelservice", TUNNEL_NAME), waitSeconds = 20)
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
    private fun run(exe: File, vararg args: String): String? = runCatching {
        val process = ProcessBuilder(listOf(exe.absolutePath) + args)
            .redirectErrorStream(true)
            .start()
        val output = process.inputStream.bufferedReader().use { it.readText() }
        if (!process.waitFor(15, TimeUnit.SECONDS)) {
            process.destroyForcibly()
            return null
        }
        if (process.exitValue() != 0) null else output
    }.getOrNull()
}

/** Win32 ERROR_CANCELLED — пользователь отклонил запрос UAC. */
private const val ERROR_CANCELLED = 1223

/** Наш код для «сорвалось не из-за Windows» — не пересекается с кодами Win32. */
private const val GENERIC_FAILURE = 9009

/** Windows-служба туннеля требует CRLF и завершающего перевода строки. */
private fun String.normalizeNewlines(): String =
    replace("\r\n", "\n").trimEnd().replace("\n", "\r\n") + "\r\n"

private fun File.readTextSafely(): String? = runCatching { readText() }.getOrNull()
