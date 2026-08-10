package com.prostovpn.desktop

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.awt.Desktop
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.nio.file.Files

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

    data class Info(
        val available: Boolean,
        val version: String?,
        val url: String?,
        val changelog: String?,
        val mandatory: Boolean,
    ) {
        companion object {
            val none = Info(false, null, null, null, false)
        }
    }

    /** Спрашивает панель о новой версии. Ошибки глушим: проверка фоновая. */
    suspend fun check(currentVersion: String): Info = withContext(Dispatchers.IO) {
        runCatching {
            val query = "platform=windows&current=" + URLEncoder.encode(currentVersion, "UTF-8")
            val body = JSONObject(get("/api/v1/version?$query"))
            Info(
                available = body.optBoolean("update_available"),
                version = body.optString("version").takeIf { it.isNotEmpty() },
                url = body.optString("url").takeIf { it.isNotEmpty() },
                changelog = body.optString("changelog").takeIf { it.isNotEmpty() },
                mandatory = body.optBoolean("mandatory"),
            )
        }.getOrDefault(Info.none)
    }

    /**
     * Скачивает установщик и открывает его.
     *
     * Возвращает путь к файлу: если система отказалась его запустить,
     * человеку есть что показать, а не просто «ошибка».
     */
    suspend fun download(
        url: String,
        onProgress: (Int) -> Unit = {},
    ): Result<File> = withContext(Dispatchers.IO) {
        runCatching {
            val connection = (URL(url).openConnection() as HttpURLConnection).apply {
                connectTimeout = TIMEOUT_MS
                // Таймаут чтения не ставим: установщик весит десятки мегабайт,
                // и на медленной сети долгая загрузка — норма, а не ошибка.
                instanceFollowRedirects = true
            }

            val name = url.substringAfterLast('/').ifEmpty { "prosto-vpn-update.msi" }
            val target = File(System.getProperty("java.io.tmpdir"), name)
            val total = connection.contentLengthLong

            connection.inputStream.use { input ->
                Files.newOutputStream(target.toPath()).use { output ->
                    val buffer = ByteArray(1 shl 16)
                    var done = 0L
                    while (true) {
                        val read = input.read(buffer)
                        if (read <= 0) break
                        output.write(buffer, 0, read)
                        done += read
                        if (total > 0) onProgress((done * 100 / total).toInt())
                    }
                }
            }
            connection.disconnect()

            launchInstaller(target)
            target
        }
    }

    /**
     * Запускает установщик средствами системы.
     *
     * Не тихая установка: пользователь должен видеть, что ставится, и
     * подтвердить повышение прав — молча менять программу на диске нельзя.
     */
    private fun launchInstaller(file: File) {
        if (Desktop.isDesktopSupported() && Desktop.getDesktop().isSupported(Desktop.Action.OPEN)) {
            Desktop.getDesktop().open(file)
        } else {
            ProcessBuilder("cmd", "/c", "start", "", file.absolutePath).start()
        }
    }

    private fun get(path: String): String {
        val connection = (URL(baseUrl.trimEnd('/') + path).openConnection() as HttpURLConnection).apply {
            connectTimeout = TIMEOUT_MS
            readTimeout = TIMEOUT_MS
            setRequestProperty("Content-Type", "application/json")
        }
        try {
            return connection.inputStream.bufferedReader().use { it.readText() }
        } finally {
            connection.disconnect()
        }
    }
}
