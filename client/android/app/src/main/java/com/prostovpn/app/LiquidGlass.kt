package com.prostovpn.app

import android.graphics.RuntimeShader
import android.graphics.Shader
import android.os.Build
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.interaction.InteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.runtime.Composable
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
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asComposeRenderEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.graphics.layer.GraphicsLayer
import androidx.compose.ui.graphics.layer.drawLayer
import androidx.compose.ui.graphics.rememberGraphicsLayer
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import kotlin.math.ceil
import kotlin.math.min

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

private fun saturationEffect(saturation: Float): android.graphics.RenderEffect {
    val matrix = android.graphics.ColorMatrix().apply { setSaturation(saturation) }
    return android.graphics.RenderEffect.createColorFilterEffect(
        android.graphics.ColorMatrixColorFilter(matrix)
    )
}

private fun buildGlassEffect(
    paddedWidth: Float,
    paddedHeight: Float,
    halfWidth: Float,
    halfHeight: Float,
    cornerRadiusPx: Float,
    blurPx: Float,
    saturation: Float,
    refractionBandPx: Float,
    refractionAmountPx: Float,
    dispersion: Float,
): android.graphics.RenderEffect? {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return null

    var effect = saturationEffect(saturation)
    if (blurPx > 0.5f) {
        effect = android.graphics.RenderEffect.createChainEffect(
            android.graphics.RenderEffect.createBlurEffect(blurPx, blurPx, Shader.TileMode.CLAMP),
            effect,
        )
    }
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
        runCatching {
            val shader = RuntimeShader(LIQUID_GLASS_SHADER).apply {
                setFloatUniform("uSize", paddedWidth, paddedHeight)
                setFloatUniform("uHalf", halfWidth, halfHeight)
                setFloatUniform("uRadius", cornerRadiusPx)
                setFloatUniform("uBand", refractionBandPx)
                setFloatUniform("uAmount", refractionAmountPx)
                setFloatUniform("uDispersion", dispersion)
            }
            effect = android.graphics.RenderEffect.createChainEffect(
                android.graphics.RenderEffect.createRuntimeShaderEffect(shader, "content"),
                effect,
            )
        }
    }
    return effect
}

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

    val context = androidx.compose.ui.platform.LocalContext.current
    val weakGpu = remember {
        context.isTv() ||
            (context.getSystemService(android.content.Context.ACTIVITY_SERVICE)
                as? android.app.ActivityManager)?.isLowRamDevice == true
    }

    val opaque = Theme.glassOpaque
    val delta = remember {
        androidx.compose.runtime.derivedStateOf {
            backdrop.positionInWindow - position.value
        }
    }
    this
        .onGloballyPositioned { position.value = it.positionInWindow() }
        .drawWithCache {
            val radiusPx = cornerRadius?.toPx() ?: (size.minDimension / 2f)
            val blurPx = blurRadius.toPx()
            val bandPx = min(refractionHeight.toPx(), size.minDimension / 2f)
            val amountPx = refractionAmount.toPx()
            val padPx = ceil(blurPx * 2f + amountPx)
            val paddedSize = IntSize(
                (size.width + padPx * 2f).toInt(),
                (size.height + padPx * 2f).toInt(),
            )
            val sampled = !weakGpu && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S
            val glassLayer = if (sampled) {
                obtainGraphicsLayer().apply {
                    clip = true
                    renderEffect = buildGlassEffect(
                        paddedWidth = paddedSize.width.toFloat(),
                        paddedHeight = paddedSize.height.toFloat(),
                        halfWidth = size.width / 2f,
                        halfHeight = size.height / 2f,
                        cornerRadiusPx = radiusPx,
                        blurPx = blurPx,
                        saturation = saturation,
                        refractionBandPx = bandPx,
                        refractionAmountPx = amountPx,
                        dispersion = dispersion,
                    )?.asComposeRenderEffect()
                }
            } else {
                null
            }

            val corner = CornerRadius(radiusPx, radiusPx)
            val highlightBrush = Brush.verticalGradient(
                0f to Color.White.copy(alpha = highlightAlpha),
                0.45f to Color.White.copy(alpha = 0.035f),
                1f to Color.White.copy(alpha = highlightAlpha * 0.45f),
            )

            onDrawWithContent {
                val src = backdrop.layer
                if (glassLayer != null && src != null) {
                    val d = delta.value
                    glassLayer.record(size = paddedSize) {
                        translate(padPx + d.x, padPx + d.y) {
                            drawLayer(src)
                        }
                    }
                    translate(-padPx, -padPx) {
                        drawLayer(glassLayer)
                    }
                    drawRoundRect(
                        color = Color.White.copy(alpha = tintAlpha),
                        cornerRadius = corner,
                    )
                } else {
                    // API < 31 или слабый GPU: сплошная подложка вместо
                    // размытия — та же геометрия, тень чуть плотнее.
                    drawRoundRect(color = opaque, cornerRadius = corner)
                }
                val strokeW = 1.2.dp.toPx()
                drawRoundRect(
                    brush = highlightBrush,
                    topLeft = Offset(strokeW / 2f, strokeW / 2f),
                    size = androidx.compose.ui.geometry.Size(size.width - strokeW, size.height - strokeW),
                    cornerRadius = CornerRadius(radiusPx - strokeW / 2f, radiusPx - strokeW / 2f),
                    style = Stroke(width = strokeW),
                )
                drawContent()
            }
        }
}

fun Modifier.pressScale(
    interactionSource: InteractionSource,
    pressedScale: Float = 0.96f,
): Modifier = composed {
    val pressed by interactionSource.collectIsPressedAsState()
    val scaleValue by animateFloatAsState(
        targetValue = if (pressed) pressedScale else 1f,
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

fun Modifier.pressHighlight(
    interactionSource: InteractionSource,
    maxAlpha: Float = 0.07f,
): Modifier = composed {
    val pressed by interactionSource.collectIsPressedAsState()
    val highlight by animateFloatAsState(
        targetValue = if (pressed) 1f else 0f,
        animationSpec = if (pressed) {
            androidx.compose.animation.core.tween(80)
        } else {
            androidx.compose.animation.core.tween(350)
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
