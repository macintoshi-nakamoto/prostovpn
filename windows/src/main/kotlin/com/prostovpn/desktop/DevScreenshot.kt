package com.prostovpn.desktop

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.ImageComposeScene
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.compose.ui.use
import java.io.File

/**
 * Рендер экранов приложения в PNG без дисплея — проверка вёрстки и liquid glass.
 * Запуск: ./gradlew screenshots
 */
fun main() {
    val out = File("screenshots").apply { mkdirs() }

    fun snap(name: String, content: @Composable () -> Unit) {
        ImageComposeScene(width = 800, height = 1280, density = Density(2f), content = content).use { scene ->
            // прогоняем ~3 секунды кадров по 16.6 мс, как при реальных 60 fps,
            // чтобы все входные анимации (fadeUp и т.п.) дошли до конца
            var image = scene.render(0L)
            for (frame in 1..180) {
                image = scene.render(frame * 16_666_667L)
            }
            File(out, "$name.png").writeBytes(image.encodeToData()!!.bytes)
        }
        println("saved $name.png")
    }

    snap("01-login") {
        Frame { state -> LoginScreen(state) }
    }

    snap("02-home-off") {
        Frame { state ->
            state.previewAs(guest = true, previewPhase = Phase.OFF)
            HomeScreen(state)
        }
    }

    snap("03-home-on") {
        Frame { state ->
            state.previewAs(guest = true, previewPhase = Phase.ON)
            HomeScreen(state)
        }
    }

    snap("04-settings") {
        Frame { state ->
            state.previewAs(guest = true, previewPhase = Phase.OFF)
            SettingsScreen(state, onBack = {})
        }
    }

    snap("05-support") {
        Frame { state ->
            state.previewAs(guest = true, previewPhase = Phase.OFF)
            SupportScreen(state, onBack = {})
        }
    }
}

@Composable
private fun Frame(content: @Composable (AppState) -> Unit) {
    val scope = rememberCoroutineScope()
    val state = remember { AppState(scope) }
    Box(
        modifier = Modifier
            .fillMaxSize()
            .clip(RoundedCornerShape(26.dp))
            .background(Theme.background)
            .border(1.dp, Color.White.copy(alpha = 0.08f), RoundedCornerShape(26.dp)),
    ) {
        content(state)
    }
}
