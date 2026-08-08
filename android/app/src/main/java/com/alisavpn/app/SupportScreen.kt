package com.alisavpn.app

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@Composable
fun SupportScreen(state: AppState, onBack: () -> Unit) {
    val s = strings(state.lang)
    val context = LocalContext.current

    fun open(url: String) {
        runCatching {
            context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 24.dp)
            .navigationBarsPadding(),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        BackRow(s.back, onBack)

        Spacer(Modifier.padding(top = 10.dp))

        Image(
            painter = painterResource(R.drawable.logo),
            contentDescription = null,
            modifier = Modifier.size(width = 120.dp, height = 80.dp),
        )

        Text(
            text = s.brand,
            color = Theme.text,
            fontSize = 22.sp,
            fontWeight = FontWeight.ExtraBold,
        )

        Text(
            text = "${s.version} 1.0",
            color = Theme.textMuted,
            fontSize = 13.sp,
            fontWeight = FontWeight.Medium,
        )

        Spacer(Modifier.padding(top = 15.dp))

        Card {
            LinkRow(Icons.telegram, s.supportTelegram, "@alisa_vpn_support") {
                open("https://t.me/alisa_vpn_support")
            }
            CardDivider()
            LinkRow(Icons.globe, s.supportSite, "alisavpn.com") {
                open("https://alisavpn.com")
            }
            CardDivider()
            LinkRow(Icons.help, s.supportFaq, s.supportFaqSub) {
                open("https://alisavpn.com/faq")
            }
        }

        Spacer(Modifier.weight(1f))
        Spacer(Modifier.padding(top = 24.dp))

        Text(
            text = s.footerLinks,
            color = Theme.textFaint,
            fontSize = 12.sp,
            modifier = Modifier.padding(bottom = 16.dp),
        )
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
            .clickable { onClick() }
            .padding(12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(38.dp)
                .clip(RoundedCornerShape(11.dp))
                .background(Theme.accentTint),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = Theme.accentSoft,
                modifier = Modifier.size(19.dp),
            )
        }

        Spacer(Modifier.width(14.dp))

        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(1.dp)) {
            Text(title, color = Theme.text, fontSize = 15.sp, fontWeight = FontWeight.Bold)
            Text(subtitle, color = Theme.textMuted, fontSize = 12.5.sp, fontWeight = FontWeight.Medium)
        }

        Icon(
            imageVector = Icons.chevronRight,
            contentDescription = null,
            tint = Theme.text.copy(alpha = 0.35f),
            modifier = Modifier.size(18.dp),
        )
    }
}
