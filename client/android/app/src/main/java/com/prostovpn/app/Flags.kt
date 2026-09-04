package com.prostovpn.app

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathOperation
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipPath
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/*
 * Флаги рисуются, а не берутся эмодзи: прошивки Android рисуют эмодзи-флаги
 * по-разному, часть вообще показывает две буквы. Здесь — те же цвета, что в
 * макете, и одинаковый круг на всех устройствах.
 */

private val WHITE = Color(0xFFF4F4F6)

private data class Stripes(val horizontal: Boolean, val colors: List<Color>)

private val PATTERNS: Map<String, Stripes> = mapOf(
    "NL" to Stripes(true, listOf(Color(0xFFAE1C28), WHITE, Color(0xFF21468B))),
    "RU" to Stripes(true, listOf(WHITE, Color(0xFF0039A6), Color(0xFFD52B1E))),
    "DE" to Stripes(true, listOf(Color(0xFF0D0D0D), Color(0xFFDD0000), Color(0xFFFFCE00))),
    "AT" to Stripes(true, listOf(Color(0xFFED2939), WHITE, Color(0xFFED2939))),
    "HU" to Stripes(true, listOf(Color(0xFFCE2939), WHITE, Color(0xFF477050))),
    "BG" to Stripes(true, listOf(WHITE, Color(0xFF00966E), Color(0xFFD62612))),
    "EE" to Stripes(true, listOf(Color(0xFF0072CE), Color(0xFF0D0D0D), WHITE)),
    "LT" to Stripes(true, listOf(Color(0xFFFDB913), Color(0xFF006A44), Color(0xFFC1272D))),
    "LU" to Stripes(true, listOf(Color(0xFFED2939), WHITE, Color(0xFF00A1DE))),
    "IN" to Stripes(true, listOf(Color(0xFFFF9933), WHITE, Color(0xFF138808))),
    "PL" to Stripes(true, listOf(WHITE, Color(0xFFDC143C))),
    "UA" to Stripes(true, listOf(Color(0xFF0057B7), Color(0xFFFFD700))),
    "ID" to Stripes(true, listOf(Color(0xFFCE1126), WHITE)),
    "SG" to Stripes(true, listOf(Color(0xFFEF3340), WHITE)),

    "FR" to Stripes(false, listOf(Color(0xFF0055A4), WHITE, Color(0xFFEF4135))),
    "IT" to Stripes(false, listOf(Color(0xFF009246), WHITE, Color(0xFFCE2B37))),
    "IE" to Stripes(false, listOf(Color(0xFF169B62), WHITE, Color(0xFFFF883E))),
    "BE" to Stripes(false, listOf(Color(0xFF0D0D0D), Color(0xFFFAE042), Color(0xFFED2939))),
    "RO" to Stripes(false, listOf(Color(0xFF002B7F), Color(0xFFFCD116), Color(0xFFCE1126))),
    "MD" to Stripes(false, listOf(Color(0xFF0033A0), Color(0xFFFFD200), Color(0xFFCC092F))),
)

private data class Nordic(val field: Color, val cross: Color, val inner: Color?)

private val NORDIC: Map<String, Nordic> = mapOf(
    "FI" to Nordic(WHITE, Color(0xFF003580), null),
    "SE" to Nordic(Color(0xFF006AA7), Color(0xFFFECC00), null),
    "DK" to Nordic(Color(0xFFC8102E), WHITE, null),
    "NO" to Nordic(Color(0xFFBA0C2F), WHITE, Color(0xFF00205B)),
    "IS" to Nordic(Color(0xFF02529C), WHITE, Color(0xFFDC1E35)),
)

@Composable
fun CountryFlag(code: String?, size: Dp = 34.dp, modifier: Modifier = Modifier) {
    val key = code?.trim()?.uppercase()?.take(2).orEmpty()
    val hairline = Color.Black.copy(alpha = 0.16f)
    val fallbackBg = Theme.accentWash
    val fallbackFg = Theme.accentText
    val density = LocalDensity.current

    Box(
        modifier = modifier.size(size).clip(CircleShape),
        contentAlignment = Alignment.Center,
    ) {
        val known = key in PATTERNS || key in NORDIC || key in SPECIAL
        if (!known) {
            Box(
                Modifier
                    .fillMaxSize()
                    .background(fallbackBg),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = key.ifEmpty { "??" },
                    style = pro(
                        with(density) { (size * 0.36f).toSp() },
                        W.bold,
                        fallbackFg,
                        display = true,
                    ),
                )
            }
        } else {
            Canvas(Modifier.fillMaxSize()) {
                PATTERNS[key]?.let { drawStripes(it) }
                NORDIC[key]?.let { drawNordic(it) }
                SPECIAL[key]?.invoke(this)
                drawCircle(
                    color = hairline,
                    radius = this.size.minDimension / 2f - 0.5f,
                    style = Stroke(width = 1f),
                )
            }
        }
    }
}

private fun DrawScope.drawStripes(pattern: Stripes) {
    val count = pattern.colors.size
    pattern.colors.forEachIndexed { index, color ->
        if (pattern.horizontal) {
            val h = size.height / count
            drawRect(color, topLeft = Offset(0f, h * index), size = Size(size.width, h + 1f))
        } else {
            val w = size.width / count
            drawRect(color, topLeft = Offset(w * index, 0f), size = Size(w + 1f, size.height))
        }
    }
}

private fun DrawScope.drawNordic(flag: Nordic) {
    drawRect(flag.field)
    val armY = size.height * 0.26f
    val armX = size.width * 0.20f
    val thick = size.minDimension * 0.28f
    val inner = size.minDimension * 0.12f

    drawRect(flag.cross, topLeft = Offset(0f, armY), size = Size(size.width, thick))
    drawRect(flag.cross, topLeft = Offset(armX, 0f), size = Size(thick, size.height))
    if (flag.inner != null) {
        val pad = (thick - inner) / 2f
        drawRect(flag.inner, topLeft = Offset(0f, armY + pad), size = Size(size.width, inner))
        drawRect(flag.inner, topLeft = Offset(armX + pad, 0f), size = Size(inner, size.height))
    }
}

private val SPECIAL: Map<String, DrawScope.() -> Unit> = mapOf(
    "US" to {
        val red = Color(0xFFB22234)
        drawRect(WHITE)
        val band = size.height / 7f
        for (i in 0 until 7 step 2) {
            drawRect(red, topLeft = Offset(0f, band * i), size = Size(size.width, band))
        }
        drawRect(
            Color(0xFF3C3B6E),
            size = Size(size.width * 0.46f, band * 4f),
        )
    },
    "GB" to {
        drawRect(Color(0xFF012169))
        val w = size.width
        val h = size.height
        val diag = h * 0.16f
        drawLine(WHITE, Offset(0f, 0f), Offset(w, h), strokeWidth = diag * 1.6f)
        drawLine(WHITE, Offset(w, 0f), Offset(0f, h), strokeWidth = diag * 1.6f)
        drawLine(Color(0xFFC8102E), Offset(0f, 0f), Offset(w, h), strokeWidth = diag * 0.7f)
        drawLine(Color(0xFFC8102E), Offset(w, 0f), Offset(0f, h), strokeWidth = diag * 0.7f)
        drawRect(WHITE, topLeft = Offset(0f, h * 0.36f), size = Size(w, h * 0.28f))
        drawRect(WHITE, topLeft = Offset(w * 0.36f, 0f), size = Size(w * 0.28f, h))
        drawRect(Color(0xFFC8102E), topLeft = Offset(0f, h * 0.42f), size = Size(w, h * 0.16f))
        drawRect(Color(0xFFC8102E), topLeft = Offset(w * 0.42f, 0f), size = Size(w * 0.16f, h))
    },
    "CH" to {
        drawRect(Color(0xFFD52B1E))
        val arm = size.minDimension * 0.20f
        val len = size.minDimension * 0.62f
        drawRect(
            WHITE,
            topLeft = Offset(center.x - len / 2f, center.y - arm / 2f),
            size = Size(len, arm),
        )
        drawRect(
            WHITE,
            topLeft = Offset(center.x - arm / 2f, center.y - len / 2f),
            size = Size(arm, len),
        )
    },
    "JP" to {
        drawRect(WHITE)
        drawCircle(Color(0xFFBC002D), radius = size.minDimension * 0.28f, center = center)
    },
    "TR" to {
        drawRect(Color(0xFFE30A17))
        val r = size.minDimension * 0.24f
        val crescent = Path().apply {
            addOval(Rect(center = Offset(center.x - r * 0.25f, center.y), radius = r))
        }
        val cut = Path().apply {
            addOval(Rect(center = Offset(center.x + r * 0.05f, center.y), radius = r * 0.82f))
        }
        clipPath(Path().apply { op(crescent, cut, PathOperation.Difference) }) {
            drawRect(WHITE)
        }
        rotate(degrees = 18f, pivot = Offset(center.x + r * 1.15f, center.y)) {
            drawCircle(WHITE, radius = r * 0.32f, center = Offset(center.x + r * 1.15f, center.y))
        }
    },
    "CA" to {
        val red = Color(0xFFD52B1E)
        drawRect(WHITE)
        drawRect(red, size = Size(size.width * 0.26f, size.height))
        drawRect(red, topLeft = Offset(size.width * 0.74f, 0f), size = Size(size.width * 0.26f, size.height))
        drawCircle(red, radius = size.minDimension * 0.18f, center = center)
    },
    "CZ" to {
        drawRect(WHITE)
        drawRect(Color(0xFFD7141A), topLeft = Offset(0f, size.height / 2f), size = Size(size.width, size.height / 2f))
        val wedge = Path().apply {
            moveTo(0f, 0f)
            lineTo(size.width * 0.55f, size.height / 2f)
            lineTo(0f, size.height)
            close()
        }
        drawPath(wedge, Color(0xFF11457E))
    },
    "IL" to {
        drawRect(WHITE)
        val band = size.height * 0.14f
        drawRect(Color(0xFF0038B8), topLeft = Offset(0f, size.height * 0.16f), size = Size(size.width, band))
        drawRect(Color(0xFF0038B8), topLeft = Offset(0f, size.height * 0.70f), size = Size(size.width, band))
        drawCircle(Color(0xFF0038B8), radius = size.minDimension * 0.16f, center = center, style = Stroke(width = size.minDimension * 0.05f))
    },
    "ES" to {
        drawRect(Color(0xFFAA151B))
        drawRect(Color(0xFFF1BF00), topLeft = Offset(0f, size.height * 0.25f), size = Size(size.width, size.height * 0.5f))
    },
    "PT" to {
        drawRect(Color(0xFFFF0000))
        drawRect(Color(0xFF006600), size = Size(size.width * 0.42f, size.height))
        drawCircle(Color(0xFFFFE800), radius = size.minDimension * 0.13f, center = Offset(size.width * 0.42f, center.y))
    },
    "BR" to {
        drawRect(Color(0xFF009B3A))
        val d = Path().apply {
            moveTo(center.x, size.height * 0.12f)
            lineTo(size.width * 0.9f, center.y)
            lineTo(center.x, size.height * 0.88f)
            lineTo(size.width * 0.1f, center.y)
            close()
        }
        drawPath(d, Color(0xFFFEDF00))
        drawCircle(Color(0xFF002776), radius = size.minDimension * 0.19f, center = center)
    },
    "AU" to {
        drawRect(Color(0xFF012169))
        drawRect(WHITE, topLeft = Offset(0f, size.height * 0.10f), size = Size(size.width * 0.5f, size.height * 0.09f))
        drawRect(WHITE, topLeft = Offset(size.width * 0.20f, 0f), size = Size(size.width * 0.09f, size.height * 0.5f))
        drawCircle(WHITE, radius = size.minDimension * 0.09f, center = Offset(size.width * 0.72f, size.height * 0.66f))
        drawCircle(WHITE, radius = size.minDimension * 0.06f, center = Offset(size.width * 0.84f, size.height * 0.34f))
    },
    "AE" to {
        drawRect(WHITE)
        drawRect(Color(0xFF00732F), topLeft = Offset(size.width * 0.26f, 0f), size = Size(size.width * 0.74f, size.height / 3f))
        drawRect(Color(0xFF000000), topLeft = Offset(size.width * 0.26f, size.height * 2f / 3f), size = Size(size.width * 0.74f, size.height / 3f))
        drawRect(Color(0xFFFF0000), size = Size(size.width * 0.26f, size.height))
    },
    "KZ" to {
        drawRect(Color(0xFF00AFCA))
        drawCircle(Color(0xFFFEC50C), radius = size.minDimension * 0.17f, center = center)
    },
    "HK" to {
        drawRect(Color(0xFFDE2910))
        drawCircle(WHITE, radius = size.minDimension * 0.20f, center = center)
    },
    "JPX" to { },
)
