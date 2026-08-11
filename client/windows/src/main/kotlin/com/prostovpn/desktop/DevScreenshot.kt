package com.prostovpn.desktop

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.ImageComposeScene
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
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

    fun snap(name: String, frames: Int = 180, content: @Composable () -> Unit) {
        ImageComposeScene(width = 800, height = 1320, density = Density(2f), content = content).use { scene ->
            // прогоняем кадры по 16.6 мс, как при реальных 60 fps,
            // чтобы все входные анимации дошли до конца
            var image = scene.render(0L)
            for (frame in 1..frames) {
                image = scene.render(frame * 16_666_667L)
            }
            File(out, "$name.png").writeBytes(image.encodeToData()!!.bytes)
        }
        println("saved $name.png")
    }

    snap("01-login") { Shell(loggedIn = false) }
    snap("02-home-off") { Shell(phase = Phase.OFF) }
    snap("03-home-on") { Shell(phase = Phase.ON) }
    snap("04-settings") { Shell(page = Page.SETTINGS) }
    snap("05-support") { Shell(page = Page.SUPPORT) }
    snap("06-servers-sheet") { Shell(phase = Phase.ON, openServers = true) }
    snap("07-files-sheet") { Shell(page = Page.SETTINGS, openFiles = true) }
}

/**
 * Полное окно приложения с общим фоном и капсулой управления —
 * ровно то, что видит пользователь.
 */
@Composable
private fun Shell(
    loggedIn: Boolean = true,
    page: Page = Page.MAIN,
    phase: Phase = Phase.OFF,
    openServers: Boolean = false,
    openFiles: Boolean = false,
) {
    val scope = rememberCoroutineScope()
    val state = remember { AppState(scope) }
    state.previewAs(loggedIn = loggedIn, previewPhase = phase)
    if (openFiles) state.previewOpenFileSheet()
    if (openServers) state.previewOpenServerSheet()

    val backdrop = rememberBackdropState()
    var powerCenter by remember { mutableStateOf(Offset.Zero) }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .clip(RoundedCornerShape(Layout.windowCorner))
            .border(1.dp, Color.White.copy(alpha = 0.08f), RoundedCornerShape(Layout.windowCorner)),
    ) {
        Box(Modifier.fillMaxSize().backdropSource(backdrop)) {
            Box(Modifier.fillMaxSize().background(Theme.background))
            PreviewOrb(page)
            PowerGlow(state, powerCenter)
        }

        if (loggedIn) {
            HomeScreen(
                state = state,
                backdrop = backdrop,
                page = page,
                onPage = {},
                drag = { it() },
                onPowerCenter = { powerCenter = it },
            )
        } else {
            LoginScreen(state = state, drag = { it() })
        }

        GlassControlBar(
            backdrop = backdrop,
            showSettings = loggedIn && page == Page.MAIN,
            onSettings = {},
            onMinimize = {},
            onClose = {},
            modifier = Modifier
                .align(Alignment.TopEnd)
                .padding(horizontal = Layout.screenPadding)
                .padding(top = Layout.topPadding),
        )
    }
}

@Composable
private fun PreviewOrb(page: Page) {
    androidx.compose.foundation.Canvas(Modifier.fillMaxSize()) {
        val center = if (page == Page.MAIN) {
            Offset(size.width * 0.5f, 60.dp.toPx())
        } else {
            Offset(size.width * 0.72f, 40.dp.toPx())
        }
        val radius = 280.dp.toPx()
        drawCircle(
            brush = androidx.compose.ui.graphics.Brush.radialGradient(
                colors = listOf(Theme.accent.copy(alpha = 0.13f), Color.Transparent),
                center = center,
                radius = radius,
            ),
            radius = radius,
            center = center,
        )
    }
}
