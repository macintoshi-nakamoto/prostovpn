package com.prostovpn.desktop

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@Composable
fun CurrentServerCard(
    state: AppState,
    backdrop: BackdropState,
    onOpen: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val interaction = remember { MutableInteractionSource() }
    Box(
        modifier = modifier
            .fillMaxWidth()
            .pressScale(interaction, 0.98f)
            .clip(RoundedCornerShape(26.dp))
            .liquidGlass(backdrop, cornerRadius = 26.dp)
            .pressHighlight(interaction, 0.05f, cornerRadius = 26.dp)
            .clickable(interactionSource = interaction, indication = null, onClick = onOpen)
            .padding(vertical = 13.dp, horizontal = 16.dp),
    ) {
        ServerRow(server = state.currentServer) {
            Icon(
                imageVector = Icons.chevronUp,
                contentDescription = null,
                tint = Theme.textTertiary,
                modifier = Modifier.size(17.dp),
            )
        }
    }
}

@Composable
fun ServerListSheet(
    state: AppState,
    visible: Boolean,
    backdrop: BackdropState,
    onDismiss: () -> Unit,
) {
    val haptics = rememberHaptics()
    val s = state.s

    GlassSheet(visible = visible, backdrop = backdrop, onDismiss = onDismiss) {
        Text(
            text = s.chooseServer,
            style = manrope(12.5.sp, W.bold, Theme.textMuted, letterSpacing = 0.6.sp),
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = Layout.screenPadding)
                .padding(top = 14.dp, bottom = 10.dp),
        )

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(max = 320.dp)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 14.dp)
                .padding(bottom = Layout.screenPadding),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            state.displayServers().forEachIndexed { index, server ->
                val isActive = index == state.selectedServerIndex
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .scaleClickable(0.98f) {
                            haptics.selection()

                            state.switchServer(index)
                            onDismiss()
                        }
                        .clip(RoundedCornerShape(18.dp))
                        .background(
                            if (isActive) Theme.accent.copy(alpha = 0.10f) else Color.Transparent
                        )
                        .padding(vertical = 11.dp, horizontal = 10.dp),
                ) {
                    ServerRow(server = server) {
                        if (isActive) {
                            Icon(
                                imageVector = Icons.check,
                                contentDescription = null,
                                tint = Theme.link,
                                modifier = Modifier.size(18.dp),
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun ServerRow(
    server: DisplayServer?,
    trailing: @Composable () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        FlagChip(flag = server?.flag ?: "🌐")

        Spacer(Modifier.width(14.dp))

        Column(verticalArrangement = Arrangement.spacedBy(1.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = server?.name ?: "—",
                    style = manrope(15.sp, W.bold, Theme.text),
                    maxLines = 1,
                )
                Spacer(Modifier.width(8.dp))
                ProtocolBadge()
            }

            Text(
                text = server?.sub ?: "",
                style = manrope(12.5.sp, W.medium, Theme.textMuted),
                maxLines = 1,
            )
        }

        Spacer(Modifier.weight(1f))

        trailing()
    }
}
