package com.prostovpn.desktop

import java.io.File
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.TimeUnit

class WindowsTunnel {
    sealed class Result {
        data object Success : Result()
        data class Failure(
            val reason: Reason,
            val detail: String = "",
            val diag: HandshakeDiag? = null,
        ) : Result()
    }

    enum class HandshakeDiag {
        SILENCE,

        PORT_CLOSED,

        HEADER_MISMATCH,

        REJECTED,

        KILLSWITCH,

        BLACKHOLE,
    }

    enum class Reason {
        NoBackend,

        ElevationDenied,

        TunnelFailed,

        AddressInUse,

        NoHandshake,

        UnsupportedOs,
    }

    companion object {
        const val TUNNEL_NAME = "prostovpn"

        private const val ENGINE = "prostovpn-tunnel.exe"

        val isWindows: Boolean =
            System.getProperty("os.name").orEmpty().startsWith("Windows", ignoreCase = true)

        fun dataDir(): File {
            val base = System.getenv("LOCALAPPDATA")
                ?: System.getProperty("user.home")
            return File(base, "ProstoVPN").apply { mkdirs() }
        }

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

            candidates += File("resources/windows/$ENGINE")
            candidates += File("windows/resources/windows/$ENGINE")

            return candidates.firstOrNull { it.isFile }
        }
    }

    data class Live(val handshakeAt: Long, val rx: Long, val tx: Long, val updatedAt: Long) {
        fun isHealthy(staleSeconds: Long = 180): Boolean =
            handshakeAt > 0 && (System.currentTimeMillis() / 1000 - handshakeAt) < staleSeconds
    }

    private var backend: File? = null

    fun isUp(): Boolean = state() == "RUNNING"

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

    fun isHealthy(): Boolean = isUp() && live()?.isHealthy() == true

    fun connect(configText: String): Result {
        if (!isWindows) {
            return Result.Failure(Reason.UnsupportedOs, "Туннель поддерживается только на Windows")
        }

        val exe = findBackend() ?: return Result.Failure(Reason.NoBackend)
        backend = exe

        AdapterConflict.holderOf(configText)?.let { holder ->
            return Result.Failure(Reason.AddressInUse, holder)
        }

        val configFile = File(dataDir(), "$TUNNEL_NAME.conf")

        var forceInstall = false
        if (state() !in setOf("ABSENT", "STOPPED")) {
            if (!disconnect()) {
                forceInstall = true
            }
        }

        runCatching { configFile.writeText(configText.normalizeNewlines()) }
            .getOrElse { return Result.Failure(Reason.TunnelFailed, "Не удалось записать конфиг: ${it.message}") }

        val report = File(dataDir(), "install.log")
        report.delete()
        File(dataDir(), "tunnel.log").delete()

        File(dataDir(), "state.txt").delete()

        if (forceInstall || run(exe, "/start", configFile.absolutePath, timeoutSeconds = 45) == null) {
            val install = runElevated(
                exe,
                listOf("/installtunnelservice", configFile.absolutePath, report.absolutePath),
                waitSeconds = 60,
            )
            if (install == ElevationResult.Denied) {
                return Result.Failure(Reason.ElevationDenied)
            }
        }

        val deadline = System.currentTimeMillis() + 90_000
        var running = false
        while (!running && System.currentTimeMillis() < deadline) {
            when (state()) {
                "RUNNING" -> running = true

                "STOPPED", "ABSENT" -> return Result.Failure(Reason.TunnelFailed, lastTunnelError())
                else -> Thread.sleep(400)
            }
        }
        if (!running) {
            val down = disconnect()
            return Result.Failure(
                Reason.TunnelFailed,
                listOfNotNull(
                    lastTunnelError().takeIf { it.isNotBlank() },
                    "туннель не снялся — адаптер может забирать трафик".takeIf { !down },
                ).joinToString(" · "),
            )
        }

        val handshakeDeadline = System.currentTimeMillis() + 20_000
        while (System.currentTimeMillis() < handshakeDeadline) {
            if (live()?.handshakeAt?.let { it > 0 } == true) return Result.Success
            if (state() != "RUNNING") {
                return Result.Failure(Reason.TunnelFailed, lastTunnelError())
            }
            Thread.sleep(500)
        }

        if (!disconnect()) {
            return Result.Failure(
                Reason.TunnelFailed,
                "рукопожатия нет, и туннель не снялся — адаптер может забирать трафик",
            )
        }
        return Result.Failure(Reason.NoHandshake, diag = classifyHandshakeFailure())
    }

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
            BLACKHOLE_V4.containsMatchIn(text) -> HandshakeDiag.BLACKHOLE

            listOf("invalid mac1", "invalid response message", "invalid initiation message")
                .any { text.contains(it, ignoreCase = true) } -> HandshakeDiag.REJECTED

            text.contains("Received message with unknown type", ignoreCase = true) ->
                HandshakeDiag.HEADER_MISMATCH

            listOf("forcibly closed", "connection reset", "refused")
                .any { text.contains(it, ignoreCase = true) } -> HandshakeDiag.PORT_CLOSED

            text.contains("Sending handshake initiation") -> HandshakeDiag.SILENCE

            else -> null
        }
    }

    private fun lastTunnelError(): String {
        val tunnelLog = File(dataDir(), "tunnel.log").takeIf { it.isFile }?.readTextSafely()
        val installLog = File(dataDir(), "install.log").takeIf { it.isFile }?.readTextSafely()

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

    fun disconnect(): Boolean {
        if (!isWindows) return true
        val exe = backend ?: findBackend() ?: return false

        if (run(exe, "/down", TUNNEL_NAME, timeoutSeconds = 30) != null) return true

        runElevated(exe, listOf("/uninstalltunnelservice", TUNNEL_NAME), waitSeconds = 20)
        return state() in setOf("ABSENT", "STOPPED")
    }

    private enum class ElevationResult { Ok, Denied, Error }

    private fun runElevated(exe: File, args: List<String>, waitSeconds: Long): ElevationResult {
        fun psQuote(value: String) = "'" + value.replace("'", "''") + "'"
        val argList = args.joinToString(",") { psQuote(it) }

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

    private fun state(): String {
        if (!isWindows) return "ABSENT"
        val exe = backend ?: findBackend() ?: return "ABSENT"
        return run(exe, "/status", TUNNEL_NAME)?.trim()?.uppercase() ?: "ABSENT"
    }

    private fun run(exe: File, vararg args: String, timeoutSeconds: Long = 15): String? = runCatching {
        val process = ProcessBuilder(listOf(exe.absolutePath) + args)
            .redirectErrorStream(true)
            .start()
        try {
            val output = ArrayBlockingQueue<String>(1)
            Thread {
                runCatching { process.inputStream.bufferedReader().use { output.put(it.readText()) } }
            }.apply { isDaemon = true }.start()

            if (!process.waitFor(timeoutSeconds, TimeUnit.SECONDS)) {
                process.destroyForcibly()
                return null
            }

            val text = output.poll(2, TimeUnit.SECONDS) ?: return null
            if (process.exitValue() != 0) null else text
        } finally {
            if (process.isAlive) process.destroyForcibly()
        }
    }.getOrNull()
}

private val BLACKHOLE_V4 = Regex("""Binding v4 socket to interface \d+ \(blackhole=true\)""")

private const val ERROR_CANCELLED = 1223

private const val GENERIC_FAILURE = 9009

private fun String.normalizeNewlines(): String =
    replace("\r\n", "\n").trimEnd().replace("\n", "\r\n") + "\r\n"

private fun File.readTextSafely(): String? = runCatching { readText() }.getOrNull()
