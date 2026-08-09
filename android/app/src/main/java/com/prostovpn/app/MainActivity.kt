package com.prostovpn.app

import android.app.Activity
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import androidx.lifecycle.viewmodel.compose.viewModel

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
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

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Theme.background)
    ) {
        AnimatedContent(
            targetState = state.isLoggedIn,
            label = "root",
            transitionSpec = {
                // Плавный «зум-переход» между входом и главным экраном, как в iOS
                if (targetState) {
                    (fadeIn(tween(400)) + scaleIn(
                        initialScale = 0.92f,
                        animationSpec = spring(dampingRatio = 0.85f, stiffness = 280f),
                    )).togetherWith(
                        fadeOut(tween(280)) + scaleOut(targetScale = 1.06f, animationSpec = tween(400))
                    )
                } else {
                    (fadeIn(tween(400)) + scaleIn(
                        initialScale = 1.06f,
                        animationSpec = tween(400),
                    )).togetherWith(
                        fadeOut(tween(280)) + scaleOut(targetScale = 0.94f, animationSpec = tween(400))
                    )
                }
            },
        ) { loggedIn ->
            if (loggedIn) {
                HomeScreen(state)
            } else {
                LoginScreen(state)
            }
        }
    }
}
