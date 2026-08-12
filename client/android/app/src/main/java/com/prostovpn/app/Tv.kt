package com.prostovpn.app

import android.app.UiModeManager
import android.content.Context
import android.content.pm.PackageManager
import android.content.res.Configuration
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalContext

/*
Определение телевизора.

UiModeManager — основной сигнал: Android TV запускает приложения в режиме
UI_MODE_TYPE_TELEVISION, это покрывает и «настоящие» ТВ, и приставки.
FEATURE_LEANBACK — страховка: на дешёвых панелях (наш ориентир —
Hi HX-32H01FB, Android 13, leanback-only) uiMode иногда прошит криво,
а leanback-фича в system features есть всегда, иначе лаунчер бы их
вообще не показывал.
*/
fun Context.isTv(): Boolean {
    val uiModeManager = getSystemService(Context.UI_MODE_SERVICE) as? UiModeManager
    if (uiModeManager?.currentModeType == Configuration.UI_MODE_TYPE_TELEVISION) return true
    return packageManager.hasSystemFeature(PackageManager.FEATURE_LEANBACK)
}

/*
Composable-обёртка для экранов: ответ не меняется за жизнь процесса
(с ТВ на телефон приложение не переезжает), поэтому считаем один раз
и не дёргаем системные сервисы на каждую рекомпозицию.
*/
@Composable
fun rememberIsTv(): Boolean {
    val context = LocalContext.current
    return remember(context) { context.isTv() }
}
