package com.alisavpn.app

import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color

object Theme {
    val bgTop = Color(0xFF170E12)
    val bgBottom = Color(0xFF100A0C)
    val accent = Color(0xFFFF4D5E)
    val accentDeep = Color(0xFFE0284F)
    val accentSoft = Color(0xFFFF7A8A)
    val vibrant = Color(0xFFFF5A6E)
    val text = Color(0xFFEEF2FF)

    val textMuted = text.copy(alpha = 0.45f)
    val textFaint = text.copy(alpha = 0.28f)
    val glyphOff = text.copy(alpha = 0.55f)

    val card = Color.White.copy(alpha = 0.045f)
    val divider = Color.White.copy(alpha = 0.06f)
    val accentTint = accent.copy(alpha = 0.12f)

    val background = Brush.verticalGradient(listOf(bgTop, bgBottom))
    val accentGradient = Brush.linearGradient(listOf(accent, accentDeep))
}

fun flagEmoji(countryCode: String): String =
    countryCode.uppercase().map { char ->
        String(Character.toChars(127397 + char.code))
    }.joinToString("")
