package com.prostovpn.app

import android.app.DownloadManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.content.FileProvider
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.security.MessageDigest

/**
 * Обновление приложения через панель — андроидный родственник PanelUpdate
 * из Windows-клиента.
 *
 * Общее с Windows: панель отвечает на /api/v1/version, скачанное сверяется
 * с обещанными sha256 и размером, состояние живёт вне экрана настроек —
 * обязательное обновление показывается и на главном. Разное — сама
 * установка: на Android поставить APK «тихо» приложению нельзя, последний
 * шаг всегда подтверждает человек в системном установщике, поэтому вместо
 * повышенного помощника здесь FileProvider и Intent(ACTION_VIEW).
 *
 * Качает системный DownloadManager, а не свой цикл по HttpURLConnection:
 * он доживает загрузку при свёрнутом приложении и сам показывает прогресс
 * в шторке — на телефоне уход с экрана во время скачивания не исключение,
 * а норма.
 */
class UpdateManager(
    context: Context,
    private val scope: CoroutineScope,
) {

    private val appContext = context.applicationContext

    /** Что сейчас происходит с обновлением — по этому рисуется карточка. */
    enum class Stage {
        /** Запрос к панели в полёте. */
        CHECKING,

        /** Новее ничего нет. */
        UP_TO_DATE,

        /** Есть версия новее — можно скачивать. */
        AVAILABLE,

        /** DownloadManager качает APK, прогресс в [percent]. */
        DOWNLOADING,

        /** Скачанное сверяется с хешем и уходит в системный установщик. */
        INSTALLING,

        /** Проверка или скачивание не удались — можно повторить. */
        FAILED,
    }

    var stage by mutableStateOf(Stage.CHECKING)
        private set

    /** Ответ панели; null — новой версии нет или проверка не удалась. */
    var info by mutableStateOf<PanelApi.UpdateInfo?>(null)
        private set

    var percent by mutableIntStateOf(0)
        private set

    /** Обновление обязательное — баннер выходит и на главный экран. */
    val mandatory: Boolean
        get() = info?.mandatory == true

    private var job: Job? = null

    /**
     * Скачанный и уже сверенный APK.
     *
     * Нужен из-за разрешения «неизвестные источники»: когда его нет,
     * человек уходит в системные настройки и возвращается — повторное
     * нажатие «Обновить» должно сразу открыть установщик, а не качать
     * файл заново.
     */
    private var verified: File? = null

    /**
     * Спрашивает панель о новой версии.
     *
     * Ошибку показываем, а не глушим: на Windows любой сбой превращался в
     * бодрое «установлена последняя версия», и понять, что проверка вообще
     * не состоялась, было нельзя.
     *
     * [silent] — для повторов при открытии настроек: тихая проверка не
     * мигает «Проверяем…» поверх уже показанного результата и не затирает
     * его разовой сетевой неудачей.
     */
    fun check(silent: Boolean = false) {
        when (stage) {
            Stage.DOWNLOADING, Stage.INSTALLING -> return
            Stage.CHECKING -> if (silent) return
            else -> Unit
        }
        job?.cancel()
        if (!silent) stage = Stage.CHECKING
        job = scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching { PanelApi.checkUpdate(BuildConfig.VERSION_NAME) }
            }
            result
                .onSuccess { fresh ->
                    // Версия сменилась — прежний скачанный файл больше не тот
                    if (fresh.version != info?.version) verified = null
                    info = fresh.takeIf { it.available }
                    stage = if (info != null) Stage.AVAILABLE else Stage.UP_TO_DATE
                }
                .onFailure {
                    // Тихую неудачу не показываем: связь могла моргнуть на
                    // одну проверку, а прежний результат ещё верен.
                    if (!silent) stage = Stage.FAILED
                }
        }
    }

    /** Кнопка в состоянии «ошибка»: заново с того места, где сломалось. */
    fun retry() {
        if (info != null) install() else check()
    }

    /**
     * Скачивает APK и открывает установку.
     *
     * Сначала DownloadManager кладёт файл в наш каталог на внешнем
     * хранилище (updates/ из file_paths.xml), затем файл сверяется с тем,
     * что обещала панель, и уходит в системный установщик через
     * FileProvider — content://, потому что file:// Android 7+ не примет.
     */
    fun install() {
        val update = info ?: return
        if (stage == Stage.DOWNLOADING || stage == Stage.INSTALLING) return

        // Файл уже скачан и сверен — например, человек возвращается из
        // настроек «неизвестных источников». Качать заново незачем.
        verified?.takeIf { it.isFile }?.let {
            launchInstaller(it)
            return
        }

        val url = update.url
        // Адрес в панели никак не проверяется и допускает http://, а по
        // ссылке приедет исполняемый пакет — без TLS его не берём.
        if (url == null || !url.startsWith("https://", ignoreCase = true)) {
            stage = Stage.FAILED
            return
        }

        /*
        Имя из URL не берём: presigned-ссылка приносит «?» и «&», а
        расширение решает, чем система откроет файл. Версию в имя кладём,
        чтобы файл от прежней версии не выдался за новый.
        */
        val target = updateFile(update)
        if (target == null) {
            // Внешнего files-каталога нет (бывает на урезанных приставках) —
            // DownloadManager писать некуда.
            stage = Stage.FAILED
            return
        }
        // Недокачанное с прошлого раза только мешает: DownloadManager в
        // занятый путь писать не станет.
        target.delete()

        val manager = appContext.getSystemService(Context.DOWNLOAD_SERVICE) as? DownloadManager
        val id = runCatching {
            val request = DownloadManager.Request(Uri.parse(url))
                .setTitle("Prosto VPN ${update.version.orEmpty()}")
                .setMimeType(APK_MIME)
                .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE)
                .setDestinationInExternalFilesDir(appContext, null, "$UPDATES_DIR/${target.name}")
            manager!!.enqueue(request)
        }.getOrNull()
        if (id == null) {
            // Службу загрузок на устройстве могли отключить целиком.
            stage = Stage.FAILED
            return
        }

        percent = 0
        stage = Stage.DOWNLOADING
        job?.cancel()
        job = scope.launch { watchDownload(manager!!, id, update, target) }
    }

    /**
     * Следит за загрузкой опросом раз в полсекунды.
     *
     * Опрос, а не BroadcastReceiver: приёмник требует регистрации с
     * жизненным циклом и context-flags на новых API, а прогресса всё равно
     * не присылает — только факт завершения. Здесь же и проценты, и финал
     * из одного места.
     */
    private suspend fun watchDownload(
        manager: DownloadManager,
        id: Long,
        update: PanelApi.UpdateInfo,
        target: File,
    ) {
        while (true) {
            delay(500)
            var status = -1
            var done = 0L
            var total = -1L
            manager.query(DownloadManager.Query().setFilterById(id))?.use { cursor ->
                if (cursor.moveToFirst()) {
                    status = cursor.getInt(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS))
                    done = cursor.getLong(
                        cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_BYTES_DOWNLOADED_SO_FAR)
                    )
                    total = cursor.getLong(
                        cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_TOTAL_SIZE_BYTES)
                    )
                }
            }

            when (status) {
                DownloadManager.STATUS_SUCCESSFUL -> {
                    verifyAndInstall(update, target)
                    return
                }
                DownloadManager.STATUS_FAILED,
                // Курсор пуст — загрузку смахнули из шторки, файла не будет.
                -1 -> {
                    runCatching { manager.remove(id) }
                    stage = Stage.FAILED
                    return
                }
                else -> {
                    // Content-Length сервер мог и не прислать — тогда без цифры.
                    val known = if (total > 0) total else update.sizeBytes ?: -1L
                    if (known > 0) percent = (done * 100 / known).toInt().coerceIn(0, 100)
                }
            }
        }
    }

    /**
     * Сверяет скачанное и открывает установщик.
     *
     * Размер и хеш — с тем, что обещала панель, а не с заголовками ответа:
     * заголовки подконтрольны тому же, кто подменил бы тело. sha256 панель
     * может не прислать — тогда целостность держится на TLS: ссылку без
     * https [install] не принимает.
     */
    private suspend fun verifyAndInstall(update: PanelApi.UpdateInfo, file: File) {
        stage = Stage.INSTALLING
        val ok = withContext(Dispatchers.Default) { checksumOk(update, file) }
        if (!ok) {
            // Битое или подменённое на диске не оставляем — следующая
            // попытка качает заново.
            file.delete()
            stage = Stage.FAILED
            return
        }
        verified = file
        launchInstaller(file)
    }

    private fun checksumOk(update: PanelApi.UpdateInfo, file: File): Boolean {
        if (update.sizeBytes != null && update.sizeBytes != file.length()) return false
        val expected = update.sha256?.lowercase() ?: return true
        if (!HEX64.matches(expected)) return false

        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(1 shl 16)
            while (true) {
                val read = input.read(buffer)
                if (read <= 0) break
                digest.update(buffer, 0, read)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) } == expected
    }

    /**
     * Отдаёт проверенный APK системному установщику.
     *
     * Без права «устанавливать неизвестные приложения» установщик молча не
     * откроется — поэтому сначала ведём человека на системный экран, где
     * это право выдаётся. Файл при этом не теряется: после возврата
     * повторное нажатие «Обновить» сразу открывает установку.
     */
    private fun launchInstaller(file: File) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
            !appContext.packageManager.canRequestPackageInstalls()
        ) {
            stage = Stage.AVAILABLE
            runCatching {
                appContext.startActivity(
                    Intent(
                        Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                        Uri.parse("package:${appContext.packageName}"),
                    ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                )
            }
            return
        }

        val uri = FileProvider.getUriForFile(appContext, AUTHORITY, file)
        val started = runCatching {
            appContext.startActivity(
                Intent(Intent.ACTION_VIEW)
                    .setDataAndType(uri, APK_MIME)
                    // Установщик — другой процесс, без явного гранта он
                    // content:// от нашего провайдера не прочитает.
                    .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            )
        }
        /*
        Дальше — системный диалог, наш процесс уходит в фон. Если человек
        передумает и вернётся, честное состояние — «доступна версия», а не
        вечное «устанавливаем»: установилось ли на самом деле, приложение
        узнает просто тем, что перезапустится уже новым.
        */
        stage = if (started.isSuccess) Stage.AVAILABLE else Stage.FAILED
    }

    /** Файл назначения в updates/ внешнего files-каталога; null — каталога нет. */
    private fun updateFile(update: PanelApi.UpdateInfo): File? {
        val base = appContext.getExternalFilesDir(null) ?: return null
        val dir = File(base, UPDATES_DIR).apply { mkdirs() }
        val version = update.version.orEmpty().replace(Regex("[^0-9A-Za-z._-]"), "_")
        return File(dir, "prosto-vpn-$version.apk")
    }

    companion object {
        /** Совпадает с authorities провайдера в манифесте. */
        private const val AUTHORITY = "com.prostovpn.app.fileprovider"

        /** Подкаталог из res/xml/file_paths.xml — external-files-path «updates/». */
        private const val UPDATES_DIR = "updates"

        private const val APK_MIME = "application/vnd.android.package-archive"

        private val HEX64 = Regex("^[0-9a-f]{64}$")
    }
}
