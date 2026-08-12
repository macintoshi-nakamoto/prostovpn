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
 * Панель говорит, есть ли версия новее; одно нажатие — и приложение
 * скачивает её, ставит и открывается уже новым. Мастера установки человек
 * не видит и запускать приложение заново не должен: единственное, что от
 * него нужно, — согласиться на права администратора.
 *
 * Состояние живёт в AppState: значок на шестерёнке появляется до того, как
 * в настройки зайдут, а установка не должна обрываться от ухода с экрана.
 */
@Composable
private fun UpdateCard(state: AppState) {
    val s = state.s
    val u = updateStrings(state.lang)

    val stage = state.updateStage
    val checking = stage == UpdateStage.CHECKING
    val busy = stage == UpdateStage.DOWNLOADING || stage == UpdateStage.INSTALLING
    val failure = state.updateCheck?.exceptionOrNull()
    val fresh = state.updateInfo

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(20.dp))
            .background(Theme.card)
            .padding(16.dp),
    ) {
        Text(
            /*
            Четыре состояния, а не два: раньше «установлена последняя версия»
            показывалось и пока проверка идёт, и когда она провалилась, —
            то есть чаще всего это было неправдой.
            */
            text = when {
                checking -> u.checking
                failure != null -> u.checkFailed.format(checkReason(failure, u))
                fresh != null -> s.updateAvailable.format(fresh.version.orEmpty())
                else -> s.updateNone
            },
            style = manrope(14.sp, W.semibold, Theme.text),
        )
        Spacer(Modifier.height(4.dp))
        Text(
            text = s.updateCurrent.format(BuildInfo.VERSION),
            style = manrope(12.sp, W.medium, Theme.textMuted),
        )

        // Списка изменений здесь нет намеренно: он занимал половину экрана
        // настроек и в состоянии «установлена последняя версия» рассказывал
        // о том, что и так уже стоит.

        if (busy) {
            Spacer(Modifier.height(10.dp))
            Text(
                text = if (stage == UpdateStage.INSTALLING) {
                    u.installing
                } else {
                    s.updateDownloading.format(state.updatePercent)
                },
                style = manrope(12.sp, W.medium, Theme.textMuted),
            )
        }

        state.updateFailure?.let { problem ->
            Spacer(Modifier.height(8.dp))
            Text(
                text = downloadReason(problem, s, u),
                style = manrope(12.sp, W.medium, Theme.accentHover),
            )
        }

        if (!checking && failure != null) {
            Spacer(Modifier.height(12.dp))
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(46.dp)
                    .scaleClickable(0.98f) { state.checkUpdate() }
                    .clip(RoundedCornerShape(14.dp))
                    .background(Theme.accentTint08),
                contentAlignment = Alignment.Center,
            ) {
                Text(text = u.retry, style = manrope(14.sp, W.bold, Theme.link))
            }
        }

        if (fresh != null) {
            Spacer(Modifier.height(12.dp))
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(46.dp)
                    .scaleClickable(0.98f, enabled = !busy) { state.installUpdate() }
                    .clip(RoundedCornerShape(14.dp))
                    .background(Theme.accentTint08),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = when (stage) {
                        UpdateStage.DOWNLOADING -> s.updateDownloadingShort
                        UpdateStage.INSTALLING -> u.installing
                        else -> s.updateButton
                    },
                    style = manrope(14.sp, W.bold, Theme.link),
                )
            }

            Spacer(Modifier.height(8.dp))
            Text(
                text = u.restartHint,
                style = manrope(11.5.sp, W.medium, Theme.textFaint).copy(lineHeight = 16.sp),
                textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth(),
            )
        }
    }
}

/**
 * Тексты карточки обновления.
 *
 * Живут рядом с ней, а не в общем Strings: набор меняется вместе с логикой
 * проверки и больше нигде не нужен.
 */
private class UpdateStrings(
    val checking: String,
    val checkFailed: String,
    val reasonNetwork: String,
    val reasonPanel: String,
    val reasonServer: String,
    val reasonAnswer: String,
    val retry: String,
    val noChecksum: String,
    val insecure: String,
    val corrupted: String,
    val launchFailed: String,
    val cancelled: String,
    val installing: String,
    val restartHint: String,
)

private val UPDATE_RU = UpdateStrings(
    checking = "Проверяем обновления…",
    checkFailed = "Не удалось проверить обновления: %s",
    reasonNetwork = "нет связи",
    reasonPanel = "сервис обновлений недоступен",
    reasonServer = "сервер ответил %d",
    reasonAnswer = "непонятный ответ",
    retry = "Проверить снова",
    noChecksum = "Панель не сообщила контрольную сумму — обновитесь вручную с сайта",
    insecure = "Ссылка на установщик небезопасна — обновитесь вручную с сайта",
    corrupted = "Файл обновления не совпал с обещанным — скачивание отменено",
    launchFailed = "Не удалось запустить установку",
    cancelled = "Обновление отменено: на установку нужны права администратора",
    installing = "Устанавливаем…",
    restartHint = "Приложение закроется и откроется заново уже обновлённым",
)

private val UPDATE_EN = UpdateStrings(
    checking = "Checking for updates…",
    checkFailed = "Could not check for updates: %s",
    reasonNetwork = "no connection",
    reasonPanel = "the update service is unavailable",
    reasonServer = "the server replied %d",
    reasonAnswer = "unexpected reply",
    retry = "Check again",
    noChecksum = "The panel did not provide a checksum — update manually from the site",
    insecure = "The installer link is not secure — update manually from the site",
    corrupted = "The downloaded file does not match — the download was discarded",
    launchFailed = "Could not start the installation",
    cancelled = "Update cancelled: installing needs administrator rights",
    installing = "Installing…",
    restartHint = "The app will close and open again already updated",
)

private fun updateStrings(lang: String): UpdateStrings = if (lang == "en") UPDATE_EN else UPDATE_RU

/** Почему проверка не удалась — адрес панели в текст не попадает. */
private fun checkReason(error: Throwable, u: UpdateStrings): String {
    val problem = (error as? PanelUpdate.UpdateProblem) ?: return u.reasonNetwork
    return when (problem.problem) {
        PanelUpdate.Problem.PANEL_OUTDATED -> u.reasonPanel
        PanelUpdate.Problem.SERVER -> u.reasonServer.format(problem.httpCode)
        PanelUpdate.Problem.BAD_ANSWER -> u.reasonAnswer
        else -> u.reasonNetwork
    }
}

/** Почему скачивание или установка не удались. */
private fun downloadReason(error: Throwable, s: Strings, u: UpdateStrings): String =
    when ((error as? PanelUpdate.UpdateProblem)?.problem) {
        PanelUpdate.Problem.NO_CHECKSUM -> u.noChecksum
        PanelUpdate.Problem.INSECURE_URL -> u.insecure
        PanelUpdate.Problem.CORRUPTED -> u.corrupted
        PanelUpdate.Problem.LAUNCH -> u.launchFailed
        PanelUpdate.Problem.CANCELLED -> u.cancelled
        // Текст исключения человеку ничего не объясняет, а адрес панели из
        // него утекает на экран.
        else -> s.updateFailed
    }
