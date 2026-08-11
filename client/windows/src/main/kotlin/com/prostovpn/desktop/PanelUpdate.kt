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
 * установщик. Он ставится поверх, поэтому удалять приложение и входить
 * заново не нужно.
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
     * Запуск сюда не входит: между скачиванием и установкой приложение
     * спрашивает согласие и снимает туннель, а вызывающему нужно отличать
     * «не скачалось» от «не запустилось».
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
     * Запускает установщик и убеждается, что он действительно стартовал.
     *
     * Не тихая установка: пользователь должен видеть, что ставится, и
     * подтвердить повышение прав — молча менять программу на диске нельзя.
     *
     * MSI отдаём msiexec напрямую, а не системной ассоциации: обработчик по
     * расширению выбирает машина, и это лишний способ увести файл не туда.
     */
    suspend fun install(file: File): Result<Unit> = withContext(Dispatchers.IO) {
        try {
            val process = if (file.extension.equals("msi", ignoreCase = true)) {
                ProcessBuilder("msiexec.exe", "/i", file.absolutePath).start()
            } else {
                ProcessBuilder(file.absolutePath).start()
            }
            /*
            Мгновенный ненулевой код — это отказ запуска. Ждать дольше нельзя:
            установщик живёт до конца установки, и его успех сюда не приходит.
            */
            if (process.waitFor(2, TimeUnit.SECONDS) && process.exitValue() != 0) {
                Result.failure(UpdateProblem(Problem.LAUNCH))
            } else {
                Result.success(Unit)
            }
        } catch (e: IOException) {
            Result.failure(UpdateProblem(Problem.LAUNCH))
        } catch (e: InterruptedException) {
            Result.failure(UpdateProblem(Problem.LAUNCH))
        }
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
