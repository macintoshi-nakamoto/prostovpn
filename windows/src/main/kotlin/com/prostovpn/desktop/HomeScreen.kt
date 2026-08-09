package com.prostovpn.desktop

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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
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
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.util.lerp
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch

private enum class HomePage { MAIN, SETTINGS, SUPPORT }

@Composable
fun HomeScreen(
    state: AppState,
    windowControls: @Composable () -> Unit,
    drag: @Composable (@Composable () -> Unit) -> Unit,
) {
    var page by remember { mutableStateOf(HomePage.MAIN) }

    AnimatedContent(
        targetState = page,
        label = "home",
        transitionSpec = {
            // push/pop, как в iOS NavigationStack: пружинный слайд с параллаксом
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
                windowControls = windowControls,
                drag = drag,
            )
            HomePage.SETTINGS -> SettingsScreen(
                state = state,
                onBack = { page = HomePage.MAIN },
                windowControls = windowControls,
                drag = drag,
            )
            HomePage.SUPPORT -> SupportScreen(
                state = state,
                onBack = { page = HomePage.MAIN },
                windowControls = windowControls,
                drag = drag,
            )
        }
    }
}

@Composable
private fun MainPage(
    state: AppState,
    onOpenSettings: () -> Unit,
    onOpenSupport: () -> Unit,
    windowControls: @Composable () -> Unit,
    drag: @Composable (@Composable () -> Unit) -> Unit,
) {
    val s = state.s
    val backdrop = rememberBackdropState()
    var showServers by remember { mutableStateOf(false) }
    var powerCenter by remember { mutableStateOf(Offset.Zero) }

    Box(Modifier.fillMaxSize()) {
        // Фон, который сэмплируют стеклянные элементы: градиент, верхний ореол
        // и свечение вокруг кнопки питания.
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
                ,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Header(
                backdrop = backdrop,
                onOpenSettings = onOpenSettings,
                onOpenSupport = onOpenSupport,
                windowControls = windowControls,
                drag = drag,
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

            CurrentServerCard(
                state = state,
                backdrop = backdrop,
                onOpen = { showServers = true },
                modifier = Modifier
                    .fadeUp(160)
                    .padding(horizontal = Layout.screenPadding)
                    .padding(bottom = Layout.screenPadding),
            )
        }

        ServerListSheet(
            state = state,
            visible = showServers,
            backdrop = backdrop,
            onDismiss = { showServers = false },
        )
    }
}

@Composable
private fun Header(
    backdrop: BackdropState,
    onOpenSettings: () -> Unit,
    onOpenSupport: () -> Unit,
    windowControls: @Composable () -> Unit,
    drag: @Composable (@Composable () -> Unit) -> Unit,
    modifier: Modifier = Modifier,
) {
    // Отступ сверху равен боковому — шапка «дышит» одинаково со всех сторон,
    // кнопки окна стоят в том же ряду и ничего не перекрывают.
    drag {
        Row(
            modifier = modifier
                .fillMaxWidth()
                .padding(horizontal = Layout.screenPadding)
                .padding(top = Layout.topPadding),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            GlassCircleButton(backdrop = backdrop, onClick = onOpenSupport) {
                LogoImage(
                    modifier = Modifier.size(26.dp),
                    glowAlpha = 0.45f,
                )
            }

            Spacer(Modifier.weight(1f))

            GlassCircleButton(backdrop = backdrop, onClick = onOpenSettings) {
                Icon(
                    imageVector = Icons.gear,
                    contentDescription = null,
                    tint = Theme.text.copy(alpha = 0.75f),
                    modifier = Modifier.size(22.dp),
                )
            }

            Spacer(Modifier.width(12.dp))

            windowControls()
        }
    }
}

@Composable
private fun StatusBlock(state: AppState) {
    val s = state.s
    val statusText = when (state.phase) {
        Phase.OFF -> s.disconnected
        Phase.CONNECTING -> s.connectingTxt
        Phase.ON -> s.connected
    }
    val subText = when (state.phase) {
        Phase.OFF -> s.tapToConnect
        Phase.CONNECTING -> ""
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
        Box(Modifier.height(20.dp), contentAlignment = Alignment.Center) {
            AnimatedContent(
                targetState = state.phase,
                label = "sub",
                transitionSpec = {
                    fadeIn(tween(280)).togetherWith(fadeOut(tween(180)))
                },
            ) { phase ->
                when (phase) {
                    Phase.OFF -> Text(text = subText, style = subStyle)
                    Phase.CONNECTING -> Text(text = "", style = subStyle)
                    // Цифры таймера «прокручиваются» — как numericText() в iOS
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
            // центр кнопки переводим из оконных координат в локальные координаты фона,
            // чтобы glow не съезжал во время слайд-переходов между экранами
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
    val isBusy = state.phase == Phase.CONNECTING
    val haptics = rememberHaptics()

    val interaction = remember { MutableInteractionSource() }
    val popScale = remember { Animatable(1f) }
    val bloom = remember { Animatable(0f) }

    // «Салют» только на реальном переходе в ON (не при возврате на экран,
    // когда VPN уже подключён); при обрыве соединения анимации сбрасываются.
    LaunchedEffect(Unit) {
        var previous: Phase? = null
        snapshotFlow { state.phase }.collectLatest { phase ->
            val was = previous
            previous = phase
            if (phase == Phase.ON && was != null && was != Phase.ON) {
                haptics.success()
                // Кольцо-вспышка расходится от кнопки в момент подключения
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
        // bloom.value читается только в фазе рисования — без рекомпозиций на каждый кадр
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

        // Стеклянный диск
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
                    // чтение в graphicsLayer-блоке — без рекомпозиции на кадрах пружины
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
                .clip(CircleShape)
                .liquidGlass(
                    backdrop = backdrop,
                    refractionHeight = 22.dp,
                    refractionAmount = 20.dp,
                )
                // отдельный слой: подсветка/кайма/глиф не пересчитывают blur стекла
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
