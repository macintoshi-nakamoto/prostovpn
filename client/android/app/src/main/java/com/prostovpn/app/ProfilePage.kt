package com.prostovpn.app

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

private const val SITE = "https://prostovpn.cc"

/**
 * «Профиль» — всё, что не подключение: учётка, настройки, поддержка и переход
 * в кабинет. Подписку и тарифы приложение не показывает, только уводит туда.
 */
@Composable
fun ProfilePage(state: AppState, onOpenSettings: () -> Unit, onOpenSupport: () -> Unit) {
    val s = state.s
    val context = LocalContext.current
    var copied by remember { mutableStateOf(false) }

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
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                text = s.tabProfile,
                style = pro(24.sp, W.bold, Theme.text, tracking = em(24.sp, -0.025f)),
                modifier = Modifier.padding(top = 18.dp, bottom = 6.dp),
            )

            GlassCard(modifier = Modifier.fadeUp(), padding = 16.dp) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(
                        modifier = Modifier
                            .size(44.dp)
                            .clip(CircleShape)
                            .background(Theme.brandGradient),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(
                            text = state.accountName.take(1).uppercase().ifEmpty { "P" },
                            style = pro(18.sp, W.bold, Color.White, display = true),
                        )
                    }
                    Spacer(Modifier.width(14.dp))
                    Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                        Text(s.yourLogin, style = pro(13.sp, W.regular, Theme.textFaint))
                        Text(
                            text = state.accountName.ifEmpty { "—" },
                            style = pro(16.sp, W.semibold, Theme.text),
                            maxLines = 1,
                        )
                    }
                    MiniPill(text = if (copied) s.copied else s.copy) {
                        copyToClipboard(context, state.accountName)
                        copied = true
                    }
                }

                if (state.subscriptionDaysLeft > 0) {
                    Spacer(Modifier.height(14.dp))
                    HairLine(inset = 0.dp)
                    Spacer(Modifier.height(14.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                            Text(s.subscriptionLabel, style = pro(13.sp, W.regular, Theme.textFaint))
                            Text(
                                text = dayPhrase(state.subscriptionDaysLeft, state.lang, s),
                                style = pro(18.sp, W.bold, Theme.text, tabular = true),
                            )
                        }
                        if (state.renewUrl.isNotEmpty()) {
                            MiniPill(text = s.renew) { openUrl(context, state.renewUrl) }
                        }
                    }
                }
            }

            RowsCard(modifier = Modifier.fadeUp(60)) {
                MenuRow(title = s.settings, icon = Icons.gear, onClick = onOpenSettings)
                HairLine()
                MenuRow(title = s.supportTitle, icon = Icons.help, onClick = onOpenSupport)
                HairLine()
                MenuRow(
                    title = s.cabinet,
                    subtitle = s.cabinetSub,
                    icon = Icons.globe,
                    height = 70.dp,
                    onClick = { openUrl(context, "$SITE/account") },
                )
            }

            RowsCard(modifier = Modifier.fadeUp(110)) {
                MenuRow(
                    title = s.guideTitle,
                    subtitle = s.guideSub,
                    icon = Icons.star,
                    height = 70.dp,
                    onClick = { openUrl(context, "$SITE/guide") },
                )
                HairLine()
                MenuRow(
                    title = s.privacy,
                    icon = Icons.doc,
                    onClick = { openUrl(context, "$SITE/privacy") },
                )
                HairLine()
                MenuRow(
                    title = s.terms,
                    icon = Icons.docText,
                    onClick = { openUrl(context, "$SITE/terms") },
                )
            }

            Text(
                text = "Prosto VPN · ${s.version} ${BuildConfig.VERSION_NAME}",
                style = pro(12.sp, W.regular, Theme.textFaint),
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 6.dp),
            )

            Spacer(Modifier.navigationBarsPadding().height(96.dp))
        }
    }
}

fun copyToClipboard(context: Context, text: String) {
    if (text.isEmpty()) return
    val manager = context.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
    manager?.setPrimaryClip(ClipData.newPlainText("Prosto VPN", text))
}
