package com.prostovpn.app

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedContentTransitionScope
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.VisibilityThreshold
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.util.lerp
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch

private enum class HomePage { MAIN, SETTINGS, SUPPORT }

@Composable
fun HomeScreen(state: AppState) {
    var page by remember { mutableStateOf(HomePage.MAIN) }

    BackHandler(enabled = page != HomePage.MAIN) { page = HomePage.MAIN }

    AnimatedContent(
        targetState = page,
        label = "home",
        transitionSpec = {
            val slideSpring = spring(
                dampingRatio = 0.92f,
                stiffness = 300f,
                visibilityThreshold = IntOffset.VisibilityThreshold,
            )
            if (targetState != HomePage.MAIN) {
                (slideIntoContainer(AnimatedContentTransitionScope.SlideDirection.Start, slideSpring) + fadeIn(tween(220)))
                    .togetherWith(
                        slideOutOfContainer(AnimatedContentTransitionScope.SlideDirection.Start, slideSpring, targetOffset = { it / 3 }) + fadeOut(tween(420))
                    )
            } else {
                (slideIntoContainer(AnimatedContentTransitionScope.SlideDirection.End, slideSpring, initialOffset = { it / 3 }) + fadeIn(tween(420)))
                    .togetherWith(
                        slideOutOfContainer(AnimatedContentTransitionScope.SlideDirection.End, slideSpring) + fadeOut(tween(220))
                    )
            }
        },
    ) { current ->
        when (current) {
            HomePage.MAIN -> MainPage(
                state = state,
                onOpenSettings = { page = HomePage.SETTINGS },
                onOpenSupport = { page = HomePage.SUPPORT },
            )
            HomePage.SETTINGS -> SettingsScreen(state, onBack = { page = HomePage.MAIN })
            HomePage.SUPPORT -> SupportScreen(state, onBack = { page = HomePage.MAIN })
        }
    }
}

@Composable
private fun MainPage(
    state: AppState,
    onOpenSettings: () -> Unit,
    onOpenSupport: () -> Unit,
) {
    val s = state.s
    val backdrop = rememberBackdropState()
    var showServers by remember { mutableStateOf(false) }
    var powerCenter by remember { mutableStateOf(Offset.Zero) }

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
            TopOrb()
            PowerGlow(state, backdrop, powerCenter)
        }

        Column(
            modifier = Modifier
                .fillMaxSize()
                .statusBarsPadding(),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Header(
                backdrop = backdrop,
                onOpenSettings = onOpenSettings,
                onOpenSupport = onOpenSupport,
                modifier = Modifier.fadeUp(),
            )

            Spacer(Modifier.weight(1f).heightIn(min = 12.dp))

            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                modifier = Modifier.fadeUp(80),
            ) {
                PowerButton(
                    state = state,
                    backdrop = backdrop,
                    onCenterChange = { powerCenter = it },
                )

                Spacer(Modifier.height(28.dp))

                StatusBlock(state)
            }

            Spacer(Modifier.weight(1f).heightIn(min = 12.dp))

            PanelBanners(
                state = state,
                modifier = Modifier
                    .padding(horizontal = 20.dp)
                    .padding(bottom = 10.dp),
            )

            CurrentServerCard(
                state = state,
                backdrop = backdrop,
                onOpen = { showServers = true },
                modifier = Modifier
                    .fadeUp(160)
                    .padding(horizontal = 20.dp)
                    .padding(bottom = 8.dp),
            )

            Spacer(
                Modifier
                    .navigationBarsPadding()
                    .height(0.dp)
            )
        }
    }

    if (showServers) {
        ServerListSheet(state = state, onDismiss = { showServers = false })
    }
}

@Composable
private fun Header(
    backdrop: BackdropState,
    onOpenSettings: () -> Unit,
    onOpenSupport: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 24.dp)
            .padding(top = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        GlassCircleButton(backdrop = backdrop, onClick = onOpenSupport) {
            LogoImage(
                modifier = Modifier.size(27.dp),
                glowAlpha = 0.45f,
            )
        }

        Spacer(Modifier.weight(1f))

        GlassCircleButton(backdrop = backdrop, onClick = onOpenSettings) {
            Icon(
                imageVector = Icons.gear,
                contentDescription = null,
                tint = Theme.text.copy(alpha = 0.75f),
                modifier = Modifier.size(23.dp),
            )
        }
    }
}

@Composable
private fun StatusBlock(state: AppState) {
    val s = state.s
    val statusText = when (state.phase) {
        Phase.OFF -> s.disconnected
        Phase.CONNECTING -> s.connectingTxt
        Phase.DISCONNECTING -> s.disconnectingTxt
        Phase.ON -> s.connected
    }

    val subText = when (state.phase) {
        Phase.OFF -> state.connectionError ?: s.tapToConnect
        Phase.CONNECTING, Phase.DISCONNECTING -> ""
        Phase.ON -> state.formattedDuration
    }

    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Box(Modifier.height(32.dp), contentAlignment = Alignment.Center) {
            AnimatedContent(
                targetState = statusText,
                label = "status",
                transitionSpec = {
                    (scaleIn(initialScale = 0.92f, animationSpec = Theme.spring(400)) +
                        fadeIn(Theme.spring(400)))
                        .togetherWith(
                            scaleOut(targetScale = 0.92f, animationSpec = Theme.spring(250)) +
                                fadeOut(Theme.spring(250))
                        )
                },
            ) { text ->
                Text(
                    text = text,
                    style = manrope(24.sp, W.extraBold, Theme.text, letterSpacing = 0.3.sp),
                )
            }
        }

        Spacer(Modifier.height(4.dp))

        val subStyle = manrope(14.sp, W.medium, Theme.textMuted).copy(
            fontFeatureSettings = "tnum",
        )

        Box(Modifier.heightIn(min = 20.dp), contentAlignment = Alignment.Center) {
            AnimatedContent(
                targetState = state.phase,
                label = "sub",
                transitionSpec = {
                    fadeIn(tween(280)).togetherWith(fadeOut(tween(180)))
                },
            ) { phase ->
                when (phase) {
                    Phase.OFF -> Text(
                        text = subText,
                        style = subStyle,
                        textAlign = TextAlign.Center,
                        modifier = Modifier.padding(horizontal = 28.dp),
                    )
                    Phase.CONNECTING, Phase.DISCONNECTING -> Text(text = "", style = subStyle)

                    Phase.ON -> RollingText(text = state.formattedDuration, style = subStyle)
                }
            }
        }
    }
}

@Composable
private fun TopOrb() {
    Canvas(Modifier.fillMaxSize()) {
        val center = Offset(size.width / 2f, -140.dp.toPx() + 200.dp.toPx())
        val radius = 200.dp.toPx()
        drawCircle(
            brush = Brush.radialGradient(
                colors = listOf(Theme.accent.copy(alpha = 0.14f), Color.Transparent),
                center = center,
                radius = radius,
            ),
            radius = radius,
            center = center,
        )
    }
}

@Composable
private fun PowerGlow(state: AppState, backdrop: BackdropState, center: Offset) {
    val glowAlpha by animateFloatAsState(
        targetValue = if (state.phase == Phase.ON) 1f else 0f,
        animationSpec = tween(450),
        label = "glow",
    )
    if (center == Offset.Zero) return
    Canvas(Modifier.fillMaxSize()) {
        if (glowAlpha > 0f) {
            val local = center - backdrop.positionInWindow
            val radius = 165.dp.toPx()
            drawCircle(
                brush = Brush.radialGradient(
                    colorStops = arrayOf(
                        0.24f to Theme.accent.copy(alpha = 0.25f * glowAlpha),
                        1f to Color.Transparent,
                    ),
                    center = local,
                    radius = radius,
                ),
                radius = radius,
                center = local,
            )
        }
    }
}

@Composable
private fun PowerButton(
    state: AppState,
    backdrop: BackdropState,
    onCenterChange: (Offset) -> Unit,
) {
    val isOn = state.phase == Phase.ON

    val isBusy = state.phase == Phase.CONNECTING || state.phase == Phase.DISCONNECTING
    val haptics = rememberHaptics()

    val interaction = remember { MutableInteractionSource() }
    val popScale = remember { Animatable(1f) }

    val powerFocus = remember { FocusRequester() }
    val isTv = rememberIsTv()
    LaunchedEffect(isTv) { if (isTv) runCatching { powerFocus.requestFocus() } }
    val bloom = remember { Animatable(0f) }

    LaunchedEffect(Unit) {
        var previous: Phase? = null
        snapshotFlow { state.phase }.collectLatest { phase ->
            val was = previous
            previous = phase
            if (phase == Phase.ON && was != null && was != Phase.ON) {
                haptics.success()

                launch {
                    bloom.snapTo(0.001f)
                    bloom.animateTo(1f, tween(750, easing = CubicBezierEasing(0.16f, 1f, 0.3f, 1f)))
                    bloom.snapTo(0f)
                }
                popScale.snapTo(0.92f)
                popScale.animateTo(
                    1.03f,
                    spring(dampingRatio = 0.55f, stiffness = 440f),
                )
                popScale.animateTo(1f, tween(180))
            } else if (phase != Phase.ON) {
                bloom.snapTo(0f)
                popScale.snapTo(1f)
            }
        }
    }

    val borderColor by androidx.compose.animation.animateColorAsState(
        targetValue = if (isOn) Theme.accent.copy(alpha = 0.8f) else Color.White.copy(alpha = 0.10f),
        animationSpec = tween(350),
        label = "ring",
    )
    val glyphColor by androidx.compose.animation.animateColorAsState(
        targetValue = if (isOn || isBusy) Color.White else Theme.glyphOff,
        animationSpec = tween(350),
        label = "glyph",
    )

    Box(
        modifier = Modifier.size(200.dp),
        contentAlignment = Alignment.Center,
    ) {
        Canvas(Modifier.fillMaxSize()) {
            val t = bloom.value
            if (t > 0f && t < 1f) {
                val radius = lerp(88.dp.toPx(), 168.dp.toPx(), t)
                drawCircle(
                    color = Theme.accent.copy(alpha = (1f - t) * 0.38f),
                    radius = radius,
                    center = center,
                    style = Stroke(width = lerp(2.5.dp.toPx(), 1.dp.toPx(), t)),
                )
            }
        }

        Box(
            modifier = Modifier
                .size(176.dp)
                .onGloballyPositioned {
                    val pos = it.positionInWindow()
                    onCenterChange(
                        Offset(
                            pos.x + it.size.width / 2f,
                            pos.y + it.size.height / 2f,
                        )
                    )
                }
                .graphicsLayer {
                    scaleX = popScale.value
                    scaleY = popScale.value
                }
                .pressScale(interaction, 0.96f)
                .softShadow(
                    color = Color.Black.copy(alpha = 0.30f),
                    blurRadius = 20.dp,
                    cornerRadius = 88.dp,
                    yOffset = 12.dp,
                )

                .tvFocusHighlight(CircleShape)
                .focusRequester(powerFocus)
                .clip(CircleShape)
                .liquidGlass(
                    backdrop = backdrop,
                    refractionHeight = 22.dp,
                    refractionAmount = 20.dp,
                )

                .graphicsLayer()
                .pressHighlight(interaction, 0.05f)
                .border(1.5.dp, borderColor, CircleShape)
                .clickable(interactionSource = interaction, indication = null) {
                    haptics.tap()
                    state.toggleConnection()
                },
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                imageVector = Icons.power,
                contentDescription = null,
                tint = glyphColor,
                modifier = Modifier.size(64.dp),
            )
        }

        androidx.compose.animation.AnimatedVisibility(
            visible = isBusy,
            enter = fadeIn(tween(220)),
            exit = fadeOut(tween(180)),
        ) {
            SpinnerRing(Modifier.size(176.dp))
        }
    }
}

@Composable
private fun SpinnerRing(modifier: Modifier = Modifier) {
    val angle by rememberInfiniteTransition(label = "spin").animateFloat(
        initialValue = 0f,
        targetValue = 360f,
        animationSpec = infiniteRepeatable(tween(1100, easing = LinearEasing)),
        label = "spinAngle",
    )

    Canvas(modifier) {
        rotate(angle) {
            drawArc(
                brush = Brush.sweepGradient(
                    colorStops = arrayOf(
                        0f to Color.Transparent,
                        0.1f to Color.Transparent,
                        0.55f to Theme.accent.copy(alpha = 0.15f),
                        1f to Theme.accent,
                    ),
                ),
                startAngle = 10f,
                sweepAngle = 340f,
                useCenter = false,
                style = Stroke(width = 2.5.dp.toPx(), cap = StrokeCap.Round),
            )
        }
    }
}

@Composable
private fun PanelBanners(state: AppState, modifier: Modifier = Modifier) {
    val showUpdate = state.updates.mandatory
    val showNotice = state.panelNotice.isNotEmpty()
    val showRenew = state.trafficLow || state.expiresSoon
    if (!showUpdate && !showNotice && !showRenew) return

    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        if (showUpdate) MandatoryUpdateBanner(state)
        if (showNotice) NoticeCard(state.panelNotice)
        if (showRenew) RenewBanner(state)
    }
}

@Composable
private fun BannerCard(content: @Composable androidx.compose.foundation.layout.ColumnScope.() -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(16.dp))
            .background(Theme.accentTint12)
            .padding(horizontal = 14.dp, vertical = 12.dp),
        content = content,
    )
}

@Composable
private fun NoticeCard(text: String) {
    BannerCard {
        Text(
            text = text,
            style = manrope(12.5.sp, W.semibold, Theme.accentSoft).copy(lineHeight = 17.sp),
        )
    }
}

@Composable
private fun RenewBanner(state: AppState) {
    val s = state.s
    val context = LocalContext.current

    val headline = if (state.trafficLow) {
        s.trafficLowWarn.format(formatBytes(state.trafficLeftBytes.coerceAtLeast(0), s))
    } else {
        s.expiresSoonWarn.format(dayPhrase(state.subscriptionDaysLeft, state.lang, s))
    }

    BannerCard {
        Text(
            text = headline,
            style = manrope(12.5.sp, W.semibold, Theme.accentSoft).copy(lineHeight = 17.sp),
        )
        if (state.renewUrl.isNotEmpty()) {
            Spacer(Modifier.height(10.dp))
            PrimaryButton(
                text = s.renew,
                height = 42.dp,
                cornerRadius = 13.dp,
                onClick = { openRenewUrl(context, state.renewUrl) },
            )
        }
    }
}

@Composable
private fun MandatoryUpdateBanner(state: AppState) {
    val s = state.s
    val updates = state.updates

    BannerCard {
        Text(
            text = s.updateAvailable.format(updates.info?.version.orEmpty()),
            style = manrope(13.sp, W.bold, Theme.text),
        )
        Spacer(Modifier.height(2.dp))
        Text(
            text = s.updateMandatory,
            style = manrope(12.sp, W.medium, Theme.textMuted),
        )
        Spacer(Modifier.height(10.dp))
        PrimaryButton(

            text = when (updates.stage) {
                UpdateManager.Stage.DOWNLOADING -> s.updateDownloading.format(updates.percent)
                UpdateManager.Stage.INSTALLING -> s.updateInstalling
                else -> s.updateButton
            },
            height = 42.dp,
            cornerRadius = 13.dp,
            onClick = { updates.install() },
        )
    }
}

private fun openRenewUrl(context: Context, url: String) {
    runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) }
}

private fun formatBytes(bytes: Long, s: Strings): String {
    if (bytes <= 0) return "0 ${s.unitMb}"
    val gb = bytes / 1024.0 / 1024.0 / 1024.0
    if (gb >= 1) return String.format("%.1f %s", gb, s.unitGb)
    return String.format("%.0f %s", bytes / 1024.0 / 1024.0, s.unitMb)
}

private fun dayPhrase(count: Int, lang: String, s: Strings): String {
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
