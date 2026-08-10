package com.prostovpn.desktop

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.hoverable
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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch

@Composable
fun SettingsScreen(
    state: AppState,
    backdrop: BackdropState,
    onBack: () -> Unit,
    drag: @Composable (@Composable () -> Unit) -> Unit,
) {
    val s = state.s
    var showLogoutConfirm by remember { mutableStateOf(false) }
    var showFileSheet by remember { mutableStateOf(state.previewFileSheetOpen) }

    Box(Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = Layout.screenPadding)
                .padding(bottom = Layout.screenPadding),
        ) {
            drag {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = Layout.topPadding),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    GlassBackButton(backdrop = backdrop, onBack = onBack)
                    Spacer(Modifier.weight(1f))
                }
            }

            Text(
                text = s.settings,
                style = manrope(30.sp, W.extraBold, Theme.text),
                modifier = Modifier.padding(start = 2.dp, top = 14.dp, bottom = 20.dp),
            )

            Column(
                modifier = Modifier
                    .weight(1f)
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                TogglesCard(
                    state = state,
                    onAddFile = { showFileSheet = true },
                )
                LanguageCard(state)
                Spacer(Modifier.height(0.dp))
            }

            Spacer(Modifier.height(14.dp))

            UpdateCard(state)

            Spacer(Modifier.height(14.dp))

            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(52.dp)
                    .scaleClickable(0.98f) { showLogoutConfirm = true }
                    .clip(RoundedCornerShape(20.dp))
                    .background(Theme.accentTint08),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = s.logout,
                    style = manrope(15.sp, W.bold, Theme.link),
                )
            }
        }

        TunnelFileSheet(
            state = state,
            visible = showFileSheet,
            backdrop = backdrop,
            onDismiss = { showFileSheet = false },
        )

        GlassDialog(
            visible = showLogoutConfirm,
            backdrop = backdrop,
            onDismiss = { showLogoutConfirm = false },
        ) {
            Text(
                text = s.logoutConfirmTitle,
                style = manrope(18.sp, W.extraBold, Theme.text),
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(8.dp))
            Text(
                text = s.logoutConfirmMessage,
                style = manrope(13.5.sp, W.medium, Theme.textSecondary),
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(20.dp))
            Row(Modifier.fillMaxWidth()) {
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .height(46.dp)
                        .clip(RoundedCornerShape(15.dp))
                        .background(Color.White.copy(alpha = 0.07f))
                        .noRippleClickable { showLogoutConfirm = false },
                    contentAlignment = Alignment.Center,
                ) {
                    Text(s.no, style = manrope(15.sp, W.bold, Theme.text))
                }
                Spacer(Modifier.width(10.dp))
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .height(46.dp)
                        .clip(RoundedCornerShape(15.dp))
                        .background(Theme.accentTint12)
                        .noRippleClickable {
                            showLogoutConfirm = false
                            state.logout()
                        },
                    contentAlignment = Alignment.Center,
                ) {
                    Text(s.yes, style = manrope(15.sp, W.bold, Theme.link))
                }
            }
        }
    }
}

@Composable
private fun TogglesCard(state: AppState, onAddFile: () -> Unit) {
    val s = state.s
    CardGroup {
        ToggleRow(s.split, s.splitDesc, state.splitTunnelEnabled) { state.changeSplitTunnel(it) }

        AnimatedVisibility(
            visible = state.splitTunnelEnabled,
            enter = expandVertically(animationSpec = Theme.spring(300)) + fadeIn(Theme.spring(300)),
            exit = shrinkVertically(animationSpec = Theme.spring(300)) + fadeOut(Theme.spring(200)),
        ) {
            PrimaryButton(
                text = s.addFile,
                icon = Icons.plus,
                height = 46.dp,
                cornerRadius = 15.dp,
                onClick = onAddFile,
                modifier = Modifier.padding(start = 8.dp, end = 8.dp, top = 2.dp, bottom = 10.dp),
            )
        }

        CardDivider()
        ToggleRow(s.kill, s.killDesc, state.killSwitch) { state.changeKillSwitch(it) }
        CardDivider()
        ToggleRow(s.autostart, s.autostartDesc, state.autoStart) { state.changeAutoStart(it) }
        CardDivider()
        ToggleRow(s.autoconnect, s.autoconnectDesc, state.autoConnect) { state.changeAutoConnect(it) }
        CardDivider()
        ToggleRow(s.logging, s.loggingDesc, state.logging) { state.changeLogging(it) }
    }
}

@Composable
private fun LanguageCard(state: AppState) {
    val s = state.s
    CardGroup {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 13.dp, horizontal = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(s.language, style = manrope(15.sp, W.bold, Theme.text))
                Text(s.langName, style = manrope(12.5.sp, W.medium, Theme.textMuted))
            }

            Row(
                modifier = Modifier
                    .clip(RoundedCornerShape(11.dp))
                    .background(Color.White.copy(alpha = 0.08f))
                    .padding(3.dp),
            ) {
                LangButton("RU", state.lang == "ru") { state.changeLang("ru") }
                LangButton("EN", state.lang == "en") { state.changeLang("en") }
            }
        }
    }
}

@Composable
private fun LangButton(title: String, active: Boolean, onClick: () -> Unit) {
    val bg by androidx.compose.animation.animateColorAsState(
        targetValue = if (active) Theme.accent else Color.Transparent,
        animationSpec = androidx.compose.animation.core.tween(220),
        label = "langBg",
    )
    val fg by androidx.compose.animation.animateColorAsState(
        targetValue = if (active) Color.White else Theme.text.copy(alpha = 0.5f),
        animationSpec = androidx.compose.animation.core.tween(220),
        label = "langFg",
    )
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(9.dp))
            .background(bg)
            .noRippleClickable(onClick = onClick)
            .padding(horizontal = 17.dp, vertical = 6.dp),
    ) {
        Text(text = title, style = manrope(13.sp, W.bold, fg))
    }
}

@Composable
private fun ToggleRow(
    title: String,
    subtitle: String,
    checked: Boolean,
    onChange: (Boolean) -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 13.dp, horizontal = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(title, style = manrope(15.sp, W.bold, Theme.text))
            Text(subtitle, style = manrope(12.5.sp, W.medium, Theme.textMuted))
        }

        Spacer(Modifier.width(14.dp))

        OrangeToggle(checked = checked, onChange = onChange)
    }
}


// --- Шторка «Файл туннелирования» ---

@Composable
private fun TunnelFileSheet(
    state: AppState,
    visible: Boolean,
    backdrop: BackdropState,
    onDismiss: () -> Unit,
) {
    val s = state.s
    var showImportError by remember { mutableStateOf(false) }
    var menuFile by remember { mutableStateOf<TunnelFile?>(null) }
    var menuPosition by remember { mutableStateOf(Offset.Zero) }
    var confirmDelete by remember { mutableStateOf<TunnelFile?>(null) }
    val haptics = rememberHaptics()

    fun pickFile() {
        val dialog = java.awt.FileDialog(null as java.awt.Frame?, s.chooseFile, java.awt.FileDialog.LOAD)
        dialog.setFilenameFilter { _, name -> name.endsWith(".json") || name.endsWith(".txt") }
        dialog.isVisible = true
        val file = dialog.files.firstOrNull() ?: return
        val content = runCatching { file.readText() }.getOrNull()
        val ok = content != null && state.addTunnelFile(file.name, content)
        if (!ok) showImportError = true
    }

    GlassSheet(visible = visible, backdrop = backdrop, onDismiss = onDismiss) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = Layout.screenPadding)
                .padding(top = 12.dp, bottom = 6.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Text(s.fileTitle, style = manrope(19.sp, W.extraBold, Theme.text))
            Text(
                text = s.fileDesc,
                style = manrope(12.5.sp, W.medium, Theme.textSecondary).copy(lineHeight = 18.sp),
            )
        }

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(max = 240.dp)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = Layout.screenPadding, vertical = 10.dp),
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
                    onContextMenu = { pos ->
                        if (!file.isDefault) {
                            menuFile = file
                            menuPosition = pos
                        }
                    },
                )
            }
        }

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = Layout.screenPadding)
                .padding(top = 4.dp, bottom = Layout.screenPadding),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                text = s.rightClickHint,
                style = manrope(11.5.sp, W.semibold, Theme.text.copy(alpha = 0.32f)),
                textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth(),
            )

            PrimaryButton(
                text = s.chooseFile,
                icon = Icons.upload,
                height = 50.dp,
                cornerRadius = 16.dp,
                onClick = { pickFile() },
            )
        }
    }

    // Контекстное меню по правой кнопке мыши
    GlassContextMenu(
        visible = menuFile != null,
        position = menuPosition,
        backdrop = backdrop,
        onDismiss = { menuFile = null },
    ) {
        ContextMenuItem(text = s.del, destructive = true, icon = Icons.trash) {
            confirmDelete = menuFile
            menuFile = null
        }
    }

    GlassDialog(
        visible = confirmDelete != null,
        backdrop = backdrop,
        onDismiss = { confirmDelete = null },
    ) {
        Text(
            text = "${s.del}?",
            style = manrope(18.sp, W.extraBold, Theme.text),
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(8.dp))
        Text(
            text = confirmDelete?.name ?: "",
            style = manrope(13.5.sp, W.medium, Theme.textSecondary),
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(20.dp))
        Row(Modifier.fillMaxWidth()) {
            Box(
                modifier = Modifier
                    .weight(1f)
                    .height(46.dp)
                    .clip(RoundedCornerShape(15.dp))
                    .background(Color.White.copy(alpha = 0.07f))
                    .noRippleClickable { confirmDelete = null },
                contentAlignment = Alignment.Center,
            ) {
                Text(s.no, style = manrope(15.sp, W.bold, Theme.text))
            }
            Spacer(Modifier.width(10.dp))
            Box(
                modifier = Modifier
                    .weight(1f)
                    .height(46.dp)
                    .clip(RoundedCornerShape(15.dp))
                    .background(Theme.accentTint12)
                    .noRippleClickable {
                        confirmDelete?.let { state.deleteTunnelFile(it) }
                        confirmDelete = null
                    },
                contentAlignment = Alignment.Center,
            ) {
                Text(s.del, style = manrope(15.sp, W.bold, Theme.link))
            }
        }
    }

    GlassDialog(
        visible = showImportError,
        backdrop = backdrop,
        onDismiss = { showImportError = false },
    ) {
        Text(
            text = s.importError,
            style = manrope(17.sp, W.extraBold, Theme.text),
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(18.dp))
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(46.dp)
                .clip(RoundedCornerShape(15.dp))
                .background(Theme.accentTint12)
                .noRippleClickable { showImportError = false },
            contentAlignment = Alignment.Center,
        ) {
            Text("OK", style = manrope(15.sp, W.bold, Theme.link))
        }
    }
}

@Composable
private fun FileRow(
    file: TunnelFile,
    meta: String,
    isActive: Boolean,
    onSelect: () -> Unit,
    onContextMenu: (Offset) -> Unit,
) {
    val interaction = remember { MutableInteractionSource() }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .pressScale(interaction, 0.98f)
            .clip(RoundedCornerShape(16.dp))
            .background(if (isActive) Theme.accentTint10 else Color.White.copy(alpha = 0.045f))
            .rightClickable { onContextMenu(it) }
            .hoverable(interaction)
            .noRippleClickable(onClick = onSelect)
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(36.dp)
                .clip(RoundedCornerShape(10.dp))
                .background(Theme.accentTint14),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                imageVector = Icons.doc,
                contentDescription = null,
                tint = Theme.accentSoft,
                modifier = Modifier.size(17.dp),
            )
        }

        Spacer(Modifier.width(12.dp))

        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(1.dp)) {
            Text(
                text = file.name,
                style = manrope(14.sp, W.bold, Theme.text),
                maxLines = 1,
                overflow = TextOverflow.MiddleEllipsis,
            )
            Text(
                text = meta,
                style = manrope(12.sp, W.semibold, Theme.accentSoft),
            )
        }

        if (isActive) {
            Spacer(Modifier.width(8.dp))
            Icon(
                imageVector = Icons.check,
                contentDescription = null,
                tint = Theme.link,
                modifier = Modifier.size(18.dp),
            )
        }
    }
}

private fun fileMeta(file: TunnelFile, s: Strings): String {
    val entries = "${file.count} ${s.entries}"
    return if (file.isDefault) "${s.defaultMeta} · $entries" else entries
}

/**
 * Обновление приложения.
 *
 * Панель говорит, есть ли версия новее; кнопка скачивает установщик и
 * запускает его. Он ставится поверх — удалять приложение и входить заново
 * не нужно.
 */
@Composable
private fun UpdateCard(state: AppState) {
    val s = state.s
    val scope = rememberCoroutineScope()

    var info by remember { mutableStateOf(PanelUpdate.Info.none) }
    var checking by remember { mutableStateOf(true) }
    var downloading by remember { mutableStateOf(false) }
    var percent by remember { mutableStateOf(0) }
    var error by remember { mutableStateOf<String?>(null) }

    // Проверяем один раз при открытии настроек: чаще незачем, а кнопка
    // должна появляться сама, без ручного «проверить обновления».
    LaunchedEffect(Unit) {
        info = PanelUpdate.check(BuildInfo.VERSION)
        checking = false
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(20.dp))
            .background(Theme.card)
            .padding(16.dp),
    ) {
        Text(
            text = if (info.available) s.updateAvailable.format(info.version.orEmpty()) else s.updateNone,
            style = manrope(14.sp, W.semibold, Theme.text),
        )
        Spacer(Modifier.height(4.dp))
        Text(
            text = s.updateCurrent.format(BuildInfo.VERSION),
            style = manrope(12.sp, W.medium, Theme.textMuted),
        )

        info.changelog?.let { text ->
            Spacer(Modifier.height(8.dp))
            Text(text = text, style = manrope(12.sp, W.medium, Theme.textSecondary))
        }

        if (downloading) {
            Spacer(Modifier.height(10.dp))
            Text(
                text = s.updateDownloading.format(percent),
                style = manrope(12.sp, W.medium, Theme.textMuted),
            )
        }

        error?.let { text ->
            Spacer(Modifier.height(8.dp))
            Text(text = text, style = manrope(12.sp, W.medium, Theme.accentHover))
        }

        if (info.available && !checking) {
            Spacer(Modifier.height(12.dp))
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(46.dp)
                    .scaleClickable(0.98f, enabled = !downloading) {
                        val url = info.url ?: return@scaleClickable
                        downloading = true
                        error = null
                        scope.launch {
                            val result = PanelUpdate.download(url) { percent = it }
                            downloading = false
                            result.onFailure { error = it.message ?: s.updateFailed }
                        }
                    }
                    .clip(RoundedCornerShape(14.dp))
                    .background(Theme.accentTint08),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = if (downloading) s.updateDownloadingShort else s.updateButton,
                    style = manrope(14.sp, W.bold, Theme.link),
                )
            }
        }
    }
}
