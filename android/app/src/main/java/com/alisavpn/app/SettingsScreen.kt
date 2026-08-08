package com.alisavpn.app

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@Composable
fun SettingsScreen(state: AppState, onBack: () -> Unit) {
    var killSwitch by rememberSaveable { mutableStateOf(true) }
    var logging by rememberSaveable { mutableStateOf(false) }
    var showLogoutConfirm by remember { mutableStateOf(false) }

    val s = strings(state.lang)
    val context = androidx.compose.ui.platform.LocalContext.current

    val filePicker = rememberLauncherForActivityResult(
        androidx.activity.result.contract.ActivityResultContracts.GetContent()
    ) { uri ->
        if (uri != null) {
            val json = runCatching {
                context.contentResolver.openInputStream(uri)?.bufferedReader()?.use { it.readText() }
            }.getOrNull()
            val name = queryFileName(context, uri) ?: "list.json"
            val ok = json != null && state.setCustomSplitList(json, name)
            android.widget.Toast.makeText(
                context,
                if (ok) "${s.listLoaded}: $name" else s.listLoadFailed,
                android.widget.Toast.LENGTH_SHORT,
            ).show()
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 24.dp)
            .navigationBarsPadding(),
    ) {
        BackRow(s.back, onBack)

        Text(
            text = s.settings,
            color = Theme.text,
            fontSize = 30.sp,
            fontWeight = FontWeight.ExtraBold,
            modifier = Modifier.padding(top = 10.dp, bottom = 22.dp),
        )

        Card {
            ToggleRow(
                s.splitTunnel,
                s.splitTunnelSub,
                state.splitTunnelEnabled,
            ) { state.changeSplitTunnel(it) }
            CardDivider()
            NavRow(
                title = s.exclusionList,
                subtitle = state.customSplitName ?: s.splitDefaultList,
                enabled = state.splitTunnelEnabled,
            ) {
                filePicker.launch("application/json")
            }
            if (state.hasCustomSplitList) {
                CardDivider()
                NavRow(
                    title = s.resetList,
                    subtitle = s.resetListSub,
                    enabled = state.splitTunnelEnabled,
                ) {
                    state.resetSplitList()
                }
            }
        }

        Spacer(Modifier.height(14.dp))

        Card {
            ToggleRow(s.autoConnect, s.autoConnectSub, state.autoConnect) { state.changeAutoConnect(it) }
            CardDivider()
            ToggleRow(s.killSwitch, s.killSwitchSub, killSwitch) { killSwitch = it }
            CardDivider()
            ToggleRow(s.logging, s.loggingSub, logging) { logging = it }
        }

        Spacer(Modifier.height(14.dp))

        Card {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(13.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Text(s.language, color = Theme.text, fontSize = 15.sp, fontWeight = FontWeight.Bold)
                    Text(
                        text = s.languageValue,
                        color = Theme.textMuted,
                        fontSize = 12.5.sp,
                        fontWeight = FontWeight.Medium,
                    )
                }

                Row(
                    modifier = Modifier
                        .clip(RoundedCornerShape(11.dp))
                        .background(Color.White.copy(alpha = 0.08f))
                        .padding(3.dp),
                ) {
                    LangButton("RU", state.lang == "ru") { state.changeLang("ru") }
                    LangButton("EN", state.lang == "en") { state.changeLang("en") }
                }
            }
        }

        Spacer(Modifier.height(24.dp))
        Spacer(Modifier.weight(1f))

        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(52.dp)
                .clip(RoundedCornerShape(20.dp))
                .background(Theme.accent.copy(alpha = 0.08f))
                .clickable { showLogoutConfirm = true },
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = s.logout,
                color = Theme.vibrant,
                fontSize = 15.sp,
                fontWeight = FontWeight.Bold,
            )
        }

        Spacer(Modifier.height(16.dp))
    }

    if (showLogoutConfirm) {
        AlertDialog(
            onDismissRequest = { showLogoutConfirm = false },
            containerColor = Theme.bgTop,
            titleContentColor = Theme.text,
            textContentColor = Theme.textMuted,
            title = { Text(s.logoutConfirmTitle) },
            text = { Text(s.logoutConfirmText) },
            confirmButton = {
                TextButton(onClick = {
                    showLogoutConfirm = false
                    state.logout()
                }) {
                    Text(s.yes, color = Theme.vibrant, fontWeight = FontWeight.Bold)
                }
            },
            dismissButton = {
                TextButton(onClick = { showLogoutConfirm = false }) {
                    Text(s.no, color = Theme.text)
                }
            },
        )
    }
}

@Composable
fun BackRow(label: String, onBack: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Row(
            modifier = Modifier
                .clip(CircleShape)
                .clickable { onBack() }
                .padding(vertical = 6.dp, horizontal = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = Icons.chevronRight,
                contentDescription = null,
                tint = Theme.accentSoft,
                modifier = Modifier
                    .size(22.dp)
                    .rotate(180f),
            )
            Text(
                text = label,
                color = Theme.accentSoft,
                fontSize = 16.sp,
                fontWeight = FontWeight.SemiBold,
            )
        }
    }
}

@Composable
fun Card(content: @Composable () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(20.dp))
            .background(Theme.card)
            .padding(6.dp),
    ) {
        content()
    }
}

@Composable
fun NavRow(
    title: String,
    subtitle: String,
    enabled: Boolean = true,
    onClick: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .then(if (enabled) Modifier.clickable { onClick() } else Modifier)
            .padding(13.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(
                title,
                color = if (enabled) Theme.text else Theme.text.copy(alpha = 0.4f),
                fontSize = 15.sp,
                fontWeight = FontWeight.Bold,
            )
            Text(
                subtitle,
                color = Theme.textMuted,
                fontSize = 12.5.sp,
                fontWeight = FontWeight.Medium,
            )
        }
        Icon(
            imageVector = Icons.chevronRight,
            contentDescription = null,
            tint = Theme.text.copy(alpha = 0.35f),
            modifier = Modifier.size(18.dp),
        )
    }
}

fun queryFileName(context: Context, uri: Uri): String? = runCatching {
    context.contentResolver.query(uri, null, null, null, null)?.use { cursor ->
        val index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
        if (index >= 0 && cursor.moveToFirst()) cursor.getString(index) else null
    }
}.getOrNull()

@Composable
fun CardDivider() {
    Box(
        Modifier
            .fillMaxWidth()
            .padding(horizontal = 10.dp)
            .height(1.dp)
            .background(Theme.divider)
    )
}

@Composable
private fun ToggleRow(
    title: String,
    subtitle: String,
    checked: Boolean,
    onChange: (Boolean) -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(13.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(title, color = Theme.text, fontSize = 15.sp, fontWeight = FontWeight.Bold)
            Text(subtitle, color = Theme.textMuted, fontSize = 12.5.sp, fontWeight = FontWeight.Medium)
        }

        Switch(
            checked = checked,
            onCheckedChange = onChange,
            colors = SwitchDefaults.colors(
                checkedThumbColor = Color.White,
                checkedTrackColor = Theme.accent,
                checkedBorderColor = Color.Transparent,
                uncheckedThumbColor = Color.White,
                uncheckedTrackColor = Color.White.copy(alpha = 0.12f),
                uncheckedBorderColor = Color.Transparent,
            ),
        )
    }
}

@Composable
private fun LangButton(title: String, active: Boolean, onClick: () -> Unit) {
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(9.dp))
            .background(if (active) Theme.accent else Color.Transparent)
            .clickable { onClick() }
            .padding(horizontal = 14.dp, vertical = 6.dp),
    ) {
        Text(
            text = title,
            color = if (active) Color.White else Theme.text.copy(alpha = 0.5f),
            fontSize = 13.sp,
            fontWeight = FontWeight.Bold,
        )
    }
}
