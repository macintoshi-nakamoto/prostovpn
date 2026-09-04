package com.prostovpn.app

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.InfiniteRepeatableSpec
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.keyframes
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.sin

enum class PlateState { OFF, CONNECTING, ON, ERROR }

private const val CYCLE = 9000

/**
 * Плита подключения — главная сущность экрана.
 *
 * Состояние читается всей плоскостью: стекло, жидкая заливка, фирменный
 * градиент. Иконку разглядывать не нужно — цвет виден с расстояния вытянутой
 * руки, ради этого плита и заменила круглую кнопку.
 */
@Composable
fun ConnectionPlate(
    state: PlateState,
    title: String,
    subtitle: String?,
    subtitleAlt: String? = null,
    chip: String?,
    chipTabular: Boolean = false,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    val interaction = remember { MutableInteractionSource() }
    val onColor = if (state == PlateState.ON) Color.White else Theme.text

    // Пока идёт подключение, подпись переключается: сначала что мы делаем,
    // потом честное «ждём ответ узла» — на этой паузе и правда ждём.
    val alt by androidx.compose.runtime.produceState(false, state, subtitleAlt) {
        if (state != PlateState.CONNECTING || subtitleAlt == null) {
            value = false
            return@produceState
        }
        while (true) {
            kotlinx.coroutines.delay(3400)
            value = !value
        }
    }
    val caption = if (alt && subtitleAlt != null) subtitleAlt else subtitle
    val glassAlpha by animateFloatAsState(
        targetValue = if (state == PlateState.ON) 0f else 1f,
        animationSpec = tween(280, easing = Theme.easeStandard),
        label = "plateGlass",
    )

    Box(
        modifier = modifier
            .fillMaxWidth()
            .height(222.dp)
            .pressScale(interaction, 0.985f)
            .softShadow(
                color = if (state == PlateState.ON) Theme.shadowAccent else Theme.shadowPlate,
                blurRadius = 30.dp,
                cornerRadius = R2.plate,
                yOffset = 18.dp,
            )
            .clip(RoundedCornerShape(R2.plate))
            .background(Theme.brandGradient)
            .then(
                if (glassAlpha > 0.01f) {
                    Modifier.glassOverlay(glassAlpha)
                } else {
                    Modifier
                }
            )
            .clickable(interactionSource = interaction, indication = null, onClick = onClick),
    ) {
        if (state == PlateState.ON) ChromeObjects()
        if (state == PlateState.CONNECTING) LiquidFill()

        if (chip != null) {
            Chip(
                text = chip,
                color = if (state == PlateState.ON) Color.White else plateChipColor(state),
                background = plateChipBackground(state),
                tabular = chipTabular,
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .padding(14.dp),
            )
        }

        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 22.dp),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            PlateGlyph(state)

            Spacer(Modifier.height(14.dp))

            AnimatedContent(
                targetState = title,
                transitionSpec = { fadeIn(tween(240)).togetherWith(fadeOut(tween(160))) },
                label = "plateTitle",
            ) { text ->
                Text(
                    text = text,
                    style = pro(
                        if (state == PlateState.ERROR) 22.sp else 24.sp,
                        W.bold,
                        onColor,
                        tracking = em(24.sp, -0.025f),
                    ),
                    textAlign = TextAlign.Center,
                )
            }

            if (!caption.isNullOrEmpty()) {
                Spacer(Modifier.height(5.dp))
                AnimatedContent(
                    targetState = caption,
                    transitionSpec = { fadeIn(tween(240)).togetherWith(fadeOut(tween(160))) },
                    label = "plateSub",
                ) { text ->
                    Text(
                        text = text,
                        style = pro(
                            14.sp,
                            W.regular,
                            if (state == PlateState.ON) Color.White.copy(alpha = 0.72f) else Theme.textMuted,
                        ),
                        textAlign = TextAlign.Center,
                    )
                }
            }
        }
    }
}

/**
 * Стекло поверх градиента.
 *
 * Плита всегда залита фирменным градиентом, а выключенное состояние — это
 * стекло поверх него: тогда переход «выкл → вкл» это один кроссфейд по alpha,
 * а не смена двух разных фонов.
 */
private fun Modifier.glassOverlay(alpha: Float): Modifier = composed {
    val canvas = Theme.canvasMid
    val fill = if (Theme.isLight) Color.White.copy(alpha = 0.9f) else Theme.glassFill
    val highlight = Theme.glassHighlight
    drawBehind {
        drawRect(canvas.copy(alpha = alpha))
        drawRect(fill.copy(alpha = fill.alpha * alpha))
        // Блик рисуем обводкой скруглённого прямоугольника: прямая линия во
        // всю ширину не ложится на углы и торчит над плитой.
        val strokeW = 1.dp.toPx()
        val radius = R2.plate.toPx()
        drawRoundRect(
            brush = Brush.verticalGradient(
                0f to highlight.copy(alpha = highlight.alpha * alpha),
                0.42f to Color.Transparent,
            ),
            topLeft = Offset(strokeW / 2f, strokeW / 2f),
            size = Size(size.width - strokeW, size.height - strokeW),
            cornerRadius = androidx.compose.ui.geometry.CornerRadius(
                radius - strokeW / 2f,
                radius - strokeW / 2f,
            ),
            style = androidx.compose.ui.graphics.drawscope.Stroke(width = strokeW),
        )
    }
}

@Composable
private fun PlateGlyph(state: PlateState) {
    when (state) {
        PlateState.ERROR -> Box(
            modifier = Modifier
                .size(104.dp)
                .clip(CircleShape)
                .background(Theme.errorWash),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                imageVector = Icons.sad,
                contentDescription = null,
                tint = Theme.errorText,
                modifier = Modifier.size(52.dp),
            )
        }

        PlateState.CONNECTING -> Box(
            modifier = Modifier.size(104.dp),
            contentAlignment = Alignment.Center,
        ) {
            PulseRings()
            BreathingPower()
        }

        else -> {
            val on = state == PlateState.ON
            // На светлой канве белый круг с 6% прозрачности не видно вовсе —
            // там подложка берётся из вложенного тона.
            val restCircle = if (Theme.isLight) Theme.tile else Color.White.copy(alpha = 0.06f)
            val circle by animateColorAsState(
                targetValue = if (on) Color.White.copy(alpha = 0.18f) else restCircle,
                animationSpec = tween(280),
                label = "plateCircle",
            )
            val glyph by animateColorAsState(
                targetValue = if (on) Color.White else Theme.textMuted,
                animationSpec = tween(280),
                label = "plateGlyph",
            )
            Box(
                modifier = Modifier
                    .size(104.dp)
                    .clip(CircleShape)
                    .background(circle),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    imageVector = Icons.power,
                    contentDescription = null,
                    tint = glyph,
                    modifier = Modifier.size(42.dp),
                )
            }
        }
    }
}

@Composable
private fun BreathingPower() {
    val t = rememberInfiniteTransition(label = "breathe")
    val scale by t.animateFloat(
        initialValue = 1f,
        targetValue = 1.09f,
        animationSpec = infiniteRepeatable(tween(1300, easing = Theme.easeStandard), RepeatMode.Reverse),
        label = "breatheScale",
    )
    val alpha by t.animateFloat(
        initialValue = 0.62f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(1300, easing = Theme.easeStandard), RepeatMode.Reverse),
        label = "breatheAlpha",
    )
    Icon(
        imageVector = Icons.power,
        contentDescription = null,
        tint = Color.White,
        modifier = Modifier
            .size(40.dp)
            .graphicsLayer {
                scaleX = scale
                scaleY = scale
                this.alpha = alpha
            },
    )
}

@Composable
private fun PulseRings() {
    val t = rememberInfiniteTransition(label = "rings")
    val a by t.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(2200, easing = androidx.compose.animation.core.LinearEasing)),
        label = "ringA",
    )
    val b by t.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            tween(2200, delayMillis = 1100, easing = androidx.compose.animation.core.LinearEasing),
        ),
        label = "ringB",
    )
    Canvas(Modifier.size(104.dp)) {
        listOf(a, b).forEach { p ->
            val scale = 0.72f + p * 0.78f
            drawCircle(
                color = Color.White.copy(alpha = (1f - p) * 0.45f),
                radius = size.minDimension / 2f * scale,
                center = center,
                style = androidx.compose.ui.graphics.drawscope.Stroke(width = 1.5.dp.toPx()),
            )
        }
    }
}

/**
 * Жидкость поднимается неравномерно: доходит до 44% и почти две секунды
 * стоит — столько мы ждём ответа узла. Ровный прогресс врал бы.
 */
@Composable
private fun LiquidFill() {
    val t = rememberInfiniteTransition(label = "liquid")
    val level by t.animateFloat(
        initialValue = 0f,
        targetValue = 1.04f,
        animationSpec = InfiniteRepeatableSpec(
            animation = keyframes {
                durationMillis = CYCLE
                0f at 0
                0.22f at 900
                0.38f at 2340
                0.41f at 2700
                0.44f at 4680
                1.04f at 6300
                1.04f at CYCLE
            },
        ),
        label = "level",
    )
    val phase by t.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            tween(2400, easing = androidx.compose.animation.core.LinearEasing),
        ),
        label = "wavePhase",
    )
    val phase2 by t.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            tween(3600, easing = androidx.compose.animation.core.LinearEasing),
        ),
        label = "wavePhase2",
    )
    val phase3 by t.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            tween(5400, easing = androidx.compose.animation.core.LinearEasing),
        ),
        label = "wavePhase3",
    )

    Canvas(Modifier.fillMaxSize()) {
        val top = size.height * (1f - level.coerceIn(0f, 1.04f))
        val brand = Brush.verticalGradient(
            0f to Color(0xFFFF7A3D),
            0.5f to Color(0xFFFA4C16),
            1f to Color(0xFFD93A05),
            startY = 0f,
            endY = size.height,
        )
        drawWave(top, phase, 9.dp.toPx(), brand, 0.45f)
        drawWave(top + 4.dp.toPx(), -phase2, 7.dp.toPx(), brand, 0.7f)
        drawWave(top + 9.dp.toPx(), phase3, 5.dp.toPx(), brand, 1f)

        // Две капли под поверхностью — эффект жидкости без Canvas-физики.
        val bob = sin(phase2 * 2f * Math.PI).toFloat()
        drawCircle(
            brush = Brush.radialGradient(
                listOf(Color.White.copy(alpha = 0.14f), Color.Transparent),
                center = Offset(size.width * 0.28f, size.height * 0.72f + bob * 6f),
                radius = 46.dp.toPx(),
            ),
            radius = 46.dp.toPx(),
            center = Offset(size.width * 0.28f, size.height * 0.72f + bob * 6f),
        )
        drawCircle(
            brush = Brush.radialGradient(
                listOf(Color.White.copy(alpha = 0.10f), Color.Transparent),
                center = Offset(size.width * 0.74f, size.height * 0.82f - bob * 8f),
                radius = 38.dp.toPx(),
            ),
            radius = 38.dp.toPx(),
            center = Offset(size.width * 0.74f, size.height * 0.82f - bob * 8f),
        )
    }
}

private fun androidx.compose.ui.graphics.drawscope.DrawScope.drawWave(
    top: Float,
    phase: Float,
    amplitude: Float,
    brush: Brush,
    alpha: Float,
) {
    if (top >= size.height) return
    val path = Path()
    val step = 6f
    path.moveTo(0f, size.height)
    path.lineTo(0f, top)
    var x = 0f
    while (x <= size.width) {
        val y = top + sin((x / size.width * 2f + phase) * 2f * Math.PI).toFloat() * amplitude
        path.lineTo(x, y)
        x += step
    }
    path.lineTo(size.width, size.height)
    path.close()
    drawPath(path, brush, alpha = alpha)
}

/**
 * Хромированные объекты кабинета прилетают из-за краёв, когда связь поднялась,
 * и дальше медленно левитируют с разными периодами — движение не должно
 * выглядеть синхронным.
 */
@Composable
private fun ChromeObjects() {
    val t = rememberInfiniteTransition(label = "chrome")
    val drift by t.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(6000, easing = Theme.easeStandard), RepeatMode.Reverse),
        label = "drift",
    )
    val drift2 by t.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(7500, easing = Theme.easeStandard), RepeatMode.Reverse),
        label = "drift2",
    )
    val arrive by animateFloatAsState(
        targetValue = 1f,
        animationSpec = tween(700, easing = Theme.easeArrive),
        label = "arrive",
    )

    Box(Modifier.fillMaxSize()) {
        Image(
            painter = painterResource(R.drawable.obj_ring_chrome),
            contentDescription = null,
            modifier = Modifier
                .align(Alignment.BottomStart)
                .size(150.dp)
                .graphicsLayer {
                    // Держим объекты по краям: в центре плиты стоит текст
                    // состояния, и перечёркивать его нельзя.
                    alpha = 0.42f * arrive
                    translationX = (-62).dp.toPx() + (1f - arrive) * 14.dp.toPx()
                    translationY = 62.dp.toPx() - drift * 12.dp.toPx() + (1f - arrive) * 18.dp.toPx()
                    rotationZ = -8f + drift * 6f
                    scaleX = 0.82f + arrive * 0.18f
                    scaleY = 0.82f + arrive * 0.18f
                },
        )
        Image(
            painter = painterResource(R.drawable.obj_mask_chrome),
            contentDescription = null,
            modifier = Modifier
                .align(Alignment.TopEnd)
                .size(104.dp)
                .graphicsLayer {
                    alpha = 0.36f * arrive
                    translationX = 48.dp.toPx() + (1f - arrive) * 14.dp.toPx()
                    translationY = (-40).dp.toPx() + drift2 * 8.dp.toPx() + (1f - arrive) * 18.dp.toPx()
                    rotationZ = 10f - drift2 * 6f
                    scaleX = 0.82f + arrive * 0.18f
                    scaleY = 0.82f + arrive * 0.18f
                },
        )
    }
}

@Composable
private fun plateChipColor(state: PlateState): Color = when (state) {
    PlateState.ERROR -> Theme.errorText
    else -> Theme.textMuted
}

@Composable
private fun plateChipBackground(state: PlateState): Color = when (state) {
    PlateState.ON -> Color.White.copy(alpha = 0.20f)
    PlateState.ERROR -> Theme.errorWash
    else -> if (Theme.isLight) Theme.tile else Color.White.copy(alpha = 0.08f)
}
