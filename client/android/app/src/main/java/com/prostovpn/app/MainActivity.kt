package com.prostovpn.app

import android.Manifest
import android.app.Activity
import android.content.pm.ActivityInfo
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.LocalIndication
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.core.content.ContextCompat
import androidx.core.view.WindowCompat
import androidx.lifecycle.viewmodel.compose.viewModel

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        if (!isTv()) {
            requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
        }
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
        )
        setContent {
            RootView()
        }
    }
}

@Composable
fun RootView(state: AppState = viewModel()) {
    val vpnPermissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        state.onVpnPermissionResult(result.resultCode == Activity.RESULT_OK)
    }

    LaunchedEffect(state.pendingPermissionIntent) {
        state.pendingPermissionIntent?.let { vpnPermissionLauncher.launch(it) }
    }

    LaunchedEffect(state.isLoggedIn) {
        if (state.isLoggedIn) state.maybeAutoConnect()
    }

    // Возврат из системных настроек «неизвестных источников»: продолжить
    // установку один раз — с какого бы экрана она ни началась.
    androidx.lifecycle.compose.LifecycleResumeEffect(Unit) {
        state.updates.resumeAfterPermission()
        onPauseOrDispose { }
    }

    val context = LocalContext.current
    val view = LocalView.current

    // Тема живёт в одном месте: экраны читают Theme.palette и перерисовываются
    // разом. Заодно переставляем цвет значков системных панелей — на светлой
    // канве белые часы не видно.
    LaunchedEffect(state.themeMode) {
        Theme.palette = if (state.themeMode == ThemeMode.LIGHT) LightPalette else DarkPalette
        val window = (view.context as? Activity)?.window ?: return@LaunchedEffect
        WindowCompat.getInsetsController(window, view).apply {
            isAppearanceLightStatusBars = Theme.isLight
            isAppearanceLightNavigationBars = Theme.isLight
        }
    }

    val notificationPermission = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { }

    LaunchedEffect(state.isLoggedIn) {
        if (!state.isLoggedIn) return@LaunchedEffect
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return@LaunchedEffect
        val granted = ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.POST_NOTIFICATIONS,
        ) == PackageManager.PERMISSION_GRANTED
        if (!granted) notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
    }

    CompositionLocalProvider(LocalIndication provides FlashIndication) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(Theme.canvas)
        ) {
            AnimatedContent(
                targetState = state.isLoggedIn,
                label = "root",
                transitionSpec = {
                    if (targetState) {
                        (fadeIn(tween(320)) + scaleIn(initialScale = 0.96f, animationSpec = tween(320)))
                            .togetherWith(
                                fadeOut(tween(220)) + scaleOut(targetScale = 1.04f, animationSpec = tween(320))
                            )
                    } else {
                        (fadeIn(tween(320)) + scaleIn(initialScale = 1.04f, animationSpec = tween(320)))
                            .togetherWith(
                                fadeOut(tween(220)) + scaleOut(targetScale = 0.96f, animationSpec = tween(320))
                            )
                    }
                },
            ) { loggedIn ->
                if (loggedIn) {
                    AppShell(state)
                } else {
                    LoginScreen(state)
                }
            }
        }
    }
}
