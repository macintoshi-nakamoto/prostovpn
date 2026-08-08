package com.alisavpn.app

import androidx.compose.animation.Crossfade
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.shape.CircleShape
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
import androidx.compose.ui.draw.scale
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

private enum class HomePage { MAIN, SETTINGS, SUPPORT }

@Composable
fun HomeScreen(state: AppState) {
    var page by remember { mutableStateOf(HomePage.MAIN) }

    Crossfade(targetState = page, label = "home") { current ->
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
    val s = strings(state.lang)
    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding(),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 24.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Image(
                painter = painterResource(R.drawable.logo),
                contentDescription = "О приложении",
                modifier = Modifier
                    .size(width = 56.dp, height = 38.dp)
                    .clip(CircleShape)
                    .clickable { onOpenSupport() },
            )

            Spacer(Modifier.weight(1f))

            Icon(
                imageVector = Icons.gear,
                contentDescription = "Настройки",
                tint = Theme.text.copy(alpha = 0.5f),
                modifier = Modifier
                    .size(44.dp)
                    .clip(CircleShape)
                    .clickable { onOpenSettings() }
                    .padding(10.dp),
            )
        }

        Spacer(Modifier.weight(1f))

        PowerButton(state)

        Spacer(Modifier.height(28.dp))

        Text(
            text = when (state.phase) {
                Phase.OFF -> s.stateOff
                Phase.CONNECTING -> s.stateConnecting
                Phase.ON -> s.stateOn
            },
            color = Theme.text,
            fontSize = 22.sp,
            fontWeight = FontWeight.ExtraBold,
        )

        Spacer(Modifier.height(4.dp))

        Text(
            text = when (state.phase) {
                Phase.OFF -> s.tapToConnect
                Phase.CONNECTING -> ""
                Phase.ON -> state.formattedDuration
            },
            color = Theme.textMuted,
            fontSize = 14.sp,
            fontWeight = FontWeight.Medium,
            modifier = Modifier.height(20.dp),
        )

        Spacer(Modifier.weight(1f))
        Spacer(Modifier.weight(1f))

        ServerSheet(state)
    }
}

@Composable
private fun PowerButton(state: AppState) {
    val isOn = state.phase == Phase.ON
    val isBusy = state.phase == Phase.CONNECTING

    val interactionSource = remember { MutableInteractionSource() }
    val pressed by interactionSource.collectIsPressedAsState()
    val pressScale by animateFloatAsState(
        targetValue = if (pressed) 0.96f else 1f,
        animationSpec = spring(),
        label = "press",
    )

    val glowAlpha by animateFloatAsState(
        targetValue = if (isOn) 1f else 0f,
        animationSpec = tween(450),
        label = "glow",
    )

    val borderColor by animateColorAsState(
        targetValue = if (isOn) Theme.accent.copy(alpha = 0.8f) else Color.White.copy(alpha = 0.1f),
        animationSpec = tween(350),
        label = "border",
    )

    val glyphColor by animateColorAsState(
        targetValue = if (isOn || isBusy) Color.White else Theme.glyphOff,
        animationSpec = tween(350),
        label = "glyph",
    )

    val spin by rememberInfiniteTransition(label = "spin").animateFloat(
        initialValue = 0f,
        targetValue = 360f,
        animationSpec = infiniteRepeatable(tween(1100, easing = LinearEasing), RepeatMode.Restart),
        label = "spinAngle",
    )

    Box(
        modifier = Modifier
            .size(300.dp)
            .scale(pressScale),
        contentAlignment = Alignment.Center,
    ) {
        Canvas(Modifier.fillMaxSize()) {
            val center = Offset(size.width / 2, size.height / 2)
            val circleRadius = 88.dp.toPx()

            if (glowAlpha > 0f) {
                drawCircle(
                    brush = Brush.radialGradient(
                        colors = listOf(
                            Theme.accent.copy(alpha = 0.28f * glowAlpha),
                            Color.Transparent,
                        ),
                        center = center,
                        radius = 165.dp.toPx(),
                    ),
                    radius = 165.dp.toPx(),
                    center = center,
                )
            }

            drawCircle(
                color = Color.White.copy(alpha = 0.05f),
                radius = circleRadius,
                center = center,
            )
            drawCircle(
                color = borderColor,
                radius = circleRadius,
                center = center,
                style = Stroke(width = 1.5.dp.toPx()),
            )

            if (isBusy) {
                val arcRadius = 77.dp.toPx()
                rotate(spin, pivot = center) {
                    drawArc(
                        brush = Brush.sweepGradient(
                            colors = listOf(
                                Theme.accent.copy(alpha = 0.05f),
                                Theme.accent,
                            ),
                            center = center,
                        ),
                        startAngle = 30f,
                        sweepAngle = 160f,
                        useCenter = false,
                        style = Stroke(width = 2.5.dp.toPx(), cap = androidx.compose.ui.graphics.StrokeCap.Round),
                        topLeft = Offset(center.x - arcRadius, center.y - arcRadius),
                        size = androidx.compose.ui.geometry.Size(arcRadius * 2, arcRadius * 2),
                    )
                }
            }
        }

        Icon(
            imageVector = Icons.power,
            contentDescription = if (isOn) "Отключиться" else "Подключиться",
            tint = glyphColor,
            modifier = Modifier.size(64.dp),
        )

        Box(
            modifier = Modifier
                .size(176.dp)
                .clip(CircleShape)
                .clickable(interactionSource = interactionSource, indication = null) {
                    state.toggleConnection()
                }
        )
    }
}
