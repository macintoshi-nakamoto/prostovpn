package com.prostovpn.desktop

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.window.WindowDraggableArea
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Notification
import androidx.compose.ui.window.Tray
import androidx.compose.ui.window.Window
import androidx.compose.ui.window.WindowPosition
import androidx.compose.ui.window.application
import androidx.compose.ui.window.rememberTrayState
import androidx.compose.ui.window.rememberWindowState
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

private const val UPDATE_POLL_MS = 5 * 60 * 1000L

private val showRequests = java.util.concurrent.atomic.AtomicLong(0)
private val showRequestTicks = kotlinx.coroutines.flow.MutableStateFlow(0L)

fun main() {
    if (!SingleInstance.acquire(onShowRequest = {
            showRequestTicks.value = showRequests.incrementAndGet()
        })
    ) {
        return
    }

    runApp()
}

private fun runApp() = application {
    val scope = rememberCoroutineScope()

    val state = remember { AppState(scope) }

    val windowState = rememberWindowState(
        size = DpSize(400.dp, 660.dp),
        position = WindowPosition(Alignment.Center),
    )

    var windowVisible by remember { mutableStateOf(true) }
    val trayState = rememberTrayState()
    var trayHintShown by remember { mutableStateOf(false) }

    fun showWindow() {
        windowVisible = true
        windowState.isMinimized = false

        state.refreshPanelServers()
    }

    LaunchedEffect(Unit) {
        showRequestTicks.collect { tick ->
            if (tick > 0) showWindow()
        }
    }

    fun hideToTray() {
        windowVisible = false

        if (!trayHintShown) {
            trayHintShown = true
            runCatching {
                trayState.sendNotification(
                    Notification("Prosto VPN", state.s.trayHint, Notification.Type.Info)
                )
            }
        }
    }

    fun quit() {
        scope.launch {
            if (state.phase != Phase.OFF) {
                state.disconnect()
                withTimeoutOrNull(20_000) { snapshotFlow { state.phase }.first { it == Phase.OFF } }
            }
            exitApplication()
        }
    }

    val s = state.s
    val trayTooltip = when (state.phase) {
        Phase.ON -> "${state.s.connected} · ${state.currentServer?.name.orEmpty()}".trim(' ', '·')
        Phase.CONNECTING -> s.trayStatusConnecting
        Phase.DISCONNECTING -> s.trayStatusDisconnecting
        Phase.OFF -> "Prosto VPN"
    }

    Tray(
        state = trayState,
        icon = painterResource("trayicon.png"),
        tooltip = trayTooltip,
        onAction = ::showWindow,
        menu = {
            Item(s.trayOpen, onClick = ::showWindow)

            when (state.phase) {
                Phase.OFF -> Item(s.trayConnect, onClick = { state.toggleConnection() })
                Phase.ON -> Item(s.trayDisconnect, onClick = { state.toggleConnection() })
                Phase.CONNECTING -> Item(s.trayStatusConnecting, enabled = false, onClick = {})
                Phase.DISCONNECTING -> Item(s.trayStatusDisconnecting, enabled = false, onClick = {})
            }

            val servers = state.displayServers()
            if (state.isLoggedIn && servers.size > 1) {
                Separator()
                Menu(s.trayServer) {
                    servers.forEachIndexed { index, srv ->

                        CheckboxItem(
                            text = if (srv.sub.isNotEmpty()) "${srv.name} · ${srv.sub}" else srv.name,
                            checked = index == state.selectedServerIndex,
                            onCheckedChange = { state.switchServer(index) },
                        )
                    }
                }
            }

            Separator()
            Item(s.trayQuit, onClick = ::quit)
        },
    )

    Window(
        onCloseRequest = ::hideToTray,
        visible = windowVisible,
        state = windowState,
        title = "Prosto VPN",
        undecorated = true,
        transparent = true,
        resizable = false,
        icon = painterResource("appicon.png"),
    ) {
        AppRoot(
            state = state,
            onMinimize = { windowState.isMinimized = true },
            onClose = ::hideToTray,
            drag = { content -> WindowDraggableArea(content = content) },
        )
    }
}

enum class Page { MAIN, SETTINGS, SUPPORT }

@Composable
fun AppRoot(
    state: AppState,
    onMinimize: () -> Unit,
    onClose: () -> Unit,
    drag: @Composable (@Composable () -> Unit) -> Unit = { it() },
) {
    var page by remember { mutableStateOf(Page.MAIN) }
    var powerCenter by remember { mutableStateOf(Offset.Zero) }

    val backdrop = rememberBackdropState()

    LaunchedEffect(state.isLoggedIn) {
        if (state.isLoggedIn) {
            state.maybeAutoConnect()
        } else {
            page = Page.MAIN
        }
    }

    LaunchedEffect(Unit) {
        state.checkUpdate()
        while (true) {
            delay(UPDATE_POLL_MS)
            state.checkUpdate(silent = true)
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .clip(RoundedCornerShape(Layout.windowCorner))
            .border(1.dp, Color.White.copy(alpha = 0.08f), RoundedCornerShape(Layout.windowCorner)),
    ) {
        Box(
            Modifier
                .fillMaxSize()
                .backdropSource(backdrop)
        ) {
            Box(Modifier.fillMaxSize().background(Theme.background))
            BackgroundOrb(page)
            PowerGlow(state, powerCenter)
        }

        AnimatedContent(
            targetState = state.isLoggedIn,
            label = "root",
            transitionSpec = {
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
                HomeScreen(
                    state = state,
                    backdrop = backdrop,
                    page = page,
                    onPage = { page = it },
                    drag = drag,
                    onPowerCenter = { powerCenter = it },
                )
            } else {
                LoginScreen(state = state, drag = drag)
            }
        }

        GlassControlBar(
            backdrop = backdrop,
            showSettings = state.isLoggedIn && page == Page.MAIN,

            settingsBadge = state.updateAvailable,
            onSettings = { page = Page.SETTINGS },
            onMinimize = onMinimize,
            onClose = onClose,
            modifier = Modifier
                .align(Alignment.TopEnd)
                .padding(horizontal = Layout.screenPadding)
                .padding(top = Layout.topPadding),
        )
    }
}

@Composable
private fun BackgroundOrb(page: Page) {
    val toCenter by animateFloatAsState(
        targetValue = if (page == Page.MAIN) 1f else 0f,
        animationSpec = tween(450),
        label = "orb",
    )
    Canvas(Modifier.fillMaxSize()) {
        val x = androidx.compose.ui.util.lerp(size.width * 0.72f, size.width * 0.5f, toCenter)
        val y = androidx.compose.ui.util.lerp(40.dp.toPx(), 60.dp.toPx(), toCenter)
        val radius = androidx.compose.ui.util.lerp(260.dp.toPx(), 300.dp.toPx(), toCenter)
        val alpha = androidx.compose.ui.util.lerp(0.10f, 0.14f, toCenter)
        drawCircle(
            brush = Brush.radialGradient(
                colors = listOf(Theme.accent.copy(alpha = alpha), Color.Transparent),
                center = Offset(x, y),
                radius = radius,
            ),
            radius = radius,
            center = Offset(x, y),
        )
    }
}
