package com.prostovpn.app

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
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
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

private const val SUPPORT_SITE = "https://prostovpn.cc"

@Composable
fun SupportScreen(state: AppState, onBack: () -> Unit) {
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
                .padding(horizontal = 16.dp),
        ) {
            ScreenHeader(title = s.supportTitle, onBack = onBack)

            Column(
                modifier = Modifier
                    .weight(1f)
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Spacer(Modifier.height(6.dp))

                HeroCard(state)

                RowsCard(modifier = Modifier.fadeUp(80)) {
                    MenuRow(
                        title = s.mailTitle,
                        subtitle = "help@prostovpn.cc",
                        height = 66.dp,
                        onClick = { openUrl(context, "mailto:help@prostovpn.cc") },
                    )
                    HairLine()
                    MenuRow(
                        title = s.siteAndCabinet,
                        subtitle = "prostovpn.cc",
                        height = 66.dp,
                        onClick = { openUrl(context, "$SUPPORT_SITE/account") },
                    )
                    HairLine()
                    MenuRow(
                        title = s.faqTitle,
                        subtitle = s.faqSub,
                        height = 66.dp,
                        onClick = { openUrl(context, "$SUPPORT_SITE/faq") },
                    )
                }

                GlassCard(modifier = Modifier.fadeUp(120), padding = 16.dp) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
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
                }

                Spacer(Modifier.navigationBarsPadding().height(24.dp))
            }
        }
    }
}

@Composable
private fun HeroCard(state: AppState) {
    val s = state.s
    val context = LocalContext.current
    val t = rememberInfiniteTransition(label = "supportDrift")
    val drift by t.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(6000, easing = Theme.easeStandard), RepeatMode.Reverse),
        label = "d1",
    )
    val drift2 by t.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(7500, easing = Theme.easeStandard), RepeatMode.Reverse),
        label = "d2",
    )

    Box(
        modifier = Modifier
            .fillMaxWidth()
            .glass(R2.plate)
            .fadeUp(),
    ) {
        Image(
            painter = painterResource(R.drawable.obj_ring_chrome),
            contentDescription = null,
            modifier = Modifier
                .align(Alignment.TopStart)
                .size(120.dp)
                .graphicsLayer {
                    // Объекты — награда за успех, а не помеха тексту: держим их
                    // на краях и приглушёнными.
                    alpha = if (Theme.isLight) 0.20f else 0.26f
                    translationX = (-46).dp.toPx()
                    translationY = (-40).dp.toPx() - drift * 10.dp.toPx()
                    rotationZ = -8f + drift * 6f
                },
        )
        Image(
            painter = painterResource(R.drawable.obj_mask_chrome),
            contentDescription = null,
            modifier = Modifier
                .align(Alignment.BottomEnd)
                .size(98.dp)
                .graphicsLayer {
                    alpha = if (Theme.isLight) 0.18f else 0.24f
                    translationX = 36.dp.toPx()
                    translationY = 34.dp.toPx() + drift2 * 8.dp.toPx()
                    rotationZ = 10f - drift2 * 6f
                },
        )

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp, vertical = 26.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                text = s.supportHeadline,
                style = pro(26.sp, W.bold, Theme.text, tracking = em(26.sp, -0.03f)),
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(8.dp))
            Text(
                text = s.supportHours,
                style = pro(14.sp, W.regular, Theme.textMuted, lineHeight = 20.sp),
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(20.dp))
            PrimaryPill(
                text = s.writeTelegram,
                icon = Icons.telegram,
                onClick = { openUrl(context, "https://t.me/temnoz") },
            )
        }
    }
}
