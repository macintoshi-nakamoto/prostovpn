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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@Composable
fun SupportScreen(state: AppState, onBack: () -> Unit) {
    val s = state.s
    val uriHandler = LocalUriHandler.current

    fun open(url: String) {
        runCatching { uriHandler.openUri(url) }
    }

    val backdrop = rememberBackdropState()

    Box(Modifier.fillMaxSize()) {
        Box(
            Modifier
                .fillMaxSize()
                .backdropSource(backdrop)
        ) {
            Box(
                Modifier
                    .fillMaxSize()
                    .background(Theme.background)
            )
            SoftTopOrb()
        }

        Column(
            modifier = Modifier
                .fillMaxSize()
                .statusBarsPadding()
                .padding(horizontal = 24.dp)
                .navigationBarsPadding()
                .padding(bottom = 16.dp),
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 8.dp),
            ) {
                GlassBackButton(backdrop = backdrop, onBack = onBack)
            }

            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 10.dp, bottom = 30.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                LogoImage(
                    modifier = Modifier.size(width = 120.dp, height = 80.dp),
                    glowAlpha = 0.35f,
                )

                Text(
                    text = "Prosto VPN",
                    style = manrope(22.sp, W.extraBold, Theme.text),
                )

                Spacer(Modifier.height(2.dp))

                Text(
                    text = s.version,
                    style = manrope(13.sp, W.medium, Theme.textMuted),
                )
            }

            CardGroup {
                LinkRow(
                    icon = Icons.telegram,
                    title = s.tgTitle,
                    subtitle = "@prosto_vpn_supp",
                ) { open("https://t.me/prosto_vpn_supp") }
                CardDivider()
                LinkRow(
                    icon = Icons.globe,
                    title = s.siteTitle,
                    subtitle = "prostovpn.media",
                ) { open("https://prostovpn.media") }
                CardDivider()
                LinkRow(
                    icon = Icons.help,
                    title = s.faqTitle,
                    subtitle = s.faqSub,
                ) { open("https://prostovpn.media/faq") }
                CardDivider()
                LinkRow(
                    icon = Icons.star,
                    title = s.rateTitle,
                    subtitle = s.rateSub,
                ) { open("https://prostovpn.media/app") }
            }

            Spacer(Modifier.weight(1f))

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = s.privacy,
                    style = manrope(12.sp, W.regular, Theme.text.copy(alpha = 0.5f)),
                    modifier = Modifier.noRippleClickable { open("https://prostovpn.media/privacy") },
                )
                Text(
                    text = " · ",
                    style = manrope(12.sp, W.regular, Theme.textFaint),
                )
                Text(
                    text = s.terms,
                    style = manrope(12.sp, W.regular, Theme.text.copy(alpha = 0.5f)),
                    modifier = Modifier.noRippleClickable { open("https://prostovpn.media/terms") },
                )
            }
        }
    }
}

@Composable
private fun LinkRow(
    icon: ImageVector,
    title: String,
    subtitle: String,
    onClick: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .scaleClickable(0.98f, onClick = onClick)
            .padding(vertical = 12.dp, horizontal = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(38.dp)
                .clip(RoundedCornerShape(11.dp))
                .background(Theme.accentTint12),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = Theme.accentSoft,
                modifier = Modifier.size(18.dp),
            )
        }

        Spacer(Modifier.width(14.dp))

        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(1.dp)) {
            Text(title, style = manrope(15.sp, W.bold, Theme.text))
            Text(subtitle, style = manrope(12.5.sp, W.medium, Theme.textMuted))
        }

        Icon(
            imageVector = Icons.chevronRight,
            contentDescription = null,
            tint = Theme.textTertiary,
            modifier = Modifier.size(16.dp),
        )
    }
}
