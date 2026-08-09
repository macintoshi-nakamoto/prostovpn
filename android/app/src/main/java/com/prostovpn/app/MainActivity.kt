package com.prostovpn.app

import android.app.Activity
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.Crossfade
import androidx.compose.animation.core.tween
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
        Crossfade(
            targetState = state.isLoggedIn,
            animationSpec = tween(450),
            label = "root",
        ) { loggedIn ->
            if (loggedIn) {
                HomeScreen(state)
            } else {
                LoginScreen(state)
            }
        }
    }
}
