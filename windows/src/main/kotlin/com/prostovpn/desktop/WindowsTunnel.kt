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
 * (UAC), а состояние читается через `sc query`.
 *
 * Обычный WireGuard-конфиг (без обфускации Amnezia) поддерживается тем же
 * способом через wireguard.exe, если он установлен.
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
    fun isUp(): Boolean {
        val exe = backend ?: findBackend() ?: return false
        return queryServiceState(serviceName()) == "RUNNING"
    }

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

        // Снимаем прошлую службу, если осталась с прошлого запуска
        runElevated(exe, listOf("/uninstalltunnelservice", TUNNEL_NAME), waitSeconds = 10)

        val install = runElevated(
            exe,
            listOf("/installtunnelservice", configFile.absolutePath),
            waitSeconds = 30,
        )
        if (install == ElevationResult.Denied) {
            return Result.Failure(Reason.ElevationDenied)
        }

        // Служба поднимается асинхронно — ждём появления RUNNING
        val service = serviceName()
        val deadline = System.currentTimeMillis() + 15_000
        while (System.currentTimeMillis() < deadline) {
            when (queryServiceState(service)) {
                "RUNNING" -> return Result.Success
                "STOPPED" -> {
                    // служба стартовала и сразу умерла — конфиг не принят
                    return Result.Failure(Reason.TunnelFailed, "Служба туннеля остановилась")
                }
            }
            Thread.sleep(400)
        }
        return Result.Failure(Reason.TunnelFailed, "Туннель не поднялся за 15 секунд")
    }

    /** Снимает туннель. Блокирующий вызов. */
    fun disconnect() {
        if (!isWindows) return
        val exe = backend ?: findBackend() ?: return
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

        val script = """
            ${'$'}ErrorActionPreference = 'Stop'
            try {
                ${'$'}p = Start-Process -FilePath ${psQuote(exe.absolutePath)} -ArgumentList $argList -Verb RunAs -Wait -PassThru
                exit ${'$'}p.ExitCode
            } catch [System.ComponentModel.Win32Exception] {
                exit ${'$'}_.Exception.NativeErrorCode
            } catch {
                exit 1
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

/** Windows-служба туннеля требует CRLF и завершающего перевода строки. */
private fun String.normalizeNewlines(): String =
    replace("\r\n", "\n").trimEnd().replace("\n", "\r\n") + "\r\n"
