package com.alisavpn.app

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@Composable
fun ServerSheet(state: AppState) {
    var expanded by remember { mutableStateOf(false) }
    val interactionSource = remember { MutableInteractionSource() }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(topStart = 28.dp, topEnd = 28.dp))
            .background(Color.White.copy(alpha = 0.04f))
            .clickable(interactionSource = interactionSource, indication = null) {
                expanded = !expanded
            }
            .padding(horizontal = 20.dp)
            .navigationBarsPadding(),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(
            modifier = Modifier
                .padding(top = 10.dp, bottom = 8.dp)
                .size(width = 38.dp, height = 4.dp)
                .clip(RoundedCornerShape(2.dp))
                .background(Color.White.copy(alpha = 0.16f))
        )

        ServerRow(
            state = state,
            trailing = {
                Icon(
                    imageVector = if (expanded) Icons.chevronDown else Icons.chevronUp,
                    contentDescription = null,
                    tint = Theme.text.copy(alpha = 0.35f),
                    modifier = Modifier.size(18.dp),
                )
            },
        )

        AnimatedVisibility(
            visible = expanded,
            enter = expandVertically() + fadeIn(),
            exit = shrinkVertically() + fadeOut(),
        ) {
            Column {
                Text(
                    text = strings(state.lang).selectServer,
                    color = Theme.textMuted,
                    fontSize = 13.sp,
                    fontWeight = FontWeight.Bold,
                    letterSpacing = 0.5.sp,
                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 8.dp),
                )

                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(16.dp))
                        .background(Theme.accent.copy(alpha = 0.07f))
                        .padding(12.dp)
                ) {
                    ServerRow(
                        state = state,
                        trailing = {
                            Icon(
                                imageVector = Icons.check,
                                contentDescription = null,
                                tint = Theme.vibrant,
                                modifier = Modifier.size(20.dp),
                            )
                        },
                    )
                }

                Spacer(Modifier.height(8.dp))
            }
        }

        Spacer(Modifier.height(if (expanded) 20.dp else 12.dp))
    }
}

@Composable
private fun ServerRow(
    state: AppState,
    trailing: @Composable () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(40.dp)
                .clip(RoundedCornerShape(12.dp))
                .background(Theme.accentTint),
            contentAlignment = Alignment.Center,
        ) {
            val code = state.server?.countryCode
            if (!code.isNullOrEmpty()) {
                Text(text = flagEmoji(code), fontSize = 22.sp)
            } else {
                Icon(
                    imageVector = Icons.globe,
                    contentDescription = null,
                    tint = Theme.accentSoft,
                    modifier = Modifier.size(20.dp),
                )
            }
        }

        Spacer(Modifier.width(14.dp))

        Column(verticalArrangement = Arrangement.spacedBy(1.dp)) {
            Text(
                text = state.server?.countryFor(state.lang) ?: strings(state.lang).server,
                color = Theme.text,
                fontSize = 15.sp,
                fontWeight = FontWeight.Bold,
            )

            val city = state.server?.cityFor(state.lang)
            if (!city.isNullOrEmpty()) {
                Text(
                    text = city,
                    color = Theme.textMuted,
                    fontSize = 12.5.sp,
                    fontWeight = FontWeight.Medium,
                )
            }
        }

        Spacer(Modifier.weight(1f))

        trailing()
    }
}
