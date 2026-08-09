package com.prostovpn.app

import androidx.compose.foundation.background
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch

/** Нижняя стеклянная карточка текущего сервера — iOS CurrentServerCard. */
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

/** Шторка выбора сервера — iOS ServerListSheet. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ServerListSheet(state: AppState, onDismiss: () -> Unit) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val scope = rememberCoroutineScope()
    val haptics = rememberHaptics()
    val s = state.s

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState,
        containerColor = Color.Transparent,
        dragHandle = null,
        shape = RoundedCornerShape(topStart = 28.dp, topEnd = 28.dp),
        scrimColor = Color.Black.copy(alpha = 0.45f),
        contentWindowInsets = { WindowInsets(0.dp) },
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .background(Theme.sheetGradient)
                .navigationBarsPadding(),
        ) {
            // Ручка шторки
            Box(
                modifier = Modifier
                    .padding(top = 10.dp)
                    .size(width = 38.dp, height = 5.dp)
                    .clip(RoundedCornerShape(2.5.dp))
                    .background(Color.White.copy(alpha = 0.18f))
                    .align(Alignment.CenterHorizontally),
            )

            Text(
                text = s.chooseServer,
                style = manrope(13.sp, W.bold, Theme.textMuted, letterSpacing = 0.5.sp),
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 28.dp)
                    .padding(top = 20.dp, bottom = 8.dp),
            )

            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = 20.dp)
                    .padding(bottom = 16.dp),
                verticalArrangement = Arrangement.spacedBy(2.dp),
            ) {
                state.displayServers().forEachIndexed { index, server ->
                    val isActive = index == state.selectedServerIndex
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .scaleClickable(0.98f) {
                                haptics.selection()
                                state.selectServer(index)
                                scope.launch { sheetState.hide() }.invokeOnCompletion { onDismiss() }
                            }
                            .clip(RoundedCornerShape(16.dp))
                            .background(if (isActive) Theme.accent.copy(alpha = 0.07f) else Color.Transparent)
                            .padding(vertical = 12.dp, horizontal = 8.dp),
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
}

/** Строка сервера: флаг, название + бейдж AWG2, подзаголовок — iOS ServerRow. */
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
