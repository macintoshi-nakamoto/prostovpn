package com.prostovpn.app

import android.graphics.BlurMaskFilter
import android.os.Build
import android.view.HapticFeedbackConstants
import android.view.View
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.Image
import androidx.compose.foundation.IndicationNodeFactory
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.InteractionSource
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.PressInteraction
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.ui.composed
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Paint
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawOutline
import androidx.compose.ui.graphics.drawscope.ContentDrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.drawIntoCanvas
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.node.DelegatableNode
import androidx.compose.ui.node.DrawModifierNode
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch

// ─── Отклик ────────────────────────────────────────────────────────────────

class Haptics(private val view: View) {
    fun tap() {
        view.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP)
    }

    fun success() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            view.performHapticFeedback(HapticFeedbackConstants.CONFIRM)
        } else {
            tap()
        }
    }

    fun selection() {
        view.performHapticFeedback(HapticFeedbackConstants.CLOCK_TICK)
    }

    fun heavy() {
        view.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
    }
}

@Composable
fun rememberHaptics(): Haptics {
    val view = LocalView.current
    return remember(view) { Haptics(view) }
}

/**
 * Вспышка вместо Material-ripple.
 *
 * Появляется за 90 мс, гаснет за 160 — то же, что в кабинете при нажатии
 * строки. Ставится глобально, чтобы дефолтный круг не вылезал там, где мы
 * забыли передать `indication = null`.
 */
object FlashIndication : IndicationNodeFactory {
    override fun create(interactionSource: InteractionSource): DelegatableNode =
        FlashNode(interactionSource)

    override fun equals(other: Any?): Boolean = other === this

    override fun hashCode(): Int = 0x51A5

    private class FlashNode(
        private val interactionSource: InteractionSource,
    ) : Modifier.Node(), DrawModifierNode {
        private val alpha = androidx.compose.animation.core.Animatable(0f)

        override fun onAttach() {
            coroutineScope.launch {
                interactionSource.interactions.collectLatest { interaction ->
                    when (interaction) {
                        is PressInteraction.Press -> alpha.animateTo(1f, tween(90))
                        is PressInteraction.Release,
                        is PressInteraction.Cancel,
                        -> alpha.animateTo(0f, tween(160))
                    }
                }
            }
        }

        override fun ContentDrawScope.draw() {
            drawContent()
            if (alpha.value > 0.01f) {
                drawRect(Color.White.copy(alpha = 0.06f * alpha.value))
            }
        }
    }
}

// ─── Модификаторы ──────────────────────────────────────────────────────────

fun Modifier.scaleClickable(
    scale: Float = 0.98f,
    enabled: Boolean = true,
    haptic: Boolean = true,
    onClick: () -> Unit,
): Modifier = composed {
    val interaction = remember { MutableInteractionSource() }
    val haptics = rememberHaptics()
    this
        .pressScale(interaction, scale)
        .clickable(
            interactionSource = interaction,
            indication = null,
            enabled = enabled,
            onClick = {
                if (haptic) haptics.tap()
                onClick()
            },
        )
}

fun Modifier.noRippleClickable(
    enabled: Boolean = true,
    haptic: Boolean = true,
    onClick: () -> Unit,
): Modifier = composed {
    val interaction = remember { MutableInteractionSource() }
    val haptics = rememberHaptics()
    clickable(
        interactionSource = interaction,
        indication = null,
        enabled = enabled,
        onClick = {
            if (haptic) haptics.tap()
            onClick()
        },
    )
}

/** Нажатие строки — вспышка белым 6%, как в кабинете. */
fun Modifier.flashClickable(
    enabled: Boolean = true,
    haptic: Boolean = true,
    onClick: () -> Unit,
): Modifier = composed {
    val interaction = remember { MutableInteractionSource() }
    val haptics = rememberHaptics()
    this
        .pressHighlight(interaction, 0.06f)
        .clickable(
            interactionSource = interaction,
            indication = null,
            enabled = enabled,
            onClick = {
                if (haptic) haptics.tap()
                onClick()
            },
        )
}

fun Modifier.tvFocusHighlight(shape: Shape = RoundedCornerShape(18.dp)): Modifier = composed {
    var focused by remember { mutableStateOf(false) }
    val accent = Theme.accent
    val wash = Theme.accentWash
    this
        .onFocusChanged { focused = it.isFocused }
        .drawWithContent {
            drawContent()
            if (focused) {
                val outline = shape.createOutline(size, layoutDirection, this)
                drawOutline(outline, color = wash)
                drawOutline(outline, color = accent, style = Stroke(width = 2.dp.toPx()))
            }
        }
}

fun Modifier.fadeUp(delayMs: Int = 0): Modifier = composed {
    var shown by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { shown = true }
    val progress by animateFloatAsState(
        targetValue = if (shown) 1f else 0f,
        animationSpec = tween(480, delayMs, CubicBezierEasing(0f, 0f, 0.58f, 1f)),
        label = "fadeUp",
    )
    graphicsLayer {
        alpha = progress
        translationY = (1f - progress) * 14.dp.toPx()
    }
}

fun Modifier.softShadow(
    color: Color,
    blurRadius: Dp,
    cornerRadius: Dp,
    yOffset: Dp = 0.dp,
    spread: Dp = 0.dp,
): Modifier = drawWithCache {
    val blurPx = blurRadius.toPx()
    val spreadPx = spread.toPx()
    val yPx = yOffset.toPx()
    val radiusPx = cornerRadius.toPx() + spreadPx

    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
        val paint = Paint()
        val frameworkPaint = paint.asFrameworkPaint()
        frameworkPaint.color = color.toArgb()
        frameworkPaint.maskFilter = BlurMaskFilter(blurPx, BlurMaskFilter.Blur.NORMAL)
        onDrawBehind {
            drawIntoCanvas { canvas ->
                canvas.save()
                canvas.translate(0f, yPx)
                canvas.drawRoundRect(
                    -spreadPx,
                    -spreadPx,
                    size.width + spreadPx,
                    size.height + spreadPx,
                    radiusPx,
                    radiusPx,
                    paint,
                )
                canvas.restore()
            }
        }
    } else {
        val pad = kotlin.math.ceil(blurPx * 1.5f + spreadPx).toInt().coerceAtLeast(1)
        val w = (size.width + 2 * pad).toInt().coerceAtLeast(1)
        val h = (size.height + 2 * pad).toInt().coerceAtLeast(1)
        val bitmap = android.graphics.Bitmap.createBitmap(w, h, android.graphics.Bitmap.Config.ARGB_8888)
        val softwareCanvas = android.graphics.Canvas(bitmap)
        val paint = android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG).apply {
            this.color = color.toArgb()
            maskFilter = BlurMaskFilter(blurPx, BlurMaskFilter.Blur.NORMAL)
        }
        softwareCanvas.drawRoundRect(
            pad - spreadPx,
            pad - spreadPx,
            pad + size.width + spreadPx,
            pad + size.height + spreadPx,
            radiusPx,
            radiusPx,
            paint,
        )
        val image = bitmap.asImageBitmap()
        onDrawBehind {
            drawImage(image, topLeft = Offset(-pad.toFloat(), -pad.toFloat() + yPx))
        }
    }
}

/**
 * Стекло кабинета: заливка, верхний блик и мягкая тень.
 *
 * Настоящее размытие фона стоит только там, где под карточкой действительно
 * что-то есть (нижняя панель, лист). Обычные карточки лежат на канве, и
 * размывать под ними нечего — заливка с бликом даёт тот же результат дешевле.
 */
fun Modifier.glass(
    radius: Dp = R2.card,
    fill: Color? = null,
    shadow: Boolean = true,
    shadowColor: Color? = null,
    shadowBlur: Dp = 26.dp,
    shadowY: Dp = 12.dp,
): Modifier = composed {
    val paletteFill = fill ?: Theme.glassFill
    val highlight = Theme.glassHighlight
    val base = if (Theme.isLight) Color.White.copy(alpha = 0.86f) else paletteFill
    val shade = shadowColor ?: Theme.shadowLift

    this
        .then(if (shadow) Modifier.softShadow(shade, shadowBlur, radius, shadowY) else Modifier)
        .clip(RoundedCornerShape(radius))
        .background(base)
        .drawBehind {
            val strokeW = 1.dp.toPx()
            drawRoundRect(
                brush = Brush.verticalGradient(
                    0f to highlight,
                    0.42f to Color.Transparent,
                ),
                topLeft = Offset(strokeW / 2f, strokeW / 2f),
                size = Size(size.width - strokeW, size.height - strokeW),
                cornerRadius = CornerRadius(radius.toPx() - strokeW / 2f, radius.toPx() - strokeW / 2f),
                style = Stroke(width = strokeW),
            )
        }
}

// ─── Карточки и строки ─────────────────────────────────────────────────────

@Composable
fun GlassCard(
    modifier: Modifier = Modifier,
    radius: Dp = R2.card,
    padding: Dp = 16.dp,
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .glass(radius)
            .padding(padding),
        content = content,
    )
}

/** Карточка-список: строки внутри одной карточки, между ними волосяная линия. */
@Composable
fun RowsCard(
    modifier: Modifier = Modifier,
    radius: Dp = R2.card,
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .glass(radius),
        content = content,
    )
}

@Composable
fun HairLine(inset: Dp = 18.dp) {
    Box(
        Modifier
            .fillMaxWidth()
            .padding(horizontal = inset)
            .height(1.dp)
            .background(Theme.hair),
    )
}

@Composable
fun IconCircle(
    icon: ImageVector,
    size: Dp = 40.dp,
    tint: Color = Theme.accentText,
    background: Color = Theme.accentWash,
    iconSize: Dp = 19.dp,
) {
    Box(
        modifier = Modifier
            .size(size)
            .clip(CircleShape)
            .background(background),
        contentAlignment = Alignment.Center,
    ) {
        Icon(icon, contentDescription = null, tint = tint, modifier = Modifier.size(iconSize))
    }
}

/**
 * Строка-меню: иконка в кружке, заголовок с подписью, справа значение или
 * шеврон. Высота 62, разделитель рисует родитель.
 */
@Composable
fun MenuRow(
    title: String,
    modifier: Modifier = Modifier,
    subtitle: String? = null,
    value: String? = null,
    icon: ImageVector? = null,
    iconTint: Color = Theme.accentText,
    iconBackground: Color = Theme.accentWash,
    titleColor: Color = Theme.text,
    chevron: Boolean = true,
    height: Dp = 62.dp,
    onClick: (() -> Unit)? = null,
    trailing: (@Composable () -> Unit)? = null,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .heightIn(min = height)
            .then(
                if (onClick != null) {
                    Modifier
                        .tvFocusHighlight(RoundedCornerShape(R2.card))
                        .flashClickable(onClick = onClick)
                } else {
                    Modifier
                }
            )
            .padding(horizontal = 18.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (icon != null) {
            IconCircle(icon = icon, tint = iconTint, background = iconBackground)
            Spacer(Modifier.width(14.dp))
        }

        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(title, style = pro(16.sp, W.semibold, titleColor))
            if (subtitle != null) {
                Text(subtitle, style = pro(13.sp, W.regular, Theme.textFaint))
            }
        }

        if (value != null) {
            Spacer(Modifier.width(10.dp))
            Text(value, style = pro(14.sp, W.medium, Theme.textFaint, tabular = true))
        }

        if (trailing != null) {
            Spacer(Modifier.width(12.dp))
            trailing()
        } else if (chevron && onClick != null) {
            Spacer(Modifier.width(8.dp))
            Icon(
                imageVector = Icons.chevronRight,
                contentDescription = null,
                tint = Theme.textFaint,
                modifier = Modifier.size(17.dp),
            )
        }
    }
}

// ─── Действия ──────────────────────────────────────────────────────────────

@Composable
fun PrimaryPill(
    text: String,
    modifier: Modifier = Modifier,
    height: Dp = 56.dp,
    enabled: Boolean = true,
    icon: ImageVector? = null,
    onClick: () -> Unit,
) {
    val interaction = remember { MutableInteractionSource() }
    val haptics = rememberHaptics()
    val fontSize = if (height >= 52.dp) 17.sp else 15.sp

    Row(
        modifier = modifier
            .fillMaxWidth()
            .height(height)
            .pressScale(interaction, 0.98f)
            .softShadow(Theme.shadowAccent, 16.dp, height / 2f, yOffset = 10.dp)
            .tvFocusHighlight(CircleShape)
            .clip(CircleShape)
            .background(Theme.brandGradient)
            .pressHighlight(interaction, 0.12f)
            .clickable(
                interactionSource = interaction,
                indication = null,
                enabled = enabled,
            ) {
                haptics.tap()
                onClick()
            },
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (icon != null) {
            Icon(icon, contentDescription = null, tint = Color.White, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(9.dp))
        }
        Text(text, style = pro(fontSize, W.semibold, Color.White))
    }
}

@Composable
fun GhostPill(
    text: String,
    modifier: Modifier = Modifier,
    height: Dp = 52.dp,
    onClick: () -> Unit,
) {
    val interaction = remember { MutableInteractionSource() }
    val haptics = rememberHaptics()
    Box(
        modifier = modifier
            .fillMaxWidth()
            .height(height)
            .pressScale(interaction, 0.98f)
            .tvFocusHighlight(CircleShape)
            .clip(CircleShape)
            .background(if (Theme.isLight) Color.White.copy(alpha = 0.9f) else Theme.glassFill)
            .border(1.dp, Theme.ghostStroke, CircleShape)
            .pressHighlight(interaction, 0.06f)
            .clickable(interactionSource = interaction, indication = null) {
                haptics.tap()
                onClick()
            },
        contentAlignment = Alignment.Center,
    ) {
        Text(text, style = pro(15.sp, W.semibold, Theme.text))
    }
}

@Composable
fun SoftPill(
    text: String,
    modifier: Modifier = Modifier,
    height: Dp = 44.dp,
    onClick: () -> Unit,
) {
    val interaction = remember { MutableInteractionSource() }
    val haptics = rememberHaptics()
    Box(
        modifier = modifier
            .height(height)
            .pressScale(interaction, 0.97f)
            .tvFocusHighlight(CircleShape)
            .clip(CircleShape)
            .background(Theme.accentWash)
            .clickable(interactionSource = interaction, indication = null) {
                haptics.tap()
                onClick()
            }
            .padding(horizontal = 18.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(text, style = pro(14.sp, W.semibold, Theme.accentText))
    }
}

/** Маленькая залитая пилюля 38 — «Продлить», «Обновить» в баннерах. */
@Composable
fun MiniPill(
    text: String,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    val interaction = remember { MutableInteractionSource() }
    val haptics = rememberHaptics()
    Box(
        modifier = modifier
            .height(38.dp)
            .pressScale(interaction, 0.96f)
            .tvFocusHighlight(CircleShape)
            .clip(CircleShape)
            .background(Theme.brandGradient)
            .clickable(interactionSource = interaction, indication = null) {
                haptics.tap()
                onClick()
            }
            .padding(horizontal = 16.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(text, style = pro(13.5.sp, W.semibold, Color.White))
    }
}

@Composable
fun Chip(
    text: String,
    color: Color = Theme.accentText,
    background: Color = Theme.accentWash,
    modifier: Modifier = Modifier,
    tabular: Boolean = false,
) {
    Text(
        text = text,
        style = pro(12.sp, W.semibold, color, tabular = tabular),
        modifier = modifier
            .clip(CircleShape)
            .background(background)
            .padding(horizontal = 10.dp, vertical = 5.dp),
    )
}

/** Переключатель 46×28: трек уезжает в акцент, кружок белый. */
@Composable
fun ProToggle(checked: Boolean, enabled: Boolean = true, onChange: (Boolean) -> Unit) {
    val haptics = rememberHaptics()
    val thumbOffset by animateDpAsState(
        targetValue = if (checked) 21.dp else 3.dp,
        animationSpec = tween(200, easing = Theme.easeStandard),
        label = "thumb",
    )
    val track by animateColorAsState(
        targetValue = if (checked) Theme.accent else Theme.tileDeep,
        animationSpec = tween(200, easing = Theme.easeStandard),
        label = "track",
    )
    Box(
        modifier = Modifier
            .size(width = 46.dp, height = 28.dp)
            .tvFocusHighlight(CircleShape)
            .clip(CircleShape)
            .background(track)
            .noRippleClickable(enabled = enabled, haptic = false) {
                haptics.selection()
                onChange(!checked)
            },
        contentAlignment = Alignment.CenterStart,
    ) {
        Box(
            modifier = Modifier
                .offset(x = thumbOffset)
                .size(22.dp)
                .softShadow(Color.Black.copy(alpha = 0.28f), 3.dp, 11.dp, yOffset = 1.dp)
                .clip(CircleShape)
                .background(Color.White),
        )
    }
}

/** Сегмент из двух-трёх пилюль: язык, тема. */
@Composable
fun Segment(
    options: List<Pair<String, String>>,
    selected: String,
    modifier: Modifier = Modifier,
    height: Dp = 34.dp,
    onSelect: (String) -> Unit,
) {
    Row(
        modifier = modifier
            .height(height)
            .clip(CircleShape)
            .background(if (Theme.isLight) Theme.tile else Color.White.copy(alpha = 0.07f))
            .padding(3.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        options.forEach { (key, label) ->
            val active = key == selected
            val bg by animateColorAsState(
                targetValue = if (active) Theme.accent else Color.Transparent,
                animationSpec = tween(220),
                label = "segBg",
            )
            val fg by animateColorAsState(
                targetValue = if (active) Color.White else Theme.textMuted,
                animationSpec = tween(220),
                label = "segFg",
            )
            Box(
                modifier = Modifier
                    .fillMaxHeight()
                    .tvFocusHighlight(CircleShape)
                    .clip(CircleShape)
                    .background(bg)
                    .noRippleClickable { onSelect(key) }
                    .padding(horizontal = 14.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(label, style = pro(13.sp, W.semibold, fg))
            }
        }
    }
}

// ─── Баннеры и заглушки ────────────────────────────────────────────────────

enum class BannerTone { ACCENT, WARNING, INFO, ERROR }

@Composable
fun Banner(
    title: String,
    tone: BannerTone = BannerTone.ACCENT,
    body: String? = null,
    actionText: String? = null,
    modifier: Modifier = Modifier,
    onAction: (() -> Unit)? = null,
) {
    val background = when (tone) {
        BannerTone.ACCENT -> Theme.accentWash
        BannerTone.WARNING -> Theme.warningWash
        BannerTone.INFO -> Theme.infoWash
        BannerTone.ERROR -> Theme.errorWash
    }
    val titleColor = when (tone) {
        BannerTone.ACCENT -> Theme.accentText
        BannerTone.WARNING -> Theme.warningText
        BannerTone.INFO -> Theme.info
        BannerTone.ERROR -> Theme.errorText
    }

    Row(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(R2.card))
            .background(background)
            .padding(horizontal = 16.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
            Text(title, style = pro(14.5.sp, W.semibold, titleColor, lineHeight = 20.sp))
            if (body != null) {
                Text(body, style = pro(13.sp, W.regular, Theme.textMuted, lineHeight = 18.sp))
            }
        }
        if (actionText != null && onAction != null) {
            Spacer(Modifier.width(12.dp))
            MiniPill(text = actionText, onClick = onAction)
        }
    }
}

@Composable
fun Skeleton(width: Dp, height: Dp, radius: Dp = 8.dp) {
    val shift by androidx.compose.animation.core.rememberInfiniteTransition(label = "sk")
        .animateFloat(
            initialValue = -1f,
            targetValue = 2f,
            animationSpec = androidx.compose.animation.core.infiniteRepeatable(
                tween(1200, easing = androidx.compose.animation.core.LinearEasing),
            ),
            label = "skShift",
        )
    Box(
        Modifier
            .size(width = width, height = height)
            .clip(RoundedCornerShape(radius))
            .drawBehind {
                drawRect(Theme.tile.copy(alpha = if (Theme.isLight) 1f else 0.55f))
                val w = size.width
                drawRect(
                    brush = Brush.horizontalGradient(
                        0f to Color.Transparent,
                        0.5f to Color.White.copy(alpha = if (Theme.isLight) 0.55f else 0.06f),
                        1f to Color.Transparent,
                        startX = shift * w,
                        endX = (shift + 1f) * w,
                    ),
                )
            },
    )
}

// ─── Мелочи ────────────────────────────────────────────────────────────────

@Composable
fun LogoImage(modifier: Modifier = Modifier, glowAlpha: Float = 0f) {
    val accent = Theme.accent
    Image(
        painter = painterResource(R.drawable.logo),
        contentDescription = null,
        modifier = modifier.drawBehind {
            if (glowAlpha > 0f) {
                drawCircle(
                    brush = Brush.radialGradient(
                        colors = listOf(accent.copy(alpha = glowAlpha), Color.Transparent),
                        center = center,
                        radius = size.minDimension * 0.9f,
                    ),
                    radius = size.minDimension * 0.9f,
                    center = center,
                )
            }
        },
    )
}

@Composable
fun GlassCircleButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    size: Dp = 40.dp,
    content: @Composable BoxScope.() -> Unit,
) {
    val haptics = rememberHaptics()
    val interaction = remember { MutableInteractionSource() }
    Box(
        modifier = modifier
            .size(size)
            .pressScale(interaction, 0.92f)
            .tvFocusHighlight(CircleShape)
            .clip(CircleShape)
            .background(if (Theme.isLight) Color.White.copy(alpha = 0.9f) else Theme.glassFill)
            .pressHighlight(interaction, 0.08f)
            .clickable(interactionSource = interaction, indication = null) {
                haptics.tap()
                onClick()
            },
        contentAlignment = Alignment.Center,
        content = content,
    )
}

/** Шапка внутреннего экрана: кружок «назад» и заголовок 22/700. */
@Composable
fun ScreenHeader(
    title: String,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
    trailing: (@Composable RowScope.() -> Unit)? = null,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .height(56.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        GlassCircleButton(onClick = onBack) {
            Icon(
                imageVector = Icons.chevronLeft,
                contentDescription = null,
                tint = Theme.text,
                modifier = Modifier.size(19.dp).offset(x = (-1).dp),
            )
        }
        Spacer(Modifier.width(14.dp))
        Text(title, style = pro(22.sp, W.bold, Theme.text, tracking = em(22.sp, -0.025f)))
        Spacer(Modifier.weight(1f))
        trailing?.invoke(this)
    }
}

@Composable
fun RollingText(text: String, style: TextStyle, modifier: Modifier = Modifier) {
    Row(modifier = modifier, verticalAlignment = Alignment.CenterVertically) {
        val length = text.length
        text.forEachIndexed { index, char ->
            androidx.compose.runtime.key(length - index) {
                androidx.compose.animation.AnimatedContent(
                    targetState = char,
                    transitionSpec = {
                        (androidx.compose.animation.slideInVertically(
                            animationSpec = tween(220, easing = Theme.easeStandard),
                        ) { height -> height } + androidx.compose.animation.fadeIn(tween(140)))
                            .togetherWith(
                                androidx.compose.animation.slideOutVertically(
                                    animationSpec = tween(220, easing = Theme.easeStandard),
                                ) { height -> -height } + androidx.compose.animation.fadeOut(tween(100))
                            )
                    },
                    label = "roll$index",
                ) { c ->
                    Text(text = c.toString(), style = style)
                }
            }
        }
    }
}

@Composable
fun ProDialog(
    title: String,
    message: String,
    confirmText: String,
    dismissText: String?,
    destructive: Boolean = true,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    androidx.compose.ui.window.Dialog(onDismissRequest = onDismiss) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(R2.plate))
                .background(if (Theme.isLight) Color.White else Color(0xFF1D1D1F))
                .padding(horizontal = 22.dp, vertical = 22.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                text = title,
                style = pro(19.sp, W.bold, Theme.text, tracking = em(19.sp, -0.02f)),
                textAlign = TextAlign.Center,
            )
            if (message.isNotEmpty()) {
                Spacer(Modifier.height(8.dp))
                Text(
                    text = message,
                    style = pro(14.sp, W.regular, Theme.textMuted, lineHeight = 20.sp),
                    textAlign = TextAlign.Center,
                )
            }
            Spacer(Modifier.height(20.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                if (dismissText != null) {
                    GhostPill(
                        text = dismissText,
                        height = 48.dp,
                        modifier = Modifier.weight(1f),
                        onClick = onDismiss,
                    )
                }
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .height(48.dp)
                        .tvFocusHighlight(CircleShape)
                        .clip(CircleShape)
                        .background(if (destructive) Theme.errorWash else Theme.accentWash)
                        .noRippleClickable(onClick = onConfirm),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        confirmText,
                        style = pro(15.sp, W.semibold, if (destructive) Theme.errorText else Theme.accentText),
                    )
                }
            }
        }
    }
}

/** Свечение канвы — цветное пятно из-под верхнего края экрана. */
@Composable
fun CanvasGlow(color: Color, strength: Float = 1f, modifier: Modifier = Modifier) {
    val animated by animateColorAsState(color, tween(420), label = "glowColor")
    val power by animateFloatAsState(strength, tween(420), label = "glowPower")
    androidx.compose.foundation.Canvas(modifier.fillMaxSize()) {
        if (power <= 0.01f) return@Canvas
        val radius = size.width * 1.05f
        val center = Offset(size.width / 2f, -size.height * 0.08f)
        drawCircle(
            brush = Brush.radialGradient(
                colors = listOf(animated.copy(alpha = animated.alpha * power), Color.Transparent),
                center = center,
                radius = radius,
            ),
            radius = radius,
            center = center,
        )
    }
}

/** Каркас листа: ручка, заголовок, подзаголовок и содержимое. */
@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
fun SheetShell(
    title: String,
    subtitle: String?,
    onDismiss: () -> Unit,
    content: @Composable ColumnScope.() -> Unit,
) {
    val sheetState = androidx.compose.material3.rememberModalBottomSheetState(skipPartiallyExpanded = true)
    androidx.compose.material3.ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState,
        containerColor = Color.Transparent,
        dragHandle = null,
        shape = RoundedCornerShape(topStart = R2.plate, topEnd = R2.plate),
        scrimColor = Color(0xFF080809).copy(alpha = 0.55f),
        contentWindowInsets = { androidx.compose.foundation.layout.WindowInsets(0.dp) },
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(topStart = R2.plate, topEnd = R2.plate))
                .background(if (Theme.isLight) Color.White else Color(0xFF141416))
                .navigationBarsPadding()
                .padding(horizontal = 16.dp)
                .padding(bottom = 18.dp),
        ) {
            Box(
                modifier = Modifier
                    .padding(top = 10.dp, bottom = 14.dp)
                    .align(Alignment.CenterHorizontally)
                    .size(width = 38.dp, height = 4.dp)
                    .clip(CircleShape)
                    .background(if (Theme.isLight) Theme.tileDeep else Color.White.copy(alpha = 0.18f)),
            )
            Text(title, style = pro(24.sp, W.bold, Theme.text, tracking = em(24.sp, -0.025f)))
            if (!subtitle.isNullOrEmpty()) {
                Spacer(Modifier.height(4.dp))
                Text(subtitle, style = pro(14.sp, W.regular, Theme.textMuted))
            }
            Spacer(Modifier.height(16.dp))
            content()
        }
    }
}
