package com.prostovpn.app

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
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
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.time.LocalDate
import java.util.Locale

@Composable
fun MainPage(
    state: AppState,
    onOpenCountries: () -> Unit,
    onOpenSettings: () -> Unit,
    onOpenSupport: () -> Unit,
) {
    val s = state.s
    val plate = state.plateState
    val notices = buildNotices(state, s)
    var showNotices by remember { mutableStateOf(false) }

    LaunchedEffect(state.panelServers.size) { state.refreshPings() }

    Box(Modifier.fillMaxSize()) {
        Box(Modifier.fillMaxSize().background(Theme.canvas))
        CanvasGlow(color = plateGlow(plate), strength = 1f)

        Column(
            modifier = Modifier
                .fillMaxSize()
                .statusBarsPadding()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            AccountHeader(
                state = state,
                badge = notices.isNotEmpty(),
                onBell = { showNotices = true },
                modifier = Modifier.fadeUp(),
            )

            ConnectionPlate(
                state = plate,
                title = plateTitle(state, plate),
                subtitle = plateSubtitle(state, plate),
                subtitleAlt = if (plate == PlateState.CONNECTING) s.waitingNode else null,
                chip = plateChip(state, plate),
                chipTabular = plate == PlateState.ON,
                modifier = Modifier.fadeUp(60),
                onClick = { state.toggleConnection() },
            )

            AnimatedVisibility(
                visible = plate == PlateState.ERROR,
                enter = expandVertically(tween(240)) + fadeIn(tween(240)),
                exit = shrinkVertically(tween(180)) + fadeOut(tween(120)),
            ) {
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    PrimaryPill(
                        text = s.retry,
                        height = 52.dp,
                        modifier = Modifier.weight(1f),
                        onClick = {
                            state.dismissConnectionError()
                            state.toggleConnection()
                        },
                    )
                    GhostPill(
                        text = s.changeCountry,
                        height = 52.dp,
                        modifier = Modifier.weight(1f),
                        onClick = {
                            state.dismissConnectionError()
                            onOpenCountries()
                        },
                    )
                }
            }

            StatRow(state = state, plate = plate, onOpenCountries = onOpenCountries)

            if (plate == PlateState.ON) {
                CurrentCountryRow(state = state, onClick = onOpenCountries)
            }

            SplitTunnelCard(state)

            Banners(state)

            if (plate != PlateState.ON) {
                RowsCard {
                    MenuRow(
                        title = s.settings,
                        icon = Icons.gear,
                        onClick = onOpenSettings,
                    )
                    HairLine()
                    MenuRow(
                        title = s.supportTitle,
                        icon = Icons.help,
                        onClick = onOpenSupport,
                    )
                }
            }

            Spacer(Modifier.navigationBarsPadding().height(96.dp))
        }
    }

    if (showNotices) {
        NoticesSheet(state = state, items = notices, onDismiss = { showNotices = false })
    }
}

// ─── Шапка ─────────────────────────────────────────────────────────────────

@Composable
private fun AccountHeader(
    state: AppState,
    badge: Boolean,
    onBell: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val name = state.accountName.ifEmpty { "Prosto VPN" }
    Row(
        modifier = modifier
            .fillMaxWidth()
            .height(56.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(36.dp)
                .clip(CircleShape)
                .background(Theme.brandGradient),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = name.take(1).uppercase(),
                style = pro(16.sp, W.bold, Color.White, display = true),
            )
        }
        Spacer(Modifier.width(12.dp))
        Text(
            text = name,
            style = pro(16.sp, W.semibold, Theme.text),
            maxLines = 1,
        )
        Spacer(Modifier.weight(1f))
        Box {
            GlassCircleButton(onClick = onBell) {
                Icon(
                    imageVector = Icons.bell,
                    contentDescription = null,
                    tint = Theme.textMuted,
                    modifier = Modifier.size(19.dp),
                )
            }
            if (badge) {
                Box(
                    Modifier
                        .align(Alignment.TopEnd)
                        .padding(2.dp)
                        .size(9.dp)
                        .clip(CircleShape)
                        .background(Theme.accent),
                )
            }
        }
    }
}

// ─── Плитки ────────────────────────────────────────────────────────────────

@Composable
private fun StatRow(state: AppState, plate: PlateState, onOpenCountries: () -> Unit) {
    val s = state.s
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fadeUp(110)) {
        if (plate == PlateState.ON) {
            StatTile(
                label = s.downloaded,
                value = trafficValue(state.sessionRx, s),
                caption = s.perSession,
                modifier = Modifier.weight(1f),
            )
            StatTile(
                label = s.uploaded,
                value = trafficValue(state.sessionTx, s),
                caption = s.perSession,
                modifier = Modifier.weight(1f),
            )
        } else {
            val server = state.currentServer
            StatTile(
                label = s.locationLabel,
                value = server?.code?.uppercase() ?: "—",
                caption = listOfNotNull(
                    server?.name?.takeIf { it.isNotEmpty() },
                    state.pingFor(server)?.let { "$it ${s.ms}" },
                ).joinToString(" · ").ifEmpty { s.bestServer },
                modifier = Modifier.weight(1f),
                onClick = onOpenCountries,
                trailing = { CountryFlag(code = server?.code, size = 26.dp) },
            )
            StatTile(
                label = s.subscriptionLabel,
                value = dayPhrase(state.subscriptionDaysLeft, state.lang, s),
                caption = if (state.expiresSoon) s.endsSoon else untilText(state.subscriptionDaysLeft, state.lang, s),
                captionColor = if (state.expiresSoon) Theme.warningText else Theme.textFaint,
                modifier = Modifier.weight(1f),
            )
        }
    }
}

@Composable
private fun StatTile(
    label: String,
    value: String,
    caption: String,
    modifier: Modifier = Modifier,
    captionColor: Color = Theme.textFaint,
    onClick: (() -> Unit)? = null,
    trailing: (@Composable () -> Unit)? = null,
) {
    Column(
        modifier = modifier
            .height(104.dp)
            .glass(R2.card)
            .then(if (onClick != null) Modifier.flashClickable(onClick = onClick) else Modifier)
            .padding(horizontal = 16.dp, vertical = 14.dp),
        verticalArrangement = Arrangement.SpaceBetween,
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
            Text(label, style = pro(12.sp, W.semibold, Theme.textFaint))
            Spacer(Modifier.weight(1f))
            trailing?.invoke()
        }
        Column {
            Text(
                text = value,
                style = pro(24.sp, W.bold, Theme.text, tracking = em(24.sp, -0.025f), tabular = true),
                maxLines = 1,
            )
            Text(
                text = caption,
                style = pro(12.sp, W.regular, captionColor),
                maxLines = 1,
            )
        }
    }
}

@Composable
private fun CurrentCountryRow(state: AppState, onClick: () -> Unit) {
    val server = state.currentServer
    val s = state.s
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(76.dp)
            .glass(R2.card)
            .flashClickable(onClick = onClick)
            .padding(horizontal = 18.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        CountryFlag(code = server?.code, size = 34.dp)
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(
                text = server?.name?.ifEmpty { s.bestServer } ?: s.bestServer,
                style = pro(16.sp, W.semibold, Theme.text),
                maxLines = 1,
            )
            Text(
                text = listOfNotNull(
                    server?.sub?.takeIf { it.isNotEmpty() },
                    state.pingFor(server)?.let { "$it ${s.ms}" },
                ).joinToString(" · "),
                style = pro(13.sp, W.regular, Theme.textFaint, tabular = true),
                maxLines = 1,
            )
        }
        Icon(
            imageVector = Icons.chevronRight,
            contentDescription = null,
            tint = Theme.textFaint,
            modifier = Modifier.size(17.dp),
        )
    }
}

@Composable
private fun SplitTunnelCard(state: AppState) {
    val s = state.s
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(76.dp)
            .glass(R2.card)
            .padding(horizontal = 18.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
            Text(s.split, style = pro(16.sp, W.semibold, Theme.text), maxLines = 1)
            Text(s.splitShort, style = pro(13.sp, W.regular, Theme.textFaint), maxLines = 1)
        }
        Spacer(Modifier.width(12.dp))
        ProToggle(checked = state.splitTunnelEnabled) { state.changeSplitTunnel(it) }
    }
}

// ─── Баннеры и уведомления ─────────────────────────────────────────────────

@Composable
private fun Banners(state: AppState) {
    val s = state.s
    val context = LocalContext.current
    val updates = state.updates

    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        if (updates.mandatory) {
            Banner(
                title = s.updateAvailable.format(updates.info?.version.orEmpty()),
                body = s.updateMandatory,
                tone = BannerTone.ACCENT,
                actionText = when (updates.stage) {
                    UpdateManager.Stage.DOWNLOADING -> s.updateDownloading.format(updates.percent)
                    UpdateManager.Stage.INSTALLING -> s.updateInstalling
                    else -> s.updateButton
                },
                onAction = { updates.install() },
            )
        }
        if (state.panelNotice.isNotEmpty()) {
            Banner(title = state.panelNotice, tone = BannerTone.INFO)
        }
        if (state.trafficLow || state.expiresSoon) {
            val headline = if (state.trafficLow) {
                s.trafficLowWarn.format(formatBytes(state.trafficLeftBytes.coerceAtLeast(0), s))
            } else {
                s.expiresSoonWarn.format(dayPhrase(state.subscriptionDaysLeft, state.lang, s))
            }
            Banner(
                title = headline,
                tone = BannerTone.WARNING,
                actionText = if (state.renewUrl.isNotEmpty()) s.renew else null,
                onAction = { openUrl(context, state.renewUrl) },
            )
        }
    }
}

data class NoticeItem(val title: String, val body: String?, val tone: BannerTone)

/** Что приложению есть сказать прямо сейчас: обновление, трафик, срок, связь. */
private fun buildNotices(state: AppState, s: Strings): List<NoticeItem> {
    val out = mutableListOf<NoticeItem>()
    state.updates.info?.let { info ->
        if (state.updates.stage == UpdateManager.Stage.AVAILABLE || state.updates.mandatory) {
            out += NoticeItem(
                title = s.updateAvailable.format(info.version),
                body = if (state.updates.mandatory) s.updateMandatory else null,
                tone = BannerTone.ACCENT,
            )
        }
    }
    if (state.panelNotice.isNotEmpty()) {
        out += NoticeItem(state.panelNotice, null, BannerTone.INFO)
    }
    if (state.trafficLow) {
        out += NoticeItem(
            s.trafficLowWarn.format(formatBytes(state.trafficLeftBytes.coerceAtLeast(0), s)),
            null,
            BannerTone.WARNING,
        )
    }
    if (state.expiresSoon) {
        out += NoticeItem(
            s.expiresSoonWarn.format(dayPhrase(state.subscriptionDaysLeft, state.lang, s)),
            null,
            BannerTone.WARNING,
        )
    }
    return out
}

@Composable
private fun NoticesSheet(state: AppState, items: List<NoticeItem>, onDismiss: () -> Unit) {
    val s = state.s
    val context = LocalContext.current

    SheetShell(title = s.notices, subtitle = null, onDismiss = onDismiss) {
        if (items.isEmpty()) {
            Text(
                text = s.noNotices,
                style = pro(14.sp, W.regular, Theme.textMuted),
                modifier = Modifier.padding(vertical = 18.dp),
            )
        } else {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                items.forEach { notice ->
                    Banner(title = notice.title, body = notice.body, tone = notice.tone)
                }
            }
        }
        Spacer(Modifier.height(16.dp))
        PrimaryPill(text = s.cabinet, onClick = {
            openUrl(context, state.renewUrl.ifEmpty { "https://prostovpn.cc/account" })
            onDismiss()
        })
    }
}

// ─── Тексты состояния ──────────────────────────────────────────────────────

@Composable
private fun plateGlow(state: PlateState): Color = when (state) {
    PlateState.OFF -> if (Theme.isLight) Color(0x22FA4C16) else Color.White.copy(alpha = 0.10f)
    PlateState.CONNECTING -> Theme.accent.copy(alpha = 0.26f)
    PlateState.ON -> Theme.accent.copy(alpha = 0.55f)
    PlateState.ERROR -> Theme.error.copy(alpha = 0.28f)
}

private fun plateTitle(state: AppState, plate: PlateState): String = when (plate) {
    PlateState.OFF -> state.s.disconnected
    PlateState.CONNECTING ->
        if (state.phase == Phase.DISCONNECTING) state.s.disconnectingTxt else state.s.connectingTitle
    PlateState.ON -> state.s.connected
    PlateState.ERROR -> state.s.errorTitle
}

private fun plateSubtitle(state: AppState, plate: PlateState): String? {
    val where = state.currentServer
    val place = listOfNotNull(
        where?.name?.takeIf { it.isNotEmpty() },
        where?.sub?.takeIf { it.isNotEmpty() },
    ).joinToString(" · ")
    return when (plate) {
        PlateState.OFF -> null
        PlateState.CONNECTING -> state.s.checkingNode.format(
            where?.sub?.takeIf { it.isNotEmpty() } ?: where?.name.orEmpty()
        ).trim().trimEnd('·', ' ')
        PlateState.ON -> place.ifEmpty { null }
        PlateState.ERROR -> state.connectionError ?: state.s.errorUnknown
    }
}

private fun plateChip(state: AppState, plate: PlateState): String? = when (plate) {
    PlateState.ON -> state.formattedDuration
    PlateState.ERROR -> state.s.errorChip
    // Пока подключаемся, таймер сессии врал бы: он считает прошлую связь.
    PlateState.OFF, PlateState.CONNECTING ->
        if (state.subscriptionDaysLeft > 0) {
            dayPhrase(state.subscriptionDaysLeft, state.lang, state.s)
        } else {
            null
        }
}

private val MONTHS_RU = listOf(
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)

private val MONTHS_EN = listOf(
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

/**
 * «до 18 сентября».
 *
 * Названия месяцев берём свои: системный формат отдаёт именительный падеж
 * («18 сентябрь»), а на десугаринге ещё и зависит от прошивки.
 */
private fun untilText(daysLeft: Int, lang: String, s: Strings): String {
    if (daysLeft <= 0) return ""
    return runCatching {
        val date = LocalDate.now().plusDays(daysLeft.toLong())
        val months = if (lang == "en") MONTHS_EN else MONTHS_RU
        val month = months[date.monthValue - 1]
        val text = if (lang == "en") "$month ${date.dayOfMonth}" else "${date.dayOfMonth} $month"
        s.untilDate.format(text)
    }.getOrDefault("")
}

private fun trafficValue(bytes: Long, s: Strings): String =
    if (bytes < 0) "—" else formatBytes(bytes, s)

fun openUrl(context: Context, url: String) {
    if (url.isEmpty()) return
    runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) }
}

fun formatBytes(bytes: Long, s: Strings): String {
    if (bytes <= 0) return "0 ${s.unitMb}"
    val gb = bytes / 1024.0 / 1024.0 / 1024.0
    if (gb >= 1) return String.format(Locale.US, "%.2f %s", gb, s.unitGb).replace('.', ',')
    return String.format(Locale.US, "%.0f %s", bytes / 1024.0 / 1024.0, s.unitMb)
}

fun dayPhrase(count: Int, lang: String, s: Strings): String {
    if (lang == "en") return "$count " + if (count == 1) s.dayOne else s.dayMany
    val n = kotlin.math.abs(count) % 100
    val n1 = n % 10
    val word = when {
        n in 11..19 -> s.dayMany
        n1 in 2..4 -> s.dayFew
        n1 == 1 -> s.dayOne
        else -> s.dayMany
    }
    return "$count $word"
}
