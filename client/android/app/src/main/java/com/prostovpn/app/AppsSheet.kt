package com.prostovpn.app

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Лист «Приложения мимо VPN».
 *
 * Отмечаешь банк — его трафик идёт напрямую, остальное по-прежнему через
 * туннель. Список — все приложения со значком, как на рабочем столе, с
 * поиском по названию. Выбор применяется, когда лист закрывают: каждая
 * галочка по отдельности переподнимала бы туннель, а человек обычно
 * отмечает несколько подряд.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AppsSheet(state: AppState, onDismiss: () -> Unit) {
    val s = state.s
    val context = LocalContext.current
    val haptics = rememberHaptics()
    val chosen = remember { mutableStateListOf<String>().apply { addAll(state.excludedApps) } }
    var query by remember { mutableStateOf("") }
    var apps by remember { mutableStateOf<List<AppExclusions.Entry>?>(null) }
    // Значки декодируются один раз на лист: при прокрутке строки
    // пересоздаются, а PackageManager каждый раз рисовать их не должен.
    val icons = remember { HashMap<String, ImageBitmap?>() }
    val iconPx = with(LocalDensity.current) { 40.dp.roundToPx() }

    LaunchedEffect(Unit) {
        apps = withContext(Dispatchers.IO) { AppExclusions.launchable(context) }
    }

    val close = {
        state.changeExcludedApps(chosen.toSet())
        onDismiss()
    }

    SheetShell(title = s.appsTitle, subtitle = s.appsHint, onDismiss = close) {
        Column(Modifier.fillMaxWidth().imePadding()) {
            SearchField(value = query, onValueChange = { query = it }, placeholder = s.appsSearch)

            Spacer(Modifier.height(10.dp))

            val list = apps
            val shown = remember(list, query) {
                val needle = query.trim()
                list?.filter {
                    needle.isEmpty() ||
                        it.label.contains(needle, ignoreCase = true) ||
                        it.packageName.contains(needle, ignoreCase = true)
                }
            }

            when {
                list == null -> Quiet(s.appsLoading)
                shown.isNullOrEmpty() -> Quiet(s.appsEmpty)
                else -> LazyColumn(
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(max = 440.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    items(shown, key = { it.packageName }) { app ->
                        val icon by produceState(initialValue = icons[app.packageName], app.packageName) {
                            if (value == null && app.packageName !in icons) {
                                value = withContext(Dispatchers.IO) {
                                    AppExclusions.icon(context, app.packageName, iconPx)
                                }.also { icons[app.packageName] = it }
                            }
                        }
                        AppRow(
                            app = app,
                            icon = icon,
                            checked = app.packageName in chosen,
                            onToggle = {
                                haptics.selection()
                                if (app.packageName in chosen) chosen.remove(app.packageName)
                                else chosen.add(app.packageName)
                            },
                        )
                    }
                }
            }

            Spacer(Modifier.height(12.dp))

            PrimaryPill(text = s.applyDone, onClick = close)
        }
    }
}

@Composable
private fun Quiet(text: String) {
    Text(
        text = text,
        style = pro(14.sp, W.regular, Theme.textFaint),
        textAlign = TextAlign.Center,
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 28.dp),
    )
}

@Composable
private fun SearchField(value: String, onValueChange: (String) -> Unit, placeholder: String) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(46.dp)
            .clip(RoundedCornerShape(R2.tile))
            .background(Theme.tile.copy(alpha = if (Theme.isLight) 1f else 0.6f))
            .padding(horizontal = 14.dp),
        contentAlignment = Alignment.CenterStart,
    ) {
        BasicTextField(
            value = value,
            onValueChange = onValueChange,
            singleLine = true,
            keyboardOptions = KeyboardOptions(
                capitalization = KeyboardCapitalization.None,
                autoCorrectEnabled = false,
                imeAction = ImeAction.Search,
            ),
            textStyle = pro(15.sp, W.medium, Theme.text),
            cursorBrush = SolidColor(Theme.accent),
            modifier = Modifier.fillMaxWidth(),
            decorationBox = { inner ->
                Box(contentAlignment = Alignment.CenterStart) {
                    if (value.isEmpty()) {
                        Text(placeholder, style = pro(15.sp, W.regular, Theme.textFaint))
                    }
                    inner()
                }
            },
        )
    }
}

@Composable
private fun AppRow(
    app: AppExclusions.Entry,
    icon: ImageBitmap?,
    checked: Boolean,
    onToggle: () -> Unit,
) {
    val interaction = remember { MutableInteractionSource() }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .pressScale(interaction, 0.98f)
            .tvFocusHighlight(RoundedCornerShape(R2.tile))
            .clip(RoundedCornerShape(R2.tile))
            .background(
                if (checked) Theme.accentWash
                else Theme.tile.copy(alpha = if (Theme.isLight) 1f else 0.5f),
            )
            .noRippleClickable(haptic = false, onClick = onToggle)
            .padding(horizontal = 12.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(36.dp)
                .clip(RoundedCornerShape(10.dp))
                .background(Theme.tileDeep),
            contentAlignment = Alignment.Center,
        ) {
            if (icon != null) {
                Image(bitmap = icon, contentDescription = null, modifier = Modifier.size(36.dp))
            }
        }

        Spacer(Modifier.width(12.dp))

        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(1.dp)) {
            Text(
                text = app.label,
                style = pro(14.sp, W.semibold, Theme.text),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = app.packageName,
                style = pro(11.sp, W.regular, Theme.textFaint),
                maxLines = 1,
                overflow = TextOverflow.MiddleEllipsis,
            )
        }

        Spacer(Modifier.width(10.dp))

        // Кружок-галочка вместо тумблера: в длинном списке тумблеры
        // сливаются в частокол, а галочка читается по одной.
        Box(
            modifier = Modifier
                .size(24.dp)
                .clip(CircleShape)
                .background(if (checked) Theme.accent else Theme.tileDeep),
            contentAlignment = Alignment.Center,
        ) {
            if (checked) {
                Icon(
                    imageVector = Icons.check,
                    contentDescription = null,
                    tint = Color.White,
                    modifier = Modifier.size(13.dp),
                )
            }
        }
    }
}
