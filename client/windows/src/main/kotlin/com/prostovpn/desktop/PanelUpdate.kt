package com.prostovpn.desktop

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import org.json.JSONException
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.nio.file.Files
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

object PanelUpdate {
    var baseUrl: String =
        System.getProperty("panel.url")
            ?: System.getenv("PANEL_URL")
            ?: BuildInfo.PANEL_URL

    private const val TIMEOUT_MS = 15_000

    private const val READ_TIMEOUT_MS = 60_000

    private val HEX64 = Regex("^[0-9a-f]{64}$")

    enum class Problem {
        NETWORK,

        PANEL_OUTDATED,

        SERVER,

        BAD_ANSWER,

        NO_CHECKSUM,

        INSECURE_URL,

        CORRUPTED,

        LAUNCH,

        CANCELLED,
    }

    class UpdateProblem(val problem: Problem, val httpCode: Int = 0) : Exception(problem.name)

    data class Info(
        val available: Boolean,
        val version: String?,
        val url: String?,
        val changelog: String?,
        val mandatory: Boolean,
        val sha256: String?,
        val sizeBytes: Long?,
    )

    suspend fun check(currentVersion: String): Result<Info> = withContext(Dispatchers.IO) {
        try {
            val query = "platform=windows&current=" + URLEncoder.encode(currentVersion, "UTF-8")
            val body = JSONObject(get("/api/v1/version?$query"))
            Result.success(
                Info(
                    available = body.optBoolean("update_available"),
                    version = body.optString("version").takeIf { it.isNotEmpty() },
                    url = body.optString("url").takeIf { it.isNotEmpty() },
                    changelog = body.optString("changelog").takeIf { it.isNotEmpty() },
                    mandatory = body.optBoolean("mandatory"),
                    sha256 = body.optString("sha256").takeIf { it.isNotEmpty() },
                    sizeBytes = body.optLong("size_bytes").takeIf { it > 0 },
                )
            )
        } catch (e: UpdateProblem) {
            Result.failure(e)
        } catch (e: JSONException) {
            Result.failure(UpdateProblem(Problem.BAD_ANSWER))
        } catch (e: IOException) {
            Result.failure(UpdateProblem(Problem.NETWORK))
        }
    }

    suspend fun download(
        info: Info,
        onProgress: (Int) -> Unit = {},
    ): Result<File> = withContext(Dispatchers.IO) {
        val expected = info.sha256?.lowercase()
        if (expected == null || !HEX64.matches(expected)) {
            return@withContext Result.failure(UpdateProblem(Problem.NO_CHECKSUM))
        }
        val url = info.url ?: return@withContext Result.failure(UpdateProblem(Problem.BAD_ANSWER))
        val source = runCatching { URL(url) }.getOrNull()
            ?: return@withContext Result.failure(UpdateProblem(Problem.BAD_ANSWER))

        if (!source.protocol.equals("https", ignoreCase = true)) {
            return@withContext Result.failure(UpdateProblem(Problem.INSECURE_URL))
        }

        val ext = source.path.substringAfterLast('/').substringAfterLast('.', "")
            .lowercase()
            .takeIf { it == "msi" || it == "exe" } ?: "msi"
        val target = Files.createTempFile("prostovpn-update-", ".$ext")

        var connection: HttpURLConnection? = null
        try {
            val open = (source.openConnection() as HttpURLConnection).apply {
                PanelTls.apply(this)
                connectTimeout = TIMEOUT_MS
                readTimeout = READ_TIMEOUT_MS
                instanceFollowRedirects = true
            }
            connection = open
            if (open.responseCode != HttpURLConnection.HTTP_OK) {
                throw UpdateProblem(Problem.SERVER, open.responseCode)
            }

            val total = open.contentLengthLong
            val digest = MessageDigest.getInstance("SHA-256")
            var done = 0L
            var shown = -1
            open.inputStream.use { input ->
                Files.newOutputStream(target).use { output ->
                    val buffer = ByteArray(1 shl 16)
                    while (true) {
                        ensureActive()
                        val read = input.read(buffer)
                        if (read <= 0) break
                        output.write(buffer, 0, read)
                        digest.update(buffer, 0, read)
                        done += read
                        if (total > 0) {
                            val percent = (done * 100 / total).toInt()

                            if (percent != shown) {
                                shown = percent
                                onProgress(percent)
                            }
                        }
                    }
                }
            }

            if (info.sizeBytes != null && info.sizeBytes != done) {
                throw UpdateProblem(Problem.CORRUPTED)
            }
            val actual = digest.digest().joinToString("") { "%02x".format(it) }
            if (actual != expected) throw UpdateProblem(Problem.CORRUPTED)

            Result.success(target.toFile())
        } catch (e: CancellationException) {
            Files.deleteIfExists(target)
            throw e
        } catch (e: Throwable) {
            Files.deleteIfExists(target)
            Result.failure(if (e is UpdateProblem) e else UpdateProblem(Problem.NETWORK))
        } finally {
            connection?.disconnect()
        }
    }

    suspend fun installAndRestart(file: File, expectedSha256: String): Result<Unit> =
        withContext(Dispatchers.IO) {
            val checksum = expectedSha256.lowercase()
            if (!HEX64.matches(checksum)) {
                return@withContext Result.failure(UpdateProblem(Problem.NO_CHECKSUM))
            }
            if (!isWindows) return@withContext Result.failure(UpdateProblem(Problem.LAUNCH))

            val helper = helperScript(
                installer = file.absolutePath,
                sha256 = checksum,
                appPath = installedAppPath(),
                pid = ProcessHandle.current().pid(),
            )
            when (runElevated(helper)) {
                Elevation.OK -> Result.success(Unit)
                Elevation.DENIED -> Result.failure(UpdateProblem(Problem.CANCELLED))
                Elevation.ERROR -> Result.failure(UpdateProblem(Problem.LAUNCH))
            }
        }

    private val isWindows: Boolean
        get() = System.getProperty("os.name").orEmpty().startsWith("Windows", ignoreCase = true)

    private fun installedAppPath(): String? =
        (System.getProperty("jpackage.app-path")
            ?: runCatching { ProcessHandle.current().info().command().orElse(null) }.getOrNull())
            ?.takeIf { it.endsWith(".exe", ignoreCase = true) }

    private fun psQuote(value: String) = "'" + value.replace("'", "''") + "'"

    private fun helperScript(installer: String, sha256: String, appPath: String?, pid: Long): String {
        val relaunch = appPath?.let {
            "Start-Process explorer.exe -ArgumentList ${psQuote("\"" + it + "\"")}"
        } ?: ""

        // Корень установки — каталог самого приложения. Нет пути (запуск из
        // Gradle) — нечего и освобождать.
        val installRoot = appPath?.let { File(it).parent }
        val freeFolder = installRoot?.let {
            """
            ${'$'}root = ${psQuote(it)}
            Get-Process | Where-Object {
                ${'$'}_.Path -and ${'$'}_.Path.StartsWith(${'$'}root, [System.StringComparison]::OrdinalIgnoreCase)
            } | Stop-Process -Force
            Start-Sleep -Milliseconds 500
            """.trimIndent()
        } ?: ""

        return """
            ${'$'}ErrorActionPreference = 'SilentlyContinue'

            ${'$'}deadline = (Get-Date).AddSeconds(90)
            while ((Get-Process -Id $pid -ErrorAction SilentlyContinue) -and (Get-Date) -lt ${'$'}deadline) {
                Start-Sleep -Milliseconds 200
            }
            if (Get-Process -Id $pid -ErrorAction SilentlyContinue) {
                Stop-Process -Id $pid -Force
                Start-Sleep -Milliseconds 500
            }

            $freeFolder

            ${'$'}installer = ${psQuote(installer)}
            ${'$'}actual = (Get-FileHash -Path ${'$'}installer -Algorithm SHA256).Hash
            if (${'$'}actual -ne ${psQuote(sha256)}) {
                Remove-Item ${'$'}installer -Force
                exit 2
            }

            ${'$'}line = '/i "' + ${'$'}installer + '" /qn /norestart'
            ${'$'}msi = Start-Process msiexec.exe -ArgumentList ${'$'}line -Wait -PassThru
            Remove-Item ${'$'}installer -Force
            if (${'$'}msi.ExitCode -eq 0 -or ${'$'}msi.ExitCode -eq 3010) {
                $relaunch
            }
            exit ${'$'}msi.ExitCode
        """.trimIndent()
    }

    private enum class Elevation { OK, DENIED, ERROR }

    /** Отказ в UAC приходит Win32Exception с кодом 1223, а не кодом возврата. */
    private const val ERROR_CANCELLED = 1223

    /**
     * Поднимает помощника с правами администратора и ждёт только решения UAC.
     *
     * Именно только решения: помощник ждёт нашего выхода, и дожидаться его
     * целиком значит запереть себя — он не закончит, пока мы не закроемся, а
     * мы не закроемся, пока он не закончит.
     */
    private fun runElevated(helper: String): Elevation {
        fun encode(script: String) =
            java.util.Base64.getEncoder().encodeToString(script.toByteArray(Charsets.UTF_16LE))

        val launcher = """
            ${'$'}ErrorActionPreference = 'Stop'
            try {
                Start-Process -FilePath 'powershell.exe' -Verb RunAs -WindowStyle Hidden -ArgumentList @(
                    '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden',
                    '-EncodedCommand', '${encode(helper)}'
                )
                exit 0
            } catch {
                ${'$'}e = ${'$'}_.Exception
                while (${'$'}e -ne ${'$'}null -and -not (${'$'}e -is [System.ComponentModel.Win32Exception])) {
                    ${'$'}e = ${'$'}e.InnerException
                }
                if (${'$'}e -is [System.ComponentModel.Win32Exception]) { exit ${'$'}e.NativeErrorCode }
                exit 1
            }
        """.trimIndent()

        return runCatching {
            val process = ProcessBuilder(
                "powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encode(launcher),
            ).redirectErrorStream(true).start()

            // Запрос UAC может провисеть на экране: ждём человека, а не сеть.
            if (!process.waitFor(2, TimeUnit.MINUTES)) {
                process.destroyForcibly()
                return Elevation.ERROR
            }
            when (process.exitValue()) {
                0 -> Elevation.OK
                ERROR_CANCELLED -> Elevation.DENIED
                else -> Elevation.ERROR
            }
        }.getOrDefault(Elevation.ERROR)
    }

    private fun get(path: String): String {
        val connection = (URL(baseUrl.trimEnd('/') + path).openConnection() as HttpURLConnection).apply {
            PanelTls.apply(this)
            connectTimeout = TIMEOUT_MS
            readTimeout = TIMEOUT_MS
            setRequestProperty("Content-Type", "application/json")
        }
        try {
            val code = connection.responseCode
            if (code != HttpURLConnection.HTTP_OK) {
                // 404 — это не «обновлений нет», а панель без маршрута
                // /api/v1/version: на боевой 2.0.0 его ещё не было.
                val problem =
                    if (code == HttpURLConnection.HTTP_NOT_FOUND) Problem.PANEL_OUTDATED else Problem.SERVER
                throw UpdateProblem(problem, code)
            }
            return connection.inputStream.bufferedReader().use { it.readText() }
        } finally {
            connection.disconnect()
        }
    }
}
