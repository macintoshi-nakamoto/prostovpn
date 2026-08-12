package com.prostovpn.desktop

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.VisibilityThreshold
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.animation.shrinkHorizontally
import androidx.compose.animation.expandHorizontally
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.hoverable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsHoveredAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.PointerIcon
import androidx.compose.ui.input.pointer.pointerHoverIcon
import androidx.compose.ui.unit.dp

/** Кнопки в капсуле: настройки, свернуть, закрыть. */
private enum class Glyph { Settings, Minimize, Close }

/**
 * Единая стеклянная капсула управления в правом верхнем углу.
 *
 * Три кнопки живут в одной вытянутой линзе, а не тремя отдельными
 * кружками. При уходе с главного экрана шестерёнка «тонет» — опускается,
 * тает и сжимается, — а капсула плавно укорачивается до двух кнопок.
 */
@Composable
fun GlassControlBar(
    backdrop: BackdropState,
    showSettings: Boolean,
    onSettings: () -> Unit,
    onMinimize: () -> Unit,
    onClose: () -> Unit,
    modifier: Modifier = Modifier,
    /** Метка «есть обновление» на шестерёнке. */
    settingsBadge: Boolean = false,
) {
    // Одна пружина на «погружение» и на сжатие капсулы — движение читается
    // как единое, а не как две независимые анимации.
    val sink = spring<Float>(dampingRatio = 0.88f, stiffness = 260f)
    val sinkSize = spring(
        dampingRatio = 0.88f,
        stiffness = 260f,
        visibilityThreshold = androidx.compose.ui.unit.IntSize.VisibilityThreshold,
    )
    val sinkOffset = spring(
        dampingRatio = 0.88f,
        stiffness = 260f,
        visibilityThreshold = androidx.compose.ui.unit.IntOffset.VisibilityThreshold,
    )

    Row(
        modifier = modifier
            .height(46.dp)
            .clip(CircleShape)
            .liquidGlass(
                backdrop = backdrop,
                blurRadius = 16.dp,
                saturation = 1.7f,
                refractionHeight = 9.dp,
                refractionAmount = 9.dp,
                tintAlpha = 0.06f,
            )
            .padding(horizontal = 5.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(1.dp),
    ) {
        AnimatedVisibility(
            visible = showSettings,
            enter = expandHorizontally(sinkSize, expandFrom = Alignment.End) +
                fadeIn(tween(220)) +
                scaleIn(initialScale = 0.55f, animationSpec = sink) +
                slideInVertically(sinkOffset) { it / 2 },
            exit = shrinkHorizontally(sinkSize, shrinkTowards = Alignment.End) +
                fadeOut(tween(160)) +
                scaleOut(targetScale = 0.55f, animationSpec = sink) +
                slideOutVertically(sinkOffset) { it / 2 },
        ) {
            ControlButton(Glyph.Settings, onSettings, badge = settingsBadge)
        }

        ControlButton(Glyph.Minimize, onMinimize)
        ControlButton(Glyph.Close, onClose)
    }
}

@Composable
private fun ControlButton(glyph: Glyph, onClick: () -> Unit, badge: Boolean = false) {
    val interaction = remember { MutableInteractionSource() }
    val hovered by interaction.collectIsHoveredAsState()
    val hover by animateFloatAsState(
        targetValue = if (hovered) 1f else 0f,
        animationSpec = tween(150),
        label = "controlHover",
    )

    // Закрытие подсвечивается акцентом, остальные — нейтрально
    val hoverFill = if (glyph == Glyph.Close) {
        Theme.accentDeep.copy(alpha = 0.85f * hover)
    } else {
        Color.White.copy(alpha = 0.14f * hover)
    }
    val strokeColor = Theme.text.copy(alpha = 0.5f + 0.45f * hover)

    // Внешняя коробка не обрезается по кругу: метка должна лежать на самом
    // углу кнопки, а внутри круглой обрезки её срезало бы наполовину.
    Box(Modifier.size(36.dp), contentAlignment = Alignment.Center) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .clip(CircleShape)
                .background(hoverFill)
                .pointerHoverIcon(PointerIcon.Hand)
                .hoverable(interaction)
                .clickable(interactionSource = interaction, indication = null, onClick = onClick),
            contentAlignment = Alignment.Center,
        ) {
            Canvas(Modifier.size(17.dp)) {
                val stroke = 1.6.dp.toPx()
                when (glyph) {
                    Glyph.Settings -> drawSliders(strokeColor, stroke)
                    Glyph.Minimize -> drawLine(
                        color = strokeColor,
                        start = Offset(size.width * 0.1f, size.height / 2f),
                        end = Offset(size.width * 0.9f, size.height / 2f),
                        strokeWidth = stroke,
                        cap = StrokeCap.Round,
                    )
                    Glyph.Close -> {
                        val a = size.width * 0.16f
                        val b = size.width * 0.84f
                        drawLine(strokeColor, Offset(a, a), Offset(b, b), stroke, StrokeCap.Round)
                        drawLine(strokeColor, Offset(b, a), Offset(a, b), stroke, StrokeCap.Round)
                    }
                }
            }
        }

        // Кружок с восклицательным знаком в углу: появляется сам, когда
        // панель сказала, что вышла версия новее.
        AnimatedVisibility(
            visible = badge,
            enter = fadeIn(tween(220)) + scaleIn(initialScale = 0.4f, animationSpec = tween(260)),
            exit = fadeOut(tween(140)) + scaleOut(targetScale = 0.4f, animationSpec = tween(160)),
            modifier = Modifier.align(Alignment.TopEnd).padding(top = 4.dp, end = 4.dp),
        ) {
            Canvas(Modifier.size(10.dp)) { drawBang(Theme.accent) }
        }
    }
}

/**
 * Восклицательный знак в кружке — метка обновления.
 *
 * Рисуем, а не берём готовую иконку: на девяти точках любой шрифтовой глиф
 * превращается в кашу, а две фигуры остаются читаемыми.
 */
private fun DrawScope.drawBang(color: Color) {
    val radius = size.minDimension / 2f
    drawCircle(color = color, radius = radius, center = center)

    val bar = radius * 0.24f
    drawLine(
        color = Color.White,
        start = Offset(center.x, center.y - radius * 0.46f),
        end = Offset(center.x, center.y + radius * 0.08f),
        strokeWidth = bar,
        cap = StrokeCap.Round,
    )
    drawCircle(color = Color.White, radius = bar * 0.6f, center = Offset(center.x, center.y + radius * 0.46f))
}

/**
 * Настройки — два «ползунка»: те же прямые штрихи, что у минуса и крестика,
 * поэтому тройка читается как один набор. Шестерёнка на таком размере
 * вырождается в солнышко, а ползунки остаются узнаваемыми.
 */
private fun DrawScope.drawSliders(color: Color, stroke: Float) {
    val left = size.width * 0.08f
    val right = size.width * 0.92f
    val topY = size.height * 0.32f
    val bottomY = size.height * 0.68f
    val knob = stroke * 1.45f

    drawLine(color, Offset(left, topY), Offset(right, topY), stroke, StrokeCap.Round)
    drawLine(color, Offset(left, bottomY), Offset(right, bottomY), stroke, StrokeCap.Round)

    // Ручки на разных позициях — иконка не выглядит просто двумя линиями
    drawCircle(color, knob, Offset(size.width * 0.36f, topY), style = Stroke(stroke))
    drawCircle(color, knob, Offset(size.width * 0.66f, bottomY), style = Stroke(stroke))
}
