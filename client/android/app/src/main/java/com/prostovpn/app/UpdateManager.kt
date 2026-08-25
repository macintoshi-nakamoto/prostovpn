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

class UpdateManager(
    context: Context,
    private val scope: CoroutineScope,
) {
    private val appContext = context.applicationContext

    enum class Stage {
        CHECKING,

        UP_TO_DATE,

        AVAILABLE,

        DOWNLOADING,

        INSTALLING,

        FAILED,
    }

    var stage by mutableStateOf(Stage.CHECKING)
        private set

    var info by mutableStateOf<PanelApi.UpdateInfo?>(null)
        private set

    var percent by mutableIntStateOf(0)
        private set

    val mandatory: Boolean
        get() = info?.mandatory == true

    private var job: Job? = null

    private var verified: File? = null

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

                    if (fresh.version != info?.version) verified = null
                    info = fresh.takeIf { it.available }
                    stage = if (info != null) Stage.AVAILABLE else Stage.UP_TO_DATE
                }
                .onFailure {
                    if (!silent) stage = Stage.FAILED
                }
        }
    }

    fun retry() {
        if (info != null) install() else check()
    }

    fun install() {
        val update = info ?: return
        if (stage == Stage.DOWNLOADING || stage == Stage.INSTALLING) return

        verified?.takeIf { it.isFile }?.let {
            launchInstaller(it)
            return
        }

        val url = update.url

        if (url == null || !url.startsWith("https://", ignoreCase = true)) {
            stage = Stage.FAILED
            return
        }

        val target = updateFile(update)
        if (target == null) {
            stage = Stage.FAILED
            return
        }

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
            stage = Stage.FAILED
            return
        }

        percent = 0
        stage = Stage.DOWNLOADING
        job?.cancel()
        job = scope.launch { watchDownload(manager!!, id, update, target) }
    }

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

                -1 -> {
                    runCatching { manager.remove(id) }
                    stage = Stage.FAILED
                    return
                }
                else -> {
                    val known = if (total > 0) total else update.sizeBytes ?: -1L
                    if (known > 0) percent = (done * 100 / known).toInt().coerceIn(0, 100)
                }
            }
        }
    }

    private suspend fun verifyAndInstall(update: PanelApi.UpdateInfo, file: File) {
        stage = Stage.INSTALLING
        val ok = withContext(Dispatchers.Default) { checksumOk(update, file) }
        if (!ok) {
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

                    .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            )
        }

        stage = if (started.isSuccess) Stage.AVAILABLE else Stage.FAILED
    }

    private fun updateFile(update: PanelApi.UpdateInfo): File? {
        val base = appContext.getExternalFilesDir(null) ?: return null
        val dir = File(base, UPDATES_DIR).apply { mkdirs() }
        val version = update.version.orEmpty().replace(Regex("[^0-9A-Za-z._-]"), "_")
        return File(dir, "prosto-vpn-$version.apk")
    }

    companion object {
        private const val AUTHORITY = "com.prostovpn.app.fileprovider"

        private const val UPDATES_DIR = "updates"

        private const val APK_MIME = "application/vnd.android.package-archive"

        private val HEX64 = Regex("^[0-9a-f]{64}$")
    }
}
