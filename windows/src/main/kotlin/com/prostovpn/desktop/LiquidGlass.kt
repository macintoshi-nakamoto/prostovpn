package com.prostovpn.desktop

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.interaction.InteractionSource
import androidx.compose.foundation.interaction.collectIsHoveredAsState
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.draw.scale
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.drawIntoCanvas
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.graphics.layer.GraphicsLayer
import androidx.compose.ui.graphics.layer.drawLayer
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.rememberGraphicsLayer
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import org.jetbrains.skia.ColorMatrix
import org.jetbrains.skia.FilterTileMode
import org.jetbrains.skia.ImageFilter
import org.jetbrains.skia.Paint as SkiaPaint
import org.jetbrains.skia.Rect as SkiaRect
import org.jetbrains.skia.RuntimeEffect
import org.jetbrains.skia.RuntimeShaderBuilder
import kotlin.math.ceil
import kotlin.math.min

/**
 * Liquid Glass (iOS 26 glassEffect) для Compose Desktop.
 *
 * Тот же принцип, что и в Android-клиенте: фон записывается в общий [GraphicsLayer],
 * стеклянный элемент рисует его под собой через цепочку Skia-фильтров:
 * насыщенность → размытие → SkSL-шейдер преломления по кромке линзы с дисперсией.
 * Skia выполняет тот же шейдер, что AGSL на Android, — эффект идентичен.
 */
class BackdropState {
    internal var layer: GraphicsLayer? by mutableStateOf(null)
    internal var positionInWindow by mutableStateOf(Offset.Zero)
}

@Composable
fun rememberBackdropState(): BackdropState {
    val layer = rememberGraphicsLayer()
    val state = remember { BackdropState() }
    state.layer = layer
    return state
}

/** Помечает содержимое как «фон», который сэмплируют стеклянные элементы. */
fun Modifier.backdropSource(state: BackdropState): Modifier = this
    .onGloballyPositioned { state.positionInWindow = it.positionInWindow() }
    .drawWithContent {
        val layer = state.layer
        if (layer != null) {
            layer.record {
                this@drawWithContent.drawContent()
            }
            drawLayer(layer)
        } else {
            drawContent()
        }
    }

private const val LIQUID_GLASS_SHADER = """
uniform shader content;
uniform float2 uSize;
uniform float2 uHalf;
uniform float uRadius;
uniform float uBand;
uniform float uAmount;
uniform float uDispersion;

float sdBox(float2 p, float2 b, float r) {
    float2 q = abs(p) - b + r;
    return min(max(q.x, q.y), 0.0) + length(max(q, float2(0.0, 0.0))) - r;
}

half4 main(float2 coord) {
    float2 center = uSize * 0.5;
    float2 p = coord - center;
    float d = sdBox(p, uHalf, uRadius);
    if (d >= 0.0) {
        return content.eval(coord);
    }
    float t = clamp(1.0 + d / uBand, 0.0, 1.0);
    if (t <= 0.001) {
        return content.eval(coord);
    }
    float e = 1.0;
    float gx = sdBox(p + float2(e, 0.0), uHalf, uRadius) - sdBox(p - float2(e, 0.0), uHalf, uRadius);
    float gy = sdBox(p + float2(0.0, e), uHalf, uRadius) - sdBox(p - float2(0.0, e), uHalf, uRadius);
    float2 g = float2(gx, gy);
    float glen = max(length(g), 0.0001);
    float2 n = g / glen;
    float s = t * t * (3.0 - 2.0 * t);
    float curve = s * s;
    float amt = uAmount * curve;
    float2 offG = n * amt;
    float2 offR = offG * (1.0 + uDispersion);
    float2 offB = offG * (1.0 - uDispersion);
    half4 sR = content.eval(coord + offR);
    half4 sG = content.eval(coord + offG);
    half4 sB = content.eval(coord + offB);
    float4 col = float4(sR.r, sG.g, sB.b, sG.a);
    col.rgb = clamp(col.rgb + 0.045 * curve, 0.0, 1.0);
    return half4(col);
}
"""

private val glassEffect: RuntimeEffect by lazy {
    RuntimeEffect.makeForShader(LIQUID_GLASS_SHADER.trimIndent())
}

private fun saturationMatrix(s: Float): ColorMatrix {
    val lr = 0.2126f
    val lg = 0.7152f
    val lb = 0.0722f
    val inv = 1f - s
    return ColorMatrix(
        lr * inv + s, lg * inv, lb * inv, 0f, 0f,
        lr * inv, lg * inv + s, lb * inv, 0f, 0f,
        lr * inv, lg * inv, lb * inv + s, 0f, 0f,
        0f, 0f, 0f, 1f, 0f,
    )
}

private fun buildGlassFilter(
    width: Float,
    height: Float,
    cornerRadiusPx: Float,
    blurPx: Float,
    saturation: Float,
    refractionBandPx: Float,
    refractionAmountPx: Float,
    dispersion: Float,
): ImageFilter? = runCatching {
    var filter: ImageFilter = ImageFilter.makeColorFilter(
        org.jetbrains.skia.ColorFilter.makeMatrix(saturationMatrix(saturation)),
        null,
        null,
    )
    if (blurPx > 0.5f) {
        filter = ImageFilter.makeBlur(blurPx * 0.5f, blurPx * 0.5f, FilterTileMode.CLAMP, filter, null)
    }
    val builder = RuntimeShaderBuilder(glassEffect).apply {
        uniform("uSize", width, height)
        uniform("uHalf", width / 2f, height / 2f)
        uniform("uRadius", cornerRadiusPx)
        uniform("uBand", refractionBandPx)
        uniform("uAmount", refractionAmountPx)
        uniform("uDispersion", dispersion)
    }
    ImageFilter.makeRuntimeShader(builder, "content", filter)
}.getOrNull()

/**
 * Стеклянная поверхность, сэмплирующая [backdrop] позади элемента.
 * Применять после `clip(shape)`; [cornerRadius] = null — круг/капсула.
 */
fun Modifier.liquidGlass(
    backdrop: BackdropState,
    cornerRadius: Dp? = null,
    blurRadius: Dp = 20.dp,
    saturation: Float = 1.6f,
    refractionHeight: Dp = 14.dp,
    refractionAmount: Dp = 15.dp,
    dispersion: Float = 0.16f,
    tintAlpha: Float = 0.05f,
    highlightAlpha: Float = 0.20f,
): Modifier = composed {
    val position = remember { mutableStateOf(Offset.Zero) }
    // Относительный сдвиг фон→элемент: при совместном движении delta не меняется —
    // стекло не пересчитывает blur+шейдер каждый кадр.
    val delta = remember {
        derivedStateOf { backdrop.positionInWindow - position.value }
    }
    this
        .onGloballyPositioned { position.value = it.positionInWindow() }
        .drawWithCache {
            val radiusPx = cornerRadius?.toPx() ?: (size.minDimension / 2f)
            val blurPx = blurRadius.toPx()
            val bandPx = min(refractionHeight.toPx(), size.minDimension / 2f)
            val amountPx = refractionAmount.toPx()
            val padPx = ceil(blurPx * 2f + amountPx)

            // Фильтр работает в координатах элемента: начало отсчёта холста
            // внутри узла — его левый верхний угол.
            val filter = buildGlassFilter(
                width = size.width,
                height = size.height,
                cornerRadiusPx = radiusPx,
                blurPx = blurPx,
                saturation = saturation,
                refractionBandPx = bandPx,
                refractionAmountPx = amountPx,
                dispersion = dispersion,
            )

            val corner = CornerRadius(radiusPx, radiusPx)
            val highlightBrush = Brush.verticalGradient(
                0f to Color.White.copy(alpha = highlightAlpha),
                0.45f to Color.White.copy(alpha = 0.035f),
                1f to Color.White.copy(alpha = highlightAlpha * 0.45f),
            )

            onDrawWithContent {
                val src = backdrop.layer
                if (src != null && filter != null) {
                    val d = delta.value
                    drawIntoCanvas { canvas ->
                        val native = canvas.nativeCanvas
                        val paint = SkiaPaint().apply { imageFilter = filter }
                        // saveLayer с запасом по краям: размытию нужны пиксели
                        // за границей элемента, иначе кромка «сереет»
                        native.saveLayer(
                            SkiaRect.makeLTRB(
                                -padPx,
                                -padPx,
                                size.width + padPx,
                                size.height + padPx,
                            ),
                            paint,
                        )
                        translate(d.x, d.y) {
                            drawLayer(src)
                        }
                        native.restore()
                    }
                    drawRoundRect(
                        color = Color.White.copy(alpha = tintAlpha),
                        cornerRadius = corner,
                    )
                } else {
                    // Фон недоступен — рисуем непрозрачный материал, чтобы
                    // сквозь панель никогда не просвечивал контент под ней
                    drawRoundRect(
                        color = Color(0xFF241710),
                        cornerRadius = corner,
                    )
                    drawRoundRect(
                        color = Color.White.copy(alpha = 0.06f),
                        cornerRadius = corner,
                    )
                }
                val strokeW = 1.2.dp.toPx()
                drawRoundRect(
                    brush = highlightBrush,
                    topLeft = Offset(strokeW / 2f, strokeW / 2f),
                    size = Size(size.width - strokeW, size.height - strokeW),
                    cornerRadius = CornerRadius(radiusPx - strokeW / 2f, radiusPx - strokeW / 2f),
                    style = Stroke(width = strokeW),
                )
                drawContent()
            }
        }
}

/**
 * Масштаб при нажатии — мгновенный отклик, упругий возврат;
 * на десктопе добавляется лёгкое увеличение при наведении.
 */
fun Modifier.pressScale(
    interactionSource: InteractionSource,
    pressedScale: Float = 0.96f,
    hoverScale: Float = 1.02f,
): Modifier = composed {
    val pressed by interactionSource.collectIsPressedAsState()
    val hovered by interactionSource.collectIsHoveredAsState()
    val target = when {
        pressed -> pressedScale
        hovered -> hoverScale
        else -> 1f
    }
    val scaleValue by animateFloatAsState(
        targetValue = target,
        animationSpec = if (pressed) {
            androidx.compose.animation.core.tween(
                durationMillis = 110,
                easing = androidx.compose.animation.core.CubicBezierEasing(0.2f, 0f, 0.4f, 1f),
            )
        } else {
            androidx.compose.animation.core.spring(
                dampingRatio = 0.55f,
                stiffness = 420f,
            )
        },
        label = "pressScale",
    )
    this.scale(scaleValue)
}

/** Подсветка стекла при нажатии/наведении — как у интерактивного glass в iOS 26. */
fun Modifier.pressHighlight(
    interactionSource: InteractionSource,
    maxAlpha: Float = 0.07f,
): Modifier = composed {
    val pressed by interactionSource.collectIsPressedAsState()
    val hovered by interactionSource.collectIsHoveredAsState()
    val target = when {
        pressed -> 1f
        hovered -> 0.55f
        else -> 0f
    }
    val highlight by animateFloatAsState(
        targetValue = target,
        animationSpec = if (pressed) {
            androidx.compose.animation.core.tween(80)
        } else {
            androidx.compose.animation.core.tween(300)
        },
        label = "pressHighlight",
    )
    drawWithContent {
        drawContent()
        if (highlight > 0.01f) {
            drawRect(Color.White.copy(alpha = maxAlpha * highlight))
        }
    }
}
