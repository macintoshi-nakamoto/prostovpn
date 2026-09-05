package com.prostovpn.app

import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.LifecycleResumeEffect

@Composable
fun SettingsScreen(state: AppState, onBack: () -> Unit) {
    val s = state.s
    val context = LocalContext.current
    var showLogoutConfirm by remember { mutableStateOf(false) }
    var showFileSheet by remember { mutableStateOf(false) }
    var showAppsSheet by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) { state.updates.check(silent = true) }

    Box(Modifier.fillMaxSize()) {
        Box(Modifier.fillMaxSize().background(Theme.canvas))
        if (Theme.isLight) LightSheen()
        CanvasGlow(
            color = if (Theme.isLight) {
                Color(0xFFFA4C16).copy(alpha = 0.10f)
            } else {
                Color.White.copy(alpha = 0.09f)
            },
        )

        Column(
            modifier = Modifier
                .fillMaxSize()
                .statusBarsPadding()
                .padding(horizontal = 16.dp),
        ) {
            ScreenHeader(title = s.settings, onBack = onBack)

            Column(
                modifier = Modifier
                    .weight(1f)
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Spacer(Modifier.height(6.dp))

                UpdateBanner(state)

                Overline(s.sectionConnection)

                RowsCard(modifier = Modifier.fadeUp()) {
                    MenuRow(
                        title = s.autostartTitle,
                        chevron = false,
                        trailing = {
                            ProToggle(checked = state.autoConnect) { state.changeAutoConnect(it) }
                        },
                    )
                    HairLine()
                    MenuRow(
                        title = s.split,
                        subtitle = s.splitDesc,
                        height = 70.dp,
                        chevron = false,
                        trailing = {
                            ProToggle(checked = state.splitTunnelEnabled) {
                                state.changeSplitTunnel(it)
                            }
                        },
                    )
                    HairLine()
                    MenuRow(
                        title = s.appsTitle,
                        subtitle = appsSubtitle(state, s),
                        height = 70.dp,
                        onClick = { showAppsSheet = true },
                    )
                    HairLine()
                    BackgroundWorkRow(state)
                    NotificationsRow(state)
                    HairLine()
                    MenuRow(
                        title = s.fileTitle,
                        subtitle = fileSubtitle(state, s),
                        height = 70.dp,
                        onClick = { showFileSheet = true },
                    )
                }

                Overline(s.sectionApp)

                RowsCard(modifier = Modifier.fadeUp(60)) {
                    MenuRow(
                        title = s.language,
                        chevron = false,
                        trailing = {
                            Segment(
                                options = listOf("ru" to "RU", "en" to "EN"),
                                selected = state.lang,
                                onSelect = { state.changeLang(it) },
                            )
                        },
                    )
                    HairLine()
                    MenuRow(
                        title = s.theme,
                        chevron = false,
                        trailing = {
                            Segment(
                                options = listOf("dark" to s.themeDark, "light" to s.themeLight),
                                selected = if (state.themeMode == ThemeMode.LIGHT) "light" else "dark",
                                onSelect = {
                                    state.changeTheme(
                                        if (it == "light") ThemeMode.LIGHT else ThemeMode.DARK
                                    )
                                },
                            )
                        },
                    )
                    HairLine()
                    MenuRow(
                        title = s.about,
                        value = BuildConfig.VERSION_NAME,
                        onClick = { openUrl(context, "https://prostovpn.cc/guide") },
                    )
                }

                Spacer(Modifier.height(4.dp))

                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(52.dp)
                        .tvFocusHighlight(CircleShape)
                        .clip(CircleShape)
                        .background(Theme.errorWash)
                        .noRippleClickable { showLogoutConfirm = true },
                    contentAlignment = Alignment.Center,
                ) {
                    Text(s.logout, style = pro(15.sp, W.semibold, Theme.errorText))
                }

                Spacer(Modifier.navigationBarsPadding().height(24.dp))
            }
        }
    }

    if (showLogoutConfirm) {
        ProDialog(
            title = s.logoutConfirmTitle,
            message = s.logoutConfirmMessage,
            confirmText = s.yes,
            dismissText = s.no,
            onConfirm = {
                showLogoutConfirm = false
                state.logout()
            },
            onDismiss = { showLogoutConfirm = false },
        )
    }

    if (showFileSheet) {
        TunnelFileSheet(state = state, onDismiss = { showFileSheet = false })
    }

    if (showAppsSheet) {
        AppsSheet(state = state, onDismiss = { showAppsSheet = false })
    }
}

@Composable
private fun Overline(text: String) {
    Text(
        text = text,
        style = pro(12.sp, W.bold, Theme.textFaint, tracking = em(12.sp, 0.08f)),
        modifier = Modifier.padding(start = 6.dp, top = 6.dp),
    )
}

private fun appsSubtitle(state: AppState, s: Strings): String {
    val count = state.excludedApps.size
    return if (count == 0) s.appsNone else s.appsCount.format(count)
}

private fun fileSubtitle(state: AppState, s: Strings): String {
    val file = state.activeTunnelFile ?: return s.defaultMeta
    return "${file.name} · ${file.count} ${s.entries}"
}

@Composable
private fun UpdateBanner(state: AppState) {
    val s = state.s
    val updates = state.updates
    val actionable = updates.stage == UpdateManager.Stage.AVAILABLE ||
        updates.stage == UpdateManager.Stage.FAILED

    val title = when (updates.stage) {
        UpdateManager.Stage.CHECKING -> s.updateChecking
        UpdateManager.Stage.UP_TO_DATE -> s.updateNone
        UpdateManager.Stage.AVAILABLE -> s.updateAvailable.format(updates.info?.version.orEmpty())
        UpdateManager.Stage.DOWNLOADING -> s.updateDownloading.format(updates.percent)
        UpdateManager.Stage.INSTALLING -> s.updateInstalling
        UpdateManager.Stage.FAILED -> s.updateFailed
    }

    Banner(
        title = title,
        body = s.updateCurrent.format(BuildConfig.VERSION_NAME),
        tone = if (updates.stage == UpdateManager.Stage.FAILED) BannerTone.WARNING else BannerTone.ACCENT,
        actionText = if (actionable) s.updateButton else null,
        onAction = { updates.retry() },
        modifier = Modifier.fadeUp(),
    )
}

@Composable
private fun NotificationsRow(state: AppState) {
    val s = state.s
    val context = LocalContext.current
    var enabled by remember {
        mutableStateOf(androidx.core.app.NotificationManagerCompat.from(context).areNotificationsEnabled())
    }
    LifecycleResumeEffect(Unit) {
        enabled = androidx.core.app.NotificationManagerCompat.from(context).areNotificationsEnabled()
        onPauseOrDispose { }
    }

    HairLine()
    MenuRow(
        title = s.notificationsTitle,
        subtitle = if (enabled) null else s.notificationsDesc,
        height = if (enabled) 62.dp else 70.dp,
        chevron = false,
        onClick = {
            runCatching {
                context.startActivity(
                    android.content.Intent(
                        android.provider.Settings.ACTION_APP_NOTIFICATION_SETTINGS,
                    )
                        .putExtra(
                            android.provider.Settings.EXTRA_APP_PACKAGE,
                            context.packageName,
                        )
                        .addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK),
                )
            }
        },
        trailing = { ProToggle(checked = enabled, enabled = false) { } },
    )
}

@Composable
private fun BackgroundWorkRow(state: AppState) {
    val s = state.s
    val context = LocalContext.current
    var unrestricted by remember { mutableStateOf(BackgroundWork.isUnrestricted(context)) }

    LifecycleResumeEffect(Unit) {
        unrestricted = BackgroundWork.isUnrestricted(context)
        onPauseOrDispose { }
    }

    MenuRow(
        title = s.background,
        subtitle = if (unrestricted) s.backgroundDone else s.backgroundDesc,
        height = 70.dp,
        onClick = {
            if (unrestricted) BackgroundWork.openOemAutoStart(context) else BackgroundWork.request(context)
        },
        trailing = {
            if (unrestricted) {
                Box(
                    modifier = Modifier
                        .size(22.dp)
                        .clip(CircleShape)
                        .background(Theme.successWash),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        imageVector = Icons.check,
                        contentDescription = null,
                        tint = Theme.success,
                        modifier = Modifier.size(12.dp),
                    )
                }
            } else {
                Icon(
                    imageVector = Icons.chevronRight,
                    contentDescription = null,
                    tint = Theme.textFaint,
                    modifier = Modifier.size(17.dp),
                )
            }
        },
    )
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
private fun TunnelFileSheet(state: AppState, onDismiss: () -> Unit) {
    val s = state.s
    val context = LocalContext.current
    var showImportError by remember { mutableStateOf(false) }
    var fileToDelete by remember { mutableStateOf<TunnelFile?>(null) }
    val haptics = rememberHaptics()

    val filePicker = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { uri ->
        if (uri != null) {
            val content = runCatching {
                context.contentResolver.openInputStream(uri)?.bufferedReader()?.use { it.readText() }
            }.getOrNull()
            val name = queryFileName(context, uri) ?: "list.json"
            val ok = content != null && state.addTunnelFile(name, content)
            if (!ok) showImportError = true
        }
    }

    SheetShell(title = s.fileTitle, subtitle = s.fileDesc, onDismiss = onDismiss) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(max = 320.dp)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            state.tunnelFiles.forEach { file ->
                FileRow(
                    file = file,
                    meta = fileMeta(file, s),
                    isActive = file.id == state.activeTunnelFileId,
                    onSelect = {
                        haptics.selection()
                        state.selectTunnelFile(file)
                    },
                    onLongPress = { if (!file.isDefault) fileToDelete = file },
                )
            }
        }

        Spacer(Modifier.height(12.dp))

        Text(
            text = s.holdHint,
            style = pro(12.sp, W.regular, Theme.textFaint),
            textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth(),
        )

        Spacer(Modifier.height(12.dp))

        PrimaryPill(
            text = s.chooseFile,
            icon = Icons.upload,
            onClick = {
                // На ТВ-боксах и урезанных ROM системного пикера может не быть.
                runCatching {
                    filePicker.launch(arrayOf("application/json", "text/plain", "text/*"))
                }.onFailure { showImportError = true }
            },
        )
    }

    if (showImportError) {
        ProDialog(
            title = s.importError,
            message = "",
            confirmText = "OK",
            dismissText = null,
            destructive = false,
            onConfirm = { showImportError = false },
            onDismiss = { showImportError = false },
        )
    }

    fileToDelete?.let { file ->
        ProDialog(
            title = "${s.del}?",
            message = file.name,
            confirmText = s.del,
            dismissText = s.no,
            onConfirm = {
                state.deleteTunnelFile(file)
                fileToDelete = null
            },
            onDismiss = { fileToDelete = null },
        )
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun FileRow(
    file: TunnelFile,
    meta: String,
    isActive: Boolean,
    onSelect: () -> Unit,
    onLongPress: () -> Unit,
) {
    val interaction = remember { MutableInteractionSource() }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .pressScale(interaction, 0.98f)
            .tvFocusHighlight(RoundedCornerShape(R2.tile))
            .clip(RoundedCornerShape(R2.tile))
            .background(if (isActive) Theme.accentWash else Theme.tile.copy(alpha = if (Theme.isLight) 1f else 0.5f))
            .combinedClickable(
                interactionSource = interaction,
                indication = null,
                onClick = onSelect,
                onLongClick = onLongPress,
            )
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconCircle(icon = Icons.doc, size = 36.dp, iconSize = 17.dp)

        Spacer(Modifier.width(12.dp))

        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(1.dp)) {
            Text(
                text = file.name,
                style = pro(14.sp, W.semibold, Theme.text),
                maxLines = 1,
                overflow = TextOverflow.MiddleEllipsis,
            )
            Text(text = meta, style = pro(12.sp, W.regular, Theme.textFaint))
        }

        if (isActive) {
            Spacer(Modifier.width(8.dp))
            Icon(
                imageVector = Icons.check,
                contentDescription = null,
                tint = Theme.accent,
                modifier = Modifier.size(18.dp),
            )
        }
    }
}

private fun fileMeta(file: TunnelFile, s: Strings): String {
    val entries = "${file.count} ${s.entries}"
    return if (file.isDefault) "${s.defaultMeta} · $entries" else entries
}

fun queryFileName(context: android.content.Context, uri: Uri): String? = runCatching {
    context.contentResolver.query(uri, null, null, null, null)?.use { cursor ->
        val index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
        if (index >= 0 && cursor.moveToFirst()) cursor.getString(index) else null
    }
}.getOrNull()
