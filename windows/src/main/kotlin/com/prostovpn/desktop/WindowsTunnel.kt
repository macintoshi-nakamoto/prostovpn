package com.prostovpn.desktop

import java.io.File
import java.util.concurrent.TimeUnit

/**
 * Реальный VPN-туннель на Windows.
 *
 * AmneziaWG для Windows — форк wireguard-windows и повторяет его контракт:
 * `amneziawg.exe /installtunnelservice <config.conf>` ставит и запускает
 * службу туннеля, `/uninstalltunnelservice <name>` — снимает её. Служба
 * требует прав администратора, поэтому команда запускается с повышением
 * (UAC), а состояние читается через PowerShell Get-Service — вывод `sc query`
 * локализован и на русской Windows не разбирается.
 */
class WindowsTunnel {

    /** Что пошло не так — для показа пользователю понятным текстом. */
    sealed class Result {
        data object Success : Result()
        data class Failure(val reason: Reason, val detail: String = "") : Result()
    }

    enum class Reason {
        /** Не нашли amneziawg.exe / wireguard.exe ни в поставке, ни в системе. */
        NoBackend,

        /** Пользователь отклонил запрос прав администратора. */
        ElevationDenied,

        /** Служба не поднялась: неверный конфиг, занятый адаптер, блокировка. */
        TunnelFailed,

        /** Не Windows. */
        UnsupportedOs,
    }

    companion object {
        const val TUNNEL_NAME = "prostovpn"

        val isWindows: Boolean =
            System.getProperty("os.name").orEmpty().startsWith("Windows", ignoreCase = true)

        /** Каталог для конфига: %LOCALAPPDATA%\ProstoVPN (или ~/.prostovpn). */
        private fun dataDir(): File {
            val base = System.getenv("LOCALAPPDATA")
                ?: System.getProperty("user.home")
            return File(base, "ProstoVPN").apply { mkdirs() }
        }

        /**
         * Ищем бинарь туннеля: сначала рядом с приложением (jpackage кладёт
         * ресурсы в <install>\app\), затем в стандартных местах установки
         * AmneziaWG и WireGuard.
         */
        fun findBackend(): File? {
            val candidates = mutableListOf<File>()

            // Положенный рядом с приложением: jpackage кладёт содержимое
            // appResourcesRootDir в <install>\app\ и отдаёт путь этим свойством
            System.getProperty("compose.application.resources.dir")?.let { dir ->
                candidates += File(dir, "amneziawg.exe")
            }
            // Рядом с jar — на случай запуска из исходников
            runCatching {
                val here = File(
                    WindowsTunnel::class.java.protectionDomain.codeSource.location.toURI()
                ).parentFile
                candidates += File(here, "amneziawg.exe")
                candidates += File(here.parentFile, "app\\amneziawg.exe")
            }

            // Установленный отдельно официальный клиент AmneziaWG
            val programFiles = System.getenv("ProgramFiles") ?: "C:\\Program Files"
            candidates += File(programFiles, "AmneziaWG\\amneziawg.exe")

            return candidates.firstOrNull { it.isFile }
        }

        /**
         * Имя службы туннеля: amneziawg.exe собирает его из имени conf-файла
         * без расширения — `AmneziaWGTunnel$<имя>`.
         */
        private fun serviceName(): String = "AmneziaWGTunnel\$$TUNNEL_NAME"
    }

    private var backend: File? = null

    /** Служба туннеля запущена? */
    fun isUp(): Boolean = queryServiceState(serviceName()) == "RUNNING"

    /**
     * Поднимает туннель по конфигу AmneziaWG/WireGuard.
     * Блокирующий вызов — запускать вне UI-потока.
     */
    fun connect(configText: String): Result {
        if (!isWindows) {
            return Result.Failure(Reason.UnsupportedOs, "Туннель поддерживается только на Windows")
        }

        val exe = findBackend()
            ?: return Result.Failure(Reason.NoBackend)
        backend = exe

        // Файл конфигурации должен называться так же, как туннель:
        // именно из имени файла служба берёт имя туннеля.
        val configFile = File(dataDir(), "$TUNNEL_NAME.conf")
        runCatching { configFile.writeText(configText.normalizeNewlines()) }
            .getOrElse { return Result.Failure(Reason.TunnelFailed, "Не удалось записать конфиг: ${it.message}") }

        // Снимаем прошлую службу — но только если она есть. amneziawg.exe
        // собран как оконное приложение и на попытку снять несуществующую
        // службу показывает модальное окно с ошибкой, которое ждёт клика,
        // да ещё и просит права зря.
        if (queryServiceState(serviceName()) != null) {
            runElevated(exe, listOf("/uninstalltunnelservice", TUNNEL_NAME), waitSeconds = 15)
        }

        // 60 секунд: на чистой машине первое подключение ещё ставит драйвер Wintun
        val install = runElevated(
            exe,
            listOf("/installtunnelservice", configFile.absolutePath),
            waitSeconds = 60,
        )
        if (install == ElevationResult.Denied) {
            return Result.Failure(Reason.ElevationDenied)
        }
        // Ненулевой код здесь не означает провал: Start-Process -Verb RunAs
        // умеет возвращать ошибку в сеансах, где туннель всё же поднялся.
        // Верим только состоянию службы.

        val service = serviceName()
        val deadline = System.currentTimeMillis() + 20_000
        while (System.currentTimeMillis() < deadline) {
            when (queryServiceState(service)) {
                "RUNNING" -> return Result.Success
                "STOPPED" -> {
                    // Служба стартовала и сразу умерла — конфиг не принят
                    return Result.Failure(Reason.TunnelFailed, lastTunnelError(exe))
                }
            }
            Thread.sleep(400)
        }
        return Result.Failure(Reason.TunnelFailed, lastTunnelError(exe))
    }

    /**
     * Достаёт настоящую причину падения из журнала туннеля (`/dumplog`) —
     * без неё все отказы выглядят одинаково. Журнал целиком кладём рядом
     * с конфигом, наружу отдаём последнюю содержательную строку.
     */
    private fun lastTunnelError(exe: File): String {
        val log = runCatching {
            val process = ProcessBuilder(exe.absolutePath, "/dumplog")
                .redirectErrorStream(true)
                .start()
            val output = process.inputStream.bufferedReader().use { it.readText() }
            process.waitFor(15, TimeUnit.SECONDS)
            output
        }.getOrNull()

        if (log.isNullOrBlank()) return ""

        runCatching { File(dataDir(), "last-error.log").writeText(log) }

        // Ищем строку с описанием ошибки разбора или запуска
        val meaningful = log.lineSequence()
            .map { it.trim() }
            .filter { it.isNotEmpty() }
            .lastOrNull { line ->
                listOf("error", "invalid", "must", "unable", "failed", "cannot")
                    .any { line.contains(it, ignoreCase = true) }
            }
        return meaningful?.substringAfterLast("] ")?.take(160).orEmpty()
    }

    /** Снимает туннель. Блокирующий вызов. */
    fun disconnect() {
        if (!isWindows) return
        val exe = backend ?: findBackend() ?: return
        // Службы нет — ничего не делаем: иначе всплывёт модальная ошибка
        if (queryServiceState(serviceName()) == null) return
        runElevated(exe, listOf("/uninstalltunnelservice", TUNNEL_NAME), waitSeconds = 15)
    }

    // --- Служебное ---

    private enum class ElevationResult { Ok, Denied, Error }

    /**
     * Запускает бинарь с правами администратора.
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
     * Состояние службы: RUNNING / STOPPED / null (службы нет).
     *
     * Берём из PowerShell, а не из `sc query`: тот печатает
     * локализованные подписи (на русской Windows — «РАБОТАЕТ»),
     * а Get-Service отдаёт значение перечисления .NET на английском.
     */
    private fun queryServiceState(service: String): String? = runCatching {
        val script =
            "(Get-Service -Name '${service.replace("'", "''")}' -ErrorAction SilentlyContinue).Status"
        val encoded = java.util.Base64.getEncoder()
            .encodeToString(script.toByteArray(Charsets.UTF_16LE))

        val process = ProcessBuilder(
            "powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded,
        ).redirectErrorStream(true).start()

        val output = process.inputStream.bufferedReader().use { it.readText() }.trim()
        process.waitFor(10, TimeUnit.SECONDS)

        when {
            output.equals("Running", ignoreCase = true) -> "RUNNING"
            output.equals("Stopped", ignoreCase = true) -> "STOPPED"
            output.equals("StartPending", ignoreCase = true) -> "START_PENDING"
            else -> null
        }
    }.getOrNull()
}

/** Win32 ERROR_CANCELLED — пользователь отклонил запрос UAC. */
private const val ERROR_CANCELLED = 1223

/** Наш код для «сорвалось не из-за Windows» — не пересекается с кодами Win32. */
private const val GENERIC_FAILURE = 9009

/** Windows-служба туннеля требует CRLF и завершающего перевода строки. */
private fun String.normalizeNewlines(): String =
    replace("\r\n", "\n").trimEnd().replace("\n", "\r\n") + "\r\n"
