package com.prostovpn.desktop

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.hoverable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
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
import androidx.compose.runtime.key
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
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Paint
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.drawIntoCanvas
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.PointerIcon
import androidx.compose.ui.input.pointer.pointerHoverIcon
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.jetbrains.skia.FilterBlurMode
import org.jetbrains.skia.MaskFilter

/** На десктопе тактильного отклика нет — интерфейс совместим с мобильной версией. */
class Haptics {
    fun tap() {}
    fun success() {}
    fun selection() {}
}

private val hapticsInstance = Haptics()

@Composable
fun rememberHaptics(): Haptics = hapticsInstance

/** Клик без ripple с масштабом при нажатии и курсором-рукой. */
fun Modifier.scaleClickable(
    scale: Float = 0.96f,
    enabled: Boolean = true,
    onClick: () -> Unit,
): Modifier = composed {
    val interaction = remember { MutableInteractionSource() }
    this
        .pressScale(interaction, scale)
        .pointerHoverIcon(PointerIcon.Hand)
        .hoverable(interaction, enabled)
        .clickable(
            interactionSource = interaction,
            indication = null,
            enabled = enabled,
            onClick = onClick,
        )
}

fun Modifier.noRippleClickable(enabled: Boolean = true, onClick: () -> Unit): Modifier = composed {
    val interaction = remember { MutableInteractionSource() }
    this
        .pointerHoverIcon(PointerIcon.Hand)
        .clickable(interactionSource = interaction, indication = null, enabled = enabled, onClick = onClick)
}

/** Появление с подъёмом — аналог iOS fadeUp(). */
fun Modifier.fadeUp(delayMs: Int = 0): Modifier = composed {
    var shown by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { shown = true }
    val progress by animateFloatAsState(
        targetValue = if (shown) 1f else 0f,
        animationSpec = tween(550, delayMs, CubicBezierEasing(0f, 0f, 0.58f, 1f)),
        label = "fadeUp",
    )
    graphicsLayer {
        alpha = progress
        translationY = (1f - progress) * 16.dp.toPx()
    }
}

/** Мягкая цветная тень (iOS .shadow) — Skia MaskFilter. */
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

    val paint = Paint()
    val frameworkPaint = paint.asFrameworkPaint()
    frameworkPaint.color = color.toArgb()
    frameworkPaint.maskFilter = MaskFilter.makeBlur(FilterBlurMode.NORMAL, blurPx * 0.5f)

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
}

/**
 * Знак «PROSTO» с тёплым свечением, как в iOS.
 *
 * Надпись широкая, поэтому свечение считаем от ширины: круг по меньшей
 * стороне у полосы 7:1 выродился бы в еле заметное пятно посередине.
 */
@Composable
fun LogoImage(
    modifier: Modifier = Modifier,
    glowAlpha: Float = 0.35f,
) {
    Image(
        painter = painterResource("logo.png"),
        contentDescription = null,
        modifier = modifier.drawBehind {
            if (glowAlpha > 0f) {
                val radius = size.maxDimension * 0.6f
                drawCircle(
                    brush = Brush.radialGradient(
                        colors = listOf(
                            Theme.accentWarm.copy(alpha = glowAlpha),
                            Color.Transparent,
                        ),
                        center = center,
                        radius = radius,
                    ),
                    radius = radius,
                    center = center,
                )
            }
        },
    )
}

/**
 * Иконка приложения — та же оранжевая плитка, что в трее и на панели задач.
 *
 * Нужна там, где места на надпись нет: в кружке заголовка главного экрана
 * широкий знак превратился бы в нечитаемую полоску.
 */
@Composable
fun AppMark(modifier: Modifier = Modifier) {
    Image(
        painter = painterResource("appicon.png"),
        contentDescription = null,
        modifier = modifier,
    )
}

/** Круглая стеклянная кнопка — iOS GlassCircleButton. */
@Composable
fun GlassCircleButton(
    backdrop: BackdropState,
    size: Dp = 46.dp,
    onClick: () -> Unit,
    content: @Composable BoxScope.() -> Unit,
) {
    val interaction = remember { MutableInteractionSource() }
    Box(
        modifier = Modifier
            .size(size)
            .pressScale(interaction, 0.92f)
            .clip(CircleShape)
            .liquidGlass(backdrop)
            // отдельный слой: подсветка и контент не заставляют стекло пересчитывать blur
            .graphicsLayer()
            .pressHighlight(interaction)
            .pointerHoverIcon(PointerIcon.Hand)
            .hoverable(interaction)
            .clickable(interactionSource = interaction, indication = null, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        content()
    }
}

/** Стеклянная кнопка «Назад». */
@Composable
fun GlassBackButton(
    backdrop: BackdropState,
    onBack: () -> Unit,
) {
    GlassCircleButton(backdrop = backdrop, size = 44.dp, onClick = onBack) {
        Icon(
            imageVector = Icons.chevronLeft,
            contentDescription = null,
            tint = Theme.text.copy(alpha = 0.85f),
            modifier = Modifier.size(20.dp).offset(x = (-1).dp),
        )
    }
}

/** Текст с «прокруткой» цифр — аналог iOS contentTransition(.numericText()). */
@Composable
fun RollingText(
    text: String,
    style: TextStyle,
    modifier: Modifier = Modifier,
) {
    Row(modifier = modifier, verticalAlignment = Alignment.CenterVertically) {
        val length = text.length
        text.forEachIndexed { index, char ->
            key(length - index) {
                AnimatedContent(
                    targetState = char,
                    transitionSpec = {
                        (slideInVertically(
                            animationSpec = spring(dampingRatio = 0.9f, stiffness = 650f),
                        ) { height -> height } + fadeIn(tween(140))).togetherWith(
                            slideOutVertically(
                                animationSpec = spring(dampingRatio = 0.9f, stiffness = 650f),
                            ) { height -> -height } + fadeOut(tween(100))
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

/** Группа-«карточка» настроек — iOS cardGroup(). */
@Composable
fun CardGroup(
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(20.dp))
            .background(Theme.card)
            .drawWithContent {
                drawContent()
                val strokeW = 1.dp.toPx()
                drawRoundRect(
                    brush = Brush.verticalGradient(
                        0f to Color.White.copy(alpha = 0.06f),
                        0.5f to Color.Transparent,
                    ),
                    topLeft = Offset(strokeW / 2f, strokeW / 2f),
                    size = Size(size.width - strokeW, size.height - strokeW),
                    cornerRadius = CornerRadius(20.dp.toPx() - strokeW / 2f, 20.dp.toPx() - strokeW / 2f),
                    style = Stroke(width = strokeW),
                )
            }
            .padding(6.dp),
    ) {
        content()
    }
}

@Composable
fun CardDivider() {
    Box(
        Modifier
            .fillMaxWidth()
            .padding(horizontal = 10.dp)
            .height(1.dp)
            .background(Theme.divider),
    )
}

/**
 * Квадратик с флагом — iOS FlagChip.
 * Флаг рисуется цветным Twemoji: системный шрифт Windows флаги не поддерживает.
 */
@Composable
fun FlagChip(flag: String, size: Dp = 40.dp) {
    val fontSize = with(LocalDensity.current) { (size * 0.62f).toSp() }
    Box(
        modifier = Modifier
            .size(size)
            .clip(RoundedCornerShape(size * 0.3f))
            .background(Theme.accentTint12),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = flag,
            style = TextStyle(
                fontFamily = EmojiFamily,
                fontSize = fontSize,
            ),
        )
    }
}

/** Бейдж протокола AWG2. */
@Composable
fun ProtocolBadge() {
    Text(
        text = "AWG2",
        style = manrope(11.sp, W.bold, Theme.accentSoft, letterSpacing = 0.5.sp),
        modifier = Modifier
            .clip(RoundedCornerShape(6.dp))
            .background(Theme.accentTint12)
            .padding(horizontal = 7.dp, vertical = 2.dp),
    )
}

/** Оранжевый тумблер — iOS OrangeToggleStyle. */
@Composable
fun OrangeToggle(checked: Boolean, onChange: (Boolean) -> Unit) {
    val thumbOffset by animateDpAsState(
        targetValue = if (checked) 21.5.dp else 2.5.dp,
        animationSpec = spring(dampingRatio = 0.72f, stiffness = 520f),
        label = "thumb",
    )
    val fillAlpha by animateFloatAsState(
        targetValue = if (checked) 1f else 0f,
        animationSpec = Theme.spring(250),
        label = "fill",
    )
    Box(
        modifier = Modifier
            .size(width = 48.dp, height = 29.dp)
            .clip(CircleShape)
            .background(Color.White.copy(alpha = 0.12f))
            .drawBehind {
                drawRoundRect(
                    brush = Theme.accentGradient,
                    cornerRadius = CornerRadius(size.height / 2f, size.height / 2f),
                    alpha = fillAlpha,
                )
            }
            .noRippleClickable { onChange(!checked) },
        contentAlignment = Alignment.CenterStart,
    ) {
        Box(
            modifier = Modifier
                .offset(x = thumbOffset)
                .size(24.dp)
                .softShadow(Color.Black.copy(alpha = 0.35f), 3.dp, 12.dp, yOffset = 2.dp)
                .clip(CircleShape)
                .background(Color.White),
        )
    }
}

/** Оранжевая CTA-кнопка — iOS PrimaryButtonStyle. */
@Composable
fun PrimaryButton(
    text: String,
    modifier: Modifier = Modifier,
    icon: ImageVector? = null,
    height: Dp = 50.dp,
    cornerRadius: Dp = 16.dp,
    onClick: () -> Unit,
) {
    val interaction = remember { MutableInteractionSource() }
    Row(
        modifier = modifier
            .fillMaxWidth()
            .height(height)
            .pressScale(interaction, 0.98f)
            .softShadow(Theme.accent.copy(alpha = 0.30f), 12.dp, cornerRadius, yOffset = 8.dp)
            .clip(RoundedCornerShape(cornerRadius))
            .background(Theme.primaryGradient)
            .drawWithContent {
                drawContent()
                val strokeW = 1.dp.toPx()
                drawRoundRect(
                    brush = Brush.verticalGradient(
                        0f to Color.White.copy(alpha = 0.25f),
                        0.5f to Color.Transparent,
                    ),
                    topLeft = Offset(strokeW / 2f, strokeW / 2f),
                    size = Size(size.width - strokeW, size.height - strokeW),
                    cornerRadius = CornerRadius(cornerRadius.toPx() - strokeW / 2f, cornerRadius.toPx() - strokeW / 2f),
                    style = Stroke(width = strokeW),
                )
            }
            .pointerHoverIcon(PointerIcon.Hand)
            .hoverable(interaction)
            .clickable(interactionSource = interaction, indication = null, onClick = onClick),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (icon != null) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = Color.White,
                modifier = Modifier.size(18.dp),
            )
            Spacer(Modifier.width(9.dp))
        }
        Text(text = text, style = manrope(15.sp, W.bold, Color.White))
    }
}

/** Тёплый диалог подтверждения в стиле приложения. */
@Composable
fun WarmAlertDialog(
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
                .width(320.dp)
                .clip(RoundedCornerShape(28.dp))
                .background(Theme.sheetGradient)
                .padding(horizontal = 24.dp, vertical = 24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                text = title,
                style = manrope(18.sp, W.extraBold, Theme.text),
                textAlign = TextAlign.Center,
            )
            if (message.isNotEmpty()) {
                Spacer(Modifier.height(8.dp))
                Text(
                    text = message,
                    style = manrope(13.5.sp, W.medium, Theme.textSecondary),
                    textAlign = TextAlign.Center,
                )
            }
            Spacer(Modifier.height(20.dp))
            Row {
                if (dismissText != null) {
                    Box(
                        modifier = Modifier
                            .weight(1f)
                            .height(46.dp)
                            .clip(RoundedCornerShape(15.dp))
                            .background(Color.White.copy(alpha = 0.06f))
                            .noRippleClickable(onClick = onDismiss),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(dismissText, style = manrope(15.sp, W.bold, Theme.text))
                    }
                    Spacer(Modifier.width(10.dp))
                }
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .height(46.dp)
                        .clip(RoundedCornerShape(15.dp))
                        .background(
                            if (destructive) Theme.accentTint12 else Color.White.copy(alpha = 0.06f)
                        )
                        .noRippleClickable(onClick = onConfirm),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        confirmText,
                        style = manrope(15.sp, W.bold, if (destructive) Theme.link else Theme.text),
                    )
                }
            }
        }
    }
}
