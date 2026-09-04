package com.prostovpn.app

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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * Выбор страны.
 *
 * Отдельная вкладка, а не лист: в приложении это второе по частоте действие
 * после подключения, и прятать его за строкой на главной незачем.
 */
@Composable
fun CountriesPage(state: AppState, onDone: () -> Unit) {
    val s = state.s
    val servers = state.displayServers()

    LaunchedEffect(Unit) { state.refreshPings() }

    Box(Modifier.fillMaxSize()) {
        Box(Modifier.fillMaxSize().background(Theme.canvas))
        if (Theme.isLight) LightSheen()
        CanvasGlow(
            color = if (Theme.isLight) {
                Color(0xFFFA4C16).copy(alpha = 0.10f)
            } else {
                Color.White.copy(alpha = 0.09f)
            },
        )

        Column(
            modifier = Modifier
                .fillMaxSize()
                .statusBarsPadding()
                .padding(horizontal = 16.dp),
        ) {
            Column(
                modifier = Modifier.padding(top = 18.dp, bottom = 18.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                Text(
                    text = s.countryTitle,
                    style = pro(24.sp, W.bold, Theme.text, tracking = em(24.sp, -0.025f)),
                )
                Text(text = s.countrySub, style = pro(14.sp, W.regular, Theme.textMuted))
            }

            Column(
                modifier = Modifier
                    .weight(1f)
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                BestServerCard(state = state, modifier = Modifier.fadeUp())

                RowsCard(modifier = Modifier.fadeUp(60)) {
                    servers.forEachIndexed { index, server ->
                        if (index > 0) HairLine(inset = 63.dp)
                        CountryRow(
                            state = state,
                            server = server,
                            active = !state.autoServer && index == state.selectedServerIndex,
                            onClick = { state.chooseServer(index) },
                        )
                    }
                    if (servers.isEmpty()) {
                        Text(
                            text = s.errNoServers,
                            style = pro(14.sp, W.regular, Theme.textMuted, lineHeight = 20.sp),
                            modifier = Modifier.padding(18.dp),
                        )
                    }
                }

                Spacer(Modifier.height(8.dp))
            }

            PrimaryPill(
                text = if (state.phase == Phase.ON) s.applyDone else s.connect,
                modifier = Modifier.padding(top = 12.dp),
                onClick = {
                    if (state.phase != Phase.ON) state.toggleConnection()
                    onDone()
                },
            )

            Spacer(Modifier.navigationBarsPadding().height(86.dp))
        }
    }
}

@Composable
private fun BestServerCard(state: AppState, modifier: Modifier = Modifier) {
    val s = state.s
    val active = state.autoServer
    Row(
        modifier = modifier
            .fillMaxWidth()
            .height(66.dp)
            .clip(androidx.compose.foundation.shape.RoundedCornerShape(R2.card))
            .background(Theme.accentWash)
            .flashClickable { state.chooseAuto() }
            .padding(horizontal = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(38.dp)
                .clip(CircleShape)
                .background(if (Theme.isLight) Color.White else Color.White.copy(alpha = 0.10f)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                imageVector = Icons.zap,
                contentDescription = null,
                tint = Theme.accent,
                modifier = Modifier.size(18.dp),
            )
        }
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(s.bestServer, style = pro(15.sp, W.semibold, Theme.text))
            Text(s.bestServerSub, style = pro(12.sp, W.regular, Theme.textMuted))
        }
        if (active) {
            Box(
                modifier = Modifier
                    .size(22.dp)
                    .clip(CircleShape)
                    .background(Theme.accent),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    imageVector = Icons.check,
                    contentDescription = null,
                    tint = Color.White,
                    modifier = Modifier.size(12.dp),
                )
            }
        }
    }
}

@Composable
private fun CountryRow(
    state: AppState,
    server: DisplayServer,
    active: Boolean,
    onClick: () -> Unit,
) {
    val s = state.s
    val ping = state.pingFor(server)
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(62.dp)
            .flashClickable(onClick = onClick)
            .padding(horizontal = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        CountryFlag(code = server.code, size = 34.dp)
        Spacer(Modifier.width(15.dp))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(1.dp)) {
            Text(
                text = server.name.ifEmpty { server.host.orEmpty() },
                style = pro(15.sp, W.semibold, Theme.text),
                maxLines = 1,
            )
            if (server.sub.isNotEmpty()) {
                Text(text = server.sub, style = pro(12.sp, W.regular, Theme.textFaint), maxLines = 1)
            }
        }
        if (ping != null) {
            Text(
                text = "$ping ${s.ms}",
                style = pro(13.sp, W.semibold, pingColor(ping), tabular = true),
            )
        }
        if (active) {
            Spacer(Modifier.width(10.dp))
            Box(
                modifier = Modifier
                    .size(8.dp)
                    .clip(CircleShape)
                    .background(Theme.accent),
            )
        }
    }
}

@Composable
private fun pingColor(ping: Int): Color = when {
    ping < 40 -> Theme.success
    ping > 60 -> Theme.warning
    else -> Theme.textMuted
}
