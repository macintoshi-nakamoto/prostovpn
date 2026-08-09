package com.prostovpn.app

import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
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

@Composable
fun SettingsScreen(state: AppState, onBack: () -> Unit) {
    val s = state.s
    var showLogoutConfirm by remember { mutableStateOf(false) }
    var showFileSheet by remember { mutableStateOf(false) }

    val backdrop = rememberBackdropState()

    Box(Modifier.fillMaxSize()) {
        Box(
            Modifier
                .fillMaxSize()
                .backdropSource(backdrop)
        ) {
            Box(
                Modifier
                    .fillMaxSize()
                    .background(Theme.background)
            )
            SoftTopOrb()
        }

        Column(
            modifier = Modifier
                .fillMaxSize()
                .statusBarsPadding()
                .padding(horizontal = 24.dp)
                .navigationBarsPadding()
                .padding(bottom = 16.dp),
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 8.dp),
            ) {
                GlassBackButton(backdrop = backdrop, onBack = onBack)
            }

            Text(
                text = s.settings,
                style = manrope(30.sp, W.extraBold, Theme.text),
                modifier = Modifier.padding(start = 2.dp, top = 6.dp, bottom = 22.dp),
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
    }

    if (showLogoutConfirm) {
        WarmAlertDialog(
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
    val haptics = rememberHaptics()
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
            .noRippleClickable {
                haptics.selection()
                onClick()
            }
            .padding(horizontal = 17.dp, vertical = 6.dp),
    ) {
        Text(text = title, style = manrope(13.sp, W.bold, fg))
    }
}

/** Мягкий тёплый ореол сверху — даёт стеклу, что преломлять. */
@Composable
fun SoftTopOrb() {
    androidx.compose.foundation.Canvas(Modifier.fillMaxSize()) {
        val center = androidx.compose.ui.geometry.Offset(size.width * 0.7f, 40.dp.toPx())
        val radius = 260.dp.toPx()
        drawCircle(
            brush = androidx.compose.ui.graphics.Brush.radialGradient(
                colors = listOf(Theme.accent.copy(alpha = 0.10f), Color.Transparent),
                center = center,
                radius = radius,
            ),
            radius = radius,
            center = center,
        )
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

// --- Шторка «Файл туннелирования» — iOS TunnelFileSheet ---

@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
private fun TunnelFileSheet(state: AppState, onDismiss: () -> Unit) {
    val s = state.s
    val context = LocalContext.current
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = false)
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

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState,
        containerColor = Color.Transparent,
        dragHandle = null,
        shape = RoundedCornerShape(topStart = 28.dp, topEnd = 28.dp),
        scrimColor = Color.Black.copy(alpha = 0.45f),
        contentWindowInsets = { WindowInsets(0.dp) },
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .background(Theme.sheetGradient)
                .navigationBarsPadding(),
        ) {
            Box(
                modifier = Modifier
                    .padding(top = 10.dp)
                    .size(width = 38.dp, height = 5.dp)
                    .clip(RoundedCornerShape(2.5.dp))
                    .background(Color.White.copy(alpha = 0.18f))
                    .align(Alignment.CenterHorizontally),
            )

            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 22.dp)
                    .padding(top = 20.dp, bottom = 6.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                Text(s.fileTitle, style = manrope(20.sp, W.extraBold, Theme.text))
                Text(
                    text = s.fileDesc,
                    style = manrope(13.sp, W.medium, Theme.textSecondary).copy(lineHeight = 19.sp),
                )
            }

            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f, fill = false)
                    .heightIn(max = 320.dp)
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = 22.dp, vertical = 10.dp),
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
                        onLongPress = {
                            if (!file.isDefault) fileToDelete = file
                        },
                    )
                }
            }

            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 22.dp)
                    .padding(top = 6.dp, bottom = 16.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                Text(
                    text = s.holdHint,
                    style = manrope(11.5.sp, W.semibold, Theme.text.copy(alpha = 0.3f)),
                    textAlign = TextAlign.Center,
                    modifier = Modifier.fillMaxWidth(),
                )

                PrimaryButton(
                    text = s.chooseFile,
                    icon = Icons.upload,
                    height = 50.dp,
                    cornerRadius = 16.dp,
                    onClick = {
                        filePicker.launch(arrayOf("application/json", "text/plain", "text/*"))
                    },
                )
            }
        }
    }

    if (showImportError) {
        WarmAlertDialog(
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
        WarmAlertDialog(
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
            .clip(RoundedCornerShape(16.dp))
            .background(if (isActive) Theme.accentTint10 else Color.White.copy(alpha = 0.04f))
            .combinedClickable(
                interactionSource = interaction,
                indication = null,
                onClick = onSelect,
                onLongClick = onLongPress,
            )
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

fun queryFileName(context: android.content.Context, uri: Uri): String? = runCatching {
    context.contentResolver.query(uri, null, null, null, null)?.use { cursor ->
        val index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
        if (index >= 0 && cursor.moveToFirst()) cursor.getString(index) else null
    }
}.getOrNull()
