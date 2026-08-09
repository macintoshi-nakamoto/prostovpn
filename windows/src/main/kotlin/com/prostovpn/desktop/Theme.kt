package com.prostovpn.desktop

import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.Easing
import androidx.compose.animation.core.TweenSpec
import androidx.compose.animation.core.tween
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.platform.Font
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.sp

object Theme {
    val bgTop = Color(0xFF1A110B)
    val bgBottom = Color(0xFF120C08)
    val sheetTop = Color(0xFF241710)
    val sheetBottom = Color(0xFF170F0A)

    val accent = Color(0xFFFF5000)
    val accentWarm = Color(0xFFFF711F)
    val accentDeep = Color(0xFFFF4000)
    val link = Color(0xFFFF6A1F)
    val accentSoft = Color(0xFFFF8A50)
    val accentHover = Color(0xFFFFB184)

    val text = Color(0xFFEEF2FF)

    val textSecondary = text.copy(alpha = 0.45f)
    val textMuted = text.copy(alpha = 0.40f)
    val textTertiary = text.copy(alpha = 0.35f)
    val textFaint = text.copy(alpha = 0.28f)
    val glyphOff = text.copy(alpha = 0.55f)

    val card = Color.White.copy(alpha = 0.045f)
    val rowActive = Color.White.copy(alpha = 0.05f)
    val divider = Color.White.copy(alpha = 0.06f)
    val accentTint08 = accent.copy(alpha = 0.08f)
    val accentTint10 = accent.copy(alpha = 0.10f)
    val accentTint12 = accent.copy(alpha = 0.12f)
    val accentTint14 = accent.copy(alpha = 0.14f)

    val success = Color(0xFF2EC27E)
    val successDeep = Color(0xFF27A06A)

    val background = Brush.verticalGradient(listOf(bgTop, bgBottom))
    val accentGradient = Brush.linearGradient(listOf(accent, accentDeep))
    val primaryGradient = Brush.linearGradient(listOf(accentWarm, accentDeep))
    val successGradient = Brush.linearGradient(listOf(success, successDeep))
    val sheetGradient = Brush.verticalGradient(listOf(sheetTop, sheetBottom))

    // iOS: .timingCurve(0.3, 0.9, 0.3, 1, duration:)
    val springEasing: Easing = CubicBezierEasing(0.3f, 0.9f, 0.3f, 1f)

    fun <T> spring(durationMs: Int = 250): TweenSpec<T> = tween(durationMs, easing = springEasing)
}

val ManropeFamily = FontFamily(
    Font(resource = "fonts/manrope_regular.ttf", weight = FontWeight.Normal),
    Font(resource = "fonts/manrope_medium.ttf", weight = FontWeight.Medium),
    Font(resource = "fonts/manrope_semibold.ttf", weight = FontWeight.SemiBold),
    Font(resource = "fonts/manrope_bold.ttf", weight = FontWeight.Bold),
    Font(resource = "fonts/manrope_extrabold.ttf", weight = FontWeight.ExtraBold),
)

fun manrope(
    size: TextUnit,
    weight: FontWeight,
    color: Color = Theme.text,
    letterSpacing: TextUnit = TextUnit.Unspecified,
): TextStyle = TextStyle(
    fontFamily = ManropeFamily,
    fontSize = size,
    fontWeight = weight,
    color = color,
    letterSpacing = letterSpacing,
)

/** iOS Manrope weights → Compose */
object W {
    val regular = FontWeight.Normal
    val medium = FontWeight.Medium
    val semibold = FontWeight.SemiBold
    val bold = FontWeight.Bold
    val extraBold = FontWeight.ExtraBold
}

fun flagEmoji(countryCode: String): String =
    countryCode.uppercase().map { char ->
        String(Character.toChars(127397 + char.code))
    }.joinToString("")
