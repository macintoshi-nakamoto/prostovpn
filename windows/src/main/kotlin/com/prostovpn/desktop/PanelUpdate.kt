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

/**
 * Обновление приложения через панель.
 *
 * Панель говорит, есть ли версия новее установленной, и даёт ссылку на
 * установщик. Дальше всё делает приложение: скачивает, сверяет, ставит и
 * открывается уже новым — от человека нужно одно нажатие и согласие на
 * права администратора.
 */
object PanelUpdate {

    /**
     * Адрес панели.
     *
     * Значение подставляет сборка (-PpanelUrl), но его можно переопределить
     * и на месте — системным свойством или переменной окружения.
     */
    var baseUrl: String =
        System.getProperty("panel.url")
            ?: System.getenv("PANEL_URL")
            ?: BuildInfo.PANEL_URL

    private const val TIMEOUT_MS = 15_000

    /*
    Пауза между пакетами, а не срок всей загрузки: SO_TIMEOUT считается
    заново на каждом чтении, поэтому медленную сеть минута не сломает, а
    молчащее соединение больше не подвешивает загрузку навсегда.
    */
    private const val READ_TIMEOUT_MS = 60_000

    private val HEX64 = Regex("^[0-9a-f]{64}$")

    /**
     * Почему обновление не получилось.
     *
     * Причину отдаём кодом, а не готовым текстом: сообщение исключения
     * писать в интерфейс нельзя (у FileNotFoundException это голый адрес
     * панели), да и перевести его не выйдет.
     */
    enum class Problem {
        /** Сеть или TLS: до панели не достучались. */
        NETWORK,

        /** Панель старая: маршрута /api/v1/version в ней нет. */
        PANEL_OUTDATED,

        /** Панель ответила ошибкой — код в [UpdateProblem.httpCode]. */
        SERVER,

        /** Ответ не разобрался. */
        BAD_ANSWER,

        /** Панель не сообщила sha256 — проверить скачанное нечем. */
        NO_CHECKSUM,

        /** Ссылка не https. */
        INSECURE_URL,

        /** Скачанное не сошлось с хешем или размером. */
        CORRUPTED,

        /** Установщик не запустился. */
        LAUNCH,

        /** Человек не дал прав администратора — установка не начиналась. */
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

    /**
     * Спрашивает панель о новой версии.
     *
     * Ошибку возвращаем, а не глушим: раньше любой сбой — 404 на старой
     * панели, обрыв сети, мусор в ответе — превращался в бодрое «установлена
     * последняя версия», и понять, что проверка вообще не состоялась, было
     * нельзя ни по экрану, ни по кнопке.
     */
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

    /**
     * Скачивает установщик и сверяет его с тем, что обещала панель.
     *
     * Установка сюда не входит: между ней и скачиванием приложение снимает
     * туннель и просит прав, а вызывающему нужно отличать «не скачалось» от
     * «не поставилось».
     *
     * Без sha256 не скачиваем вовсе. Проверять «только если хеш пришёл»
     * бессмысленно: подменить содержимое на пути от панели до человека
     * может ровно тот, кто уберёт и хеш, а запускается это с повышением
     * прав.
     */
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
        // Адрес в панели никак не проверяется и допускает http://.
        if (!source.protocol.equals("https", ignoreCase = true)) {
            return@withContext Result.failure(UpdateProblem(Problem.INSECURE_URL))
        }

        /*
        Имя из URL не берём: оно приходит извне и на Windows ломает путь
        («?» и «&» presigned-ссылки) либо подсовывает чужое расширение, по
        которому система и выбирает, чем файл открыть. Из ссылки оставляем
        только расширение, и то из белого списка.
        */
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
                        // Иначе уход с экрана отменяет корутину, а блокирующее
                        // чтение спокойно дорабатывает до конца.
                        ensureActive()
                        val read = input.read(buffer)
                        if (read <= 0) break
                        output.write(buffer, 0, read)
                        digest.update(buffer, 0, read)
                        done += read
                        if (total > 0) {
                            val percent = (done * 100 / total).toInt()
                            // Каждые 64 КБ дёргать интерфейс незачем.
                            if (percent != shown) {
                                shown = percent
                                onProgress(percent)
                            }
                        }
                    }
                }
            }

            // Сверяем записанное, а не Content-Length: заголовок подконтролен
            // тому же, кто подменил бы тело.
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
            // Недокачанное и непроверенное на диске не оставляем: следующая
            // попытка пишет в новый файл, а этот так и лежал бы в %TEMP%.
            Files.deleteIfExists(target)
            Result.failure(if (e is UpdateProblem) e else UpdateProblem(Problem.NETWORK))
        } finally {
            connection?.disconnect()
        }
    }

    /**
     * Ставит обновление и открывает уже новую версию.
     *
     * Как в Telegram: одно нажатие — и через несколько секунд приложение
     * снова на экране, только новое. Мастера установки человек не видит, и
     * запускать приложение заново руками не нужно.
     *
     * Сделать это изнутри самого приложения нельзя: MSI ставится major
     * upgrade'ом — сносит прежнюю установку целиком, а её файлы держит наша
     * же JVM. Поэтому работу доделывает отдельный процесс: он ждёт, пока мы
     * выйдем, ставит пакет тихо (`/qn`) и запускает новую версию.
     *
     * Права администратора нужны один раз, на установку: пакет ставится в
     * Program Files. Запрос UAC поднимаем здесь, пока приложение ещё на
     * экране, — отказ должен оставить всё как было, а не оборвать VPN ради
     * установки, которая не начнётся.
     *
     * Скрипт передаём base64 в командной строке, а не файлом на диске:
     * файл в общем %TEMP% между записью и запуском может подменить любой
     * процесс пользователя, а запускается он с повышением прав.
     *
     * @param expectedSha256 сумма скачанного: помощник сверяет файл ещё раз,
     *   уже в повышенном процессе и прямо перед запуском msiexec.
     */
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

    /**
     * Путь до установленного приложения — его же запустит помощник.
     *
     * `jpackage.app-path` выставляет лаунчер установленной сборки. На
     * ProcessHandle не полагаемся: под Gradle он вернёт java.exe, и вместо
     * приложения открылась бы JVM.
     */
    private fun installedAppPath(): String? =
        (System.getProperty("jpackage.app-path")
            ?: runCatching { ProcessHandle.current().info().command().orElse(null) }.getOrNull())
            ?.takeIf { it.endsWith(".exe", ignoreCase = true) }

    private fun psQuote(value: String) = "'" + value.replace("'", "''") + "'"

    /**
     * Что делает повышенный помощник: ждёт нашего выхода, освобождает папку
     * установки, ставит, открывает.
     *
     * Порядок важен, и это выучено на настоящей поломке. Пока хоть один
     * процесс держит файлы в папке установки, MSI не может их заменить: он
     * откладывает замену «на перезагрузку», Windows выполняет отложенное при
     * следующем включении, и папка остаётся полупустой — приложение больше
     * не запускается вовсе. Держать файлы может не только экземпляр, который
     * запустил обновление: второй экземпляр из трея, служба туннеля с
     * prostovpn-tunnel.exe и wintun.dll внутри той же папки.
     *
     * Поэтому: сначала ждём выхода того, кто нас запустил (по идентификатору,
     * а не по имени), не дождались — гасим принудительно; затем гасим всё
     * остальное, чей исполняемый файл лежит в папке установки. Человек уже
     * согласился на обновление и дал права администратора — «подождать ещё»
     * здесь означало бы сломать ему установку.
     */
    private fun helperScript(installer: String, sha256: String, appPath: String?, pid: Long): String {
        val relaunch = appPath?.let {
            /*
            Через explorer, а не напрямую: помощник работает с правами
            администратора, и запущенное им приложение унаследовало бы их.
            Explorer работает от имени вошедшего человека и открывает
            приложение с обычными правами — тот же процесс, что и запуск
            с ярлыка.

            Путь внутри кавычек: Start-Process складывает -ArgumentList в
            командную строку как есть, ничего не экранируя, а приложение
            стоит в «C:\Program Files\Prosto VPN\» — без кавычек explorer
            получил бы три отдельных слова.
            */
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
