package com.prostovpn.app

import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.Easing
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.TweenSpec
import androidx.compose.animation.core.tween
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * Токены кабинета prostovpn.cc, перенесённые один в один.
 *
 * Тёмная тема основная, светлая обязательна: обе описаны здесь целиком, а не
 * наложением поверх одной. Палитра живёт наблюдаемым состоянием — экранам
 * достаточно читать `Theme.text`, и при смене темы перерисуется всё разом.
 */
@Immutable
data class Palette(
    val isLight: Boolean,

    // Канва: три остановки вертикального градиента под свечением состояния.
    val canvasTop: Color,
    val canvasMid: Color,
    val canvasBottom: Color,

    // Стекло: заливка, непрозрачная замена для API < 31 и верхний блик.
    val glassFill: Color,
    val glassOpaque: Color,
    val glassHighlight: Color,

    val tile: Color,
    val tileDeep: Color,
    val hair: Color,
    val ghostStroke: Color,

    val text: Color,
    val textMuted: Color,
    val textFaint: Color,
    val onAccent: Color,

    val accent: Color,
    val accentPressed: Color,
    val accentWash: Color,
    val accentText: Color,

    val success: Color,
    val successWash: Color,
    val error: Color,
    val errorText: Color,
    val errorWash: Color,
    val warning: Color,
    val warningText: Color,
    val warningWash: Color,
    val info: Color,
    val infoWash: Color,

    val shadowLift: Color,
    val shadowPlate: Color,
    val shadowAccent: Color,
)

val DarkPalette = Palette(
    isLight = false,
    canvasTop = Color(0xFF101012),
    canvasMid = Color(0xFF0B0B0C),
    canvasBottom = Color(0xFF0A0A0B),
    glassFill = Color.White.copy(alpha = 0.05f),
    glassOpaque = Color(0xFF29292B),
    glassHighlight = Color.White.copy(alpha = 0.11f),
    tile = Color(0xFF343437),
    tileDeep = Color.White.copy(alpha = 0.12f),
    hair = Color.White.copy(alpha = 0.07f),
    ghostStroke = Color.White.copy(alpha = 0.13f),
    text = Color(0xFFF2F2F3),
    textMuted = Color(0xFFA5A5AA),
    textFaint = Color(0xFF7C7C82),
    onAccent = Color.White,
    accent = Color(0xFFFA4C16),
    accentPressed = Color(0xFFFF6334),
    accentWash = Color(0xFFFA4C16).copy(alpha = 0.14f),
    accentText = Color(0xFFFF8A5C),
    success = Color(0xFF34C759),
    successWash = Color(0xFF34C759).copy(alpha = 0.16f),
    error = Color(0xFFFF453A),
    errorText = Color(0xFFFF6B60),
    errorWash = Color(0xFFFF453A).copy(alpha = 0.13f),
    warning = Color(0xFFFFA326),
    warningText = Color(0xFFFFB65C),
    warningWash = Color(0xFFFFA326).copy(alpha = 0.12f),
    info = Color(0xFF5B9DFF),
    infoWash = Color(0xFF5B9DFF).copy(alpha = 0.13f),
    shadowLift = Color.Black.copy(alpha = 0.50f),
    shadowPlate = Color.Black.copy(alpha = 0.50f),
    shadowAccent = Color(0xFFFA4C16).copy(alpha = 0.36f),
)

val LightPalette = Palette(
    isLight = true,
    canvasTop = Color(0xFFFFFFFF),
    canvasMid = Color(0xFFF3F5F9),
    canvasBottom = Color(0xFFDEE2E9),
    glassFill = Color.White.copy(alpha = 0.72f),
    glassOpaque = Color(0xFFFFFFFF),
    glassHighlight = Color.White.copy(alpha = 0.95f),
    tile = Color(0xFFF2F3F7),
    tileDeep = Color(0xFFDDE0E7),
    hair = Color(0xFF0A0E14).copy(alpha = 0.07f),
    ghostStroke = Color(0xFF0A0E14).copy(alpha = 0.14f),
    text = Color(0xFF0A0A0A),
    textMuted = Color(0xFF5A6069),
    textFaint = Color(0xFF8A9099),
    onAccent = Color.White,
    accent = Color(0xFFFA4C16),
    accentPressed = Color(0xFFFF6334),
    accentWash = Color(0xFFFFF1EA),
    accentText = Color(0xFFFA4C16),
    success = Color(0xFF2AAE4C),
    successWash = Color(0xFFE7F7EC),
    error = Color(0xFFE0332A),
    errorText = Color(0xFFE0332A),
    errorWash = Color(0xFFFFEAE8),
    warning = Color(0xFFFFA326),
    warningText = Color(0xFFB4740A),
    warningWash = Color(0xFFFFF3E0),
    info = Color(0xFF5B9DFF),
    infoWash = Color(0xFFE9F1FF),
    shadowLift = Color(0xFF141922).copy(alpha = 0.10f),
    shadowPlate = Color(0xFF141922).copy(alpha = 0.14f),
    shadowAccent = Color(0xFFFA4C16).copy(alpha = 0.30f),
)

object Theme {
    var palette by mutableStateOf(DarkPalette)

    val isLight get() = palette.isLight

    val canvasTop get() = palette.canvasTop
    val canvasMid get() = palette.canvasMid
    val canvasBottom get() = palette.canvasBottom

    val glassFill get() = palette.glassFill
    val glassOpaque get() = palette.glassOpaque
    val glassHighlight get() = palette.glassHighlight
    val tile get() = palette.tile
    val tileDeep get() = palette.tileDeep
    val hair get() = palette.hair
    val ghostStroke get() = palette.ghostStroke

    val text get() = palette.text
    val textMuted get() = palette.textMuted
    val textFaint get() = palette.textFaint
    val onAccent get() = palette.onAccent

    val accent get() = palette.accent
    val accentPressed get() = palette.accentPressed
    val accentWash get() = palette.accentWash
    val accentText get() = palette.accentText

    val success get() = palette.success
    val successWash get() = palette.successWash
    val error get() = palette.error
    val errorText get() = palette.errorText
    val errorWash get() = palette.errorWash
    val warning get() = palette.warning
    val warningText get() = palette.warningText
    val warningWash get() = palette.warningWash
    val info get() = palette.info
    val infoWash get() = palette.infoWash

    val shadowLift get() = palette.shadowLift
    val shadowPlate get() = palette.shadowPlate
    val shadowAccent get() = palette.shadowAccent

    /** Фирменный градиент кабинета, 118° — им залиты плита «вкл» и все CTA. */
    val brandGradient = Brush.linearGradient(
        0f to Color(0xFFFF7A3D),
        0.46f to Color(0xFFFA4C16),
        1f to Color(0xFFD93A05),
    )

    val canvas get() = Brush.verticalGradient(
        0f to palette.canvasTop,
        0.46f to palette.canvasMid,
        1f to palette.canvasBottom,
    )

    val easeStandard: Easing = FastOutSlowInEasing
    val easeOut: Easing = CubicBezierEasing(0f, 0f, 0.58f, 1f)
    val easeArrive: Easing = CubicBezierEasing(0.2f, 0.9f, 0.25f, 1f)

    fun <T> spring(durationMs: Int = 250): TweenSpec<T> = tween(durationMs, easing = easeStandard)
}

object R2 {
    val plate = 32.dp
    val card = 26.dp
    val tile = 18.dp
    val field = 16.dp
}

/**
 * Шрифт кабинета. ProstoDisplay (Rothorn) кириллицы не содержит — на сайте
 * русский текст всегда рисует Onest из той же связки, поэтому в приложении
 * Onest и есть основное начертание, а ProstoDisplay остаётся для латиницы и
 * цифр: код страны, таймер, версия.
 */
val ProstoSans = FontFamily(
    Font(R.font.onest_regular, FontWeight.Normal),
    Font(R.font.onest_medium, FontWeight.Medium),
    Font(R.font.onest_semibold, FontWeight.SemiBold),
    Font(R.font.onest_bold, FontWeight.Bold),
    Font(R.font.onest_extrabold, FontWeight.ExtraBold),
)

val ProstoDisplay = FontFamily(
    Font(R.font.prosto_regular, FontWeight.Normal),
    Font(R.font.prosto_medium, FontWeight.Medium),
    Font(R.font.prosto_semibold, FontWeight.SemiBold),
    Font(R.font.prosto_bold, FontWeight.Bold),
    Font(R.font.prosto_bold, FontWeight.ExtraBold),
)

/**
 * Единый конструктор стиля.
 *
 * `tabular` включает моноширинные цифры: без него таймер и трафик дёргают
 * строку на каждом такте.
 */
fun pro(
    size: TextUnit,
    weight: FontWeight,
    color: Color = Theme.text,
    tracking: TextUnit = TextUnit.Unspecified,
    lineHeight: TextUnit = TextUnit.Unspecified,
    tabular: Boolean = false,
    display: Boolean = false,
): TextStyle = TextStyle(
    fontFamily = if (display) ProstoDisplay else ProstoSans,
    fontSize = size,
    fontWeight = weight,
    color = color,
    letterSpacing = tracking,
    lineHeight = lineHeight,
    fontFeatureSettings = if (tabular) "tnum" else null,
)

/** Трекинг из таблицы токенов: −0.035em и подобное, в долях кегля. */
fun em(size: TextUnit, value: Float): TextUnit = (size.value * value).sp

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
