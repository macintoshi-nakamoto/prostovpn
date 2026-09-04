package com.prostovpn.app

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedContentTransitionScope
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

enum class Tab { CONNECT, MORE }

private sealed interface Route {
    data object Tabs : Route
    data object Settings : Route
    data object Support : Route
}

/**
 * Оболочка приложения: две вкладки и два экрана, которые выезжают поверх.
 *
 * У приложения одна работа — подключить, поэтому в панели только «подключение»
 * и «ещё». Выбор страны живёт в листе снизу: его открывают редко, а место в
 * панели стоит дорого. Тарифы и друзья остаются в кабинете.
 */
@Composable
fun AppShell(state: AppState) {
    var route by remember { mutableStateOf<Route>(Route.Tabs) }
    var tab by rememberSaveable { mutableStateOf(Tab.CONNECT) }

    BackHandler(enabled = route != Route.Tabs || tab != Tab.CONNECT) {
        if (route != Route.Tabs) route = Route.Tabs else tab = Tab.CONNECT
    }

    Box(Modifier.fillMaxSize()) {
        AnimatedContent(
            targetState = route,
            label = "route",
            transitionSpec = {
                if (targetState != Route.Tabs) {
                    (slideIntoContainer(
                        AnimatedContentTransitionScope.SlideDirection.Start,
                        tween(240, easing = Theme.easeStandard),
                        initialOffset = { it / 3 },
                    ) + fadeIn(tween(240))).togetherWith(
                        slideOutOfContainer(
                            AnimatedContentTransitionScope.SlideDirection.Start,
                            tween(180, easing = Theme.easeStandard),
                            targetOffset = { it / 8 },
                        ) + fadeOut(tween(180))
                    )
                } else {
                    (slideIntoContainer(
                        AnimatedContentTransitionScope.SlideDirection.End,
                        tween(240, easing = Theme.easeStandard),
                        initialOffset = { it / 8 },
                    ) + fadeIn(tween(240))).togetherWith(
                        slideOutOfContainer(
                            AnimatedContentTransitionScope.SlideDirection.End,
                            tween(180, easing = Theme.easeStandard),
                            targetOffset = { it / 3 },
                        ) + fadeOut(tween(180))
                    )
                }
            },
        ) { current ->
            when (current) {
                Route.Settings -> SettingsScreen(state, onBack = { route = Route.Tabs })
                Route.Support -> SupportScreen(state, onBack = { route = Route.Tabs })
                Route.Tabs -> TabsHost(
                    state = state,
                    tab = tab,
                    onTab = { tab = it },
                    onSettings = { route = Route.Settings },
                    onSupport = { route = Route.Support },
                )
            }
        }
    }

}

@Composable
private fun TabsHost(
    state: AppState,
    tab: Tab,
    onTab: (Tab) -> Unit,
    onSettings: () -> Unit,
    onSupport: () -> Unit,
) {
    val backdrop = rememberBackdropState()

    Box(Modifier.fillMaxSize()) {
        Box(
            Modifier
                .fillMaxSize()
                .backdropSource(backdrop)
        ) {
        AnimatedContent(
            targetState = tab,
            label = "tab",
            transitionSpec = { fadeIn(tween(220)).togetherWith(fadeOut(tween(140))) },
        ) { current ->
            when (current) {
                Tab.CONNECT -> MainPage(
                    state = state,
                    onOpenSettings = onSettings,
                    onOpenSupport = onSupport,
                )
                Tab.MORE -> MorePage(
                    state = state,
                    onOpenSettings = onSettings,
                    onOpenSupport = onSupport,
                )
            }
        }
        }

        BottomNav(
            current = tab,
            strings = state.s,
            backdrop = backdrop,
            onSelect = onTab,
            modifier = Modifier.align(Alignment.BottomCenter),
        )
    }
}

private data class NavItem(val tab: Tab, val icon: ImageVector, val label: String)

@Composable
fun BottomNav(
    current: Tab,
    strings: Strings,
    backdrop: BackdropState,
    onSelect: (Tab) -> Unit,
    modifier: Modifier = Modifier,
) {
    val s = strings
    val haptics = rememberHaptics()
    val items = listOf(
        NavItem(Tab.CONNECT, Icons.power, s.tabConnect),
        NavItem(Tab.MORE, Icons.more, s.tabMore),
    )
    val index = items.indexOfFirst { it.tab == current }.coerceAtLeast(0)
    val itemWidth = 116.dp
    val pillOffset by animateDpAsState(
        targetValue = itemWidth * index,
        animationSpec = tween(240, easing = Theme.easeStandard),
        label = "navPill",
    )

    Box(modifier = modifier.fillMaxWidth(), contentAlignment = Alignment.BottomCenter) {
        // Растяжка канвы отделяет содержимое от панели без единой линии.
        Box(
            Modifier
                .fillMaxWidth()
                .height(104.dp)
                .background(
                    Brush.verticalGradient(
                        0f to Color.Transparent,
                        1f to Theme.canvasBottom,
                    )
                )
                .align(Alignment.BottomCenter)
        )

        Row(
            modifier = Modifier
                .navigationBarsPadding()
                .padding(bottom = 12.dp)
                .softShadow(Theme.shadowPlate, 24.dp, 30.dp, yOffset = 10.dp)
                .clip(CircleShape)
                .liquidGlass(
                    backdrop = backdrop,
                    cornerRadius = 30.dp,
                    blurRadius = 22.dp,
                    saturation = 1.35f,
                    refractionHeight = 10.dp,
                    refractionAmount = 8.dp,
                    tintAlpha = if (Theme.isLight) 0.55f else 0.06f,
                    highlightAlpha = if (Theme.isLight) 0.6f else 0.12f,
                )
                .padding(5.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box {
                Box(
                    Modifier
                        .offset { IntOffset(pillOffset.roundToPx(), 0) }
                        .size(width = itemWidth, height = 52.dp)
                        .clip(CircleShape)
                        .background(Theme.accentWash)
                )
                Row {
                    items.forEach { item ->
                        NavCell(
                            item = item,
                            active = item.tab == current,
                            width = itemWidth,
                            onClick = {
                                if (item.tab != current) haptics.selection()
                                onSelect(item.tab)
                            },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun NavCell(item: NavItem, active: Boolean, width: Dp, onClick: () -> Unit) {
    val tint by animateColorAsState(
        targetValue = if (active) Theme.accent else Theme.textFaint,
        animationSpec = tween(240),
        label = "navTint",
    )
    val bump by animateFloatAsState(
        targetValue = if (active) 1.08f else 1f,
        animationSpec = tween(180, easing = Theme.easeOut),
        label = "navBump",
    )
    Column(
        modifier = Modifier
            .width(width)
            .height(52.dp)
            .tvFocusHighlight(CircleShape)
            .noRippleClickable(haptic = false, onClick = onClick),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Icon(
            imageVector = item.icon,
            contentDescription = item.label,
            tint = tint,
            modifier = Modifier
                .size(21.dp)
                .graphicsLayer {
                    scaleX = bump
                    scaleY = bump
                },
        )
        Spacer(Modifier.height(3.dp))
        Text(item.label, style = pro(11.sp, W.semibold, tint))
    }
}
