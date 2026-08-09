package com.prostovpn.desktop

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.animateFloatAsState
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
import androidx.compose.foundation.hoverable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsHoveredAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.window.WindowDraggableArea
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.PointerIcon
import androidx.compose.ui.input.pointer.pointerHoverIcon
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Window
import androidx.compose.ui.window.WindowPosition
import androidx.compose.ui.window.application
import androidx.compose.ui.window.rememberWindowState

fun main() = application {
    val windowState = rememberWindowState(
        size = DpSize(400.dp, 640.dp),
        position = WindowPosition(Alignment.Center),
    )

    Window(
        onCloseRequest = ::exitApplication,
        state = windowState,
        title = "Prosto VPN",
        undecorated = true,
        transparent = true,
        resizable = false,
        icon = painterResource("logo.png"),
    ) {
        WindowDraggableArea {
            AppRoot(
                onMinimize = { windowState.isMinimized = true },
                onClose = ::exitApplication,
            )
        }
    }
}

/** Корень приложения: окно-«квадратик» со скруглёнными углами и своим хромом. */
@Composable
fun AppRoot(
    onMinimize: () -> Unit,
    onClose: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val state = remember { AppState(scope) }

    LaunchedEffect(state.isLoggedIn) {
        if (state.isLoggedIn) state.maybeAutoConnect()
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .clip(RoundedCornerShape(26.dp))
            .background(Theme.background)
            .border(1.dp, Color.White.copy(alpha = 0.08f), RoundedCornerShape(26.dp)),
    ) {
        AnimatedContent(
            targetState = state.isLoggedIn,
            label = "root",
            transitionSpec = {
                if (targetState) {
                    (fadeIn(tween(400)) + scaleIn(
                        initialScale = 0.92f,
                        animationSpec = spring(dampingRatio = 0.85f, stiffness = 280f),
                    )).togetherWith(
                        fadeOut(tween(280)) + scaleOut(targetScale = 1.06f, animationSpec = tween(400))
                    )
                } else {
                    (fadeIn(tween(400)) + scaleIn(
                        initialScale = 1.06f,
                        animationSpec = tween(400),
                    )).togetherWith(
                        fadeOut(tween(280)) + scaleOut(targetScale = 0.94f, animationSpec = tween(400))
                    )
                }
            },
        ) { loggedIn ->
            if (loggedIn) {
                HomeScreen(state)
            } else {
                LoginScreen(state)
            }
        }

        WindowControls(
            onMinimize = onMinimize,
            onClose = onClose,
            modifier = Modifier.align(Alignment.TopEnd),
        )
    }
}

/** Кнопки окна: свернуть и закрыть. */
@Composable
private fun WindowControls(
    onMinimize: () -> Unit,
    onClose: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier.padding(top = 12.dp, end = 12.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        ControlDot(close = false, onClick = onMinimize)
        ControlDot(close = true, onClick = onClose)
    }
}

@Composable
private fun ControlDot(close: Boolean, onClick: () -> Unit) {
    val interaction = remember { MutableInteractionSource() }
    val hovered by interaction.collectIsHoveredAsState()
    val bgAlpha by animateFloatAsState(
        targetValue = if (hovered) 1f else 0f,
        animationSpec = tween(160),
        label = "dotHover",
    )
    val hoverColor = if (close) Theme.accentDeep else Color.White.copy(alpha = 0.16f)
    val glyphColor = Theme.text.copy(alpha = if (hovered) 0.95f else 0.45f)

    Box(
        modifier = Modifier
            .size(24.dp)
            .clip(CircleShape)
            .background(Color.White.copy(alpha = 0.06f))
            .background(hoverColor.copy(alpha = hoverColor.alpha * bgAlpha))
            .pointerHoverIcon(PointerIcon.Hand)
            .hoverable(interaction)
            .clickable(interactionSource = interaction, indication = null, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Canvas(Modifier.size(9.dp)) {
            val stroke = Stroke(width = 1.6.dp.toPx(), cap = StrokeCap.Round).width
            if (close) {
                drawLine(
                    color = glyphColor,
                    start = Offset(0f, 0f),
                    end = Offset(size.width, size.height),
                    strokeWidth = stroke,
                    cap = StrokeCap.Round,
                )
                drawLine(
                    color = glyphColor,
                    start = Offset(size.width, 0f),
                    end = Offset(0f, size.height),
                    strokeWidth = stroke,
                    cap = StrokeCap.Round,
                )
            } else {
                drawLine(
                    color = glyphColor,
                    start = Offset(0f, size.height / 2f),
                    end = Offset(size.width, size.height / 2f),
                    strokeWidth = stroke,
                    cap = StrokeCap.Round,
                )
            }
        }
    }
}
