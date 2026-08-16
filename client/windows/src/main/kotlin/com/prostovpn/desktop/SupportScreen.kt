package com.prostovpn.desktop

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
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

/**
 * Адрес сайта одной строкой: он же в подписи, он же во всех ссылках экрана.
 * Страницы указываем с расширением — так они открываются и когда сайт
 * отдаёт nginx, и когда его раздаёт сама панель.
 */
private const val SITE = "https://prostovpn.cc"

@Composable
fun SupportScreen(
    state: AppState,
    backdrop: BackdropState,
    onBack: () -> Unit,
    drag: @Composable (@Composable () -> Unit) -> Unit,
) {
    val s = state.s
    val uriHandler = LocalUriHandler.current

    fun open(url: String) {
        runCatching { uriHandler.openUri(url) }
    }

    Box(Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = Layout.screenPadding)
                .padding(bottom = Layout.screenPadding),
        ) {
            drag {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = Layout.topPadding),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    GlassBackButton(backdrop = backdrop, onBack = onBack)
                    Spacer(Modifier.weight(1f))
                }
            }

            // Опускаем знак от кнопки «назад»: не по центру экрана, а
            // примерно на трети — под ним ещё четыре карточки со ссылками, и
            // ровная середина увела бы их слишком низко.
            Spacer(Modifier.weight(0.5f))

            // Только логотип: название и версия отсюда убраны. Название
            // теперь читается с самого знака, а версию видно в настройках,
            // рядом с кнопкой обновления, — там она и нужна.
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 26.dp, bottom = 34.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                LogoImage(
                    modifier = Modifier.size(width = 186.dp, height = 25.dp),
                    glowAlpha = 0.35f,
                )
            }

            CardGroup {
                LinkRow(
                    icon = Icons.telegram,
                    title = s.tgTitle,
                    subtitle = "@prostovpnn_bot",
                ) { open("https://t.me/prostovpnn_bot") }
                CardDivider()
                LinkRow(
                    icon = Icons.globe,
                    title = s.siteTitle,
                    subtitle = "prostovpn.cc",
                ) { open("$SITE/") }
                CardDivider()
                LinkRow(
                    icon = Icons.help,
                    title = s.faqTitle,
                    subtitle = s.faqSub,
                ) { open("$SITE/faq.html") }
                CardDivider()
                LinkRow(
                    icon = Icons.star,
                    title = s.rateTitle,
                    subtitle = s.rateSub,
                ) { open("$SITE/download.html") }
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
                    modifier = Modifier.noRippleClickable { open("$SITE/privacy.html") },
                )
                Text(
                    text = " · ",
                    style = manrope(12.sp, W.regular, Theme.textFaint),
                )
                Text(
                    text = s.terms,
                    style = manrope(12.sp, W.regular, Theme.text.copy(alpha = 0.5f)),
                    modifier = Modifier.noRippleClickable { open("$SITE/offer.html") },
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
            .scaleClickable(0.98f, onClick = onClick)
            .clip(RoundedCornerShape(14.dp))
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
