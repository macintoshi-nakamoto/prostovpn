package com.alisavpn.app

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
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
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@Composable
fun LoginScreen(state: AppState) {
    var login by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var showPassword by remember { mutableStateOf(false) }
    var errorText by remember { mutableStateOf("") }

    val s = strings(state.lang)
    val loginFocus = remember { FocusRequester() }
    val passwordFocus = remember { FocusRequester() }

    fun submit() {
        when (val result = state.login(login, password)) {
            is AppState.LoginResult.Success -> errorText = ""
            is AppState.LoginResult.Error -> errorText = result.message
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .imePadding()
            .padding(horizontal = 28.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Image(
            painter = painterResource(R.drawable.logo),
            contentDescription = null,
            modifier = Modifier.size(width = 190.dp, height = 127.dp),
        )

        Text(
            text = s.brand,
            color = Theme.text,
            fontSize = 28.sp,
            fontWeight = FontWeight.ExtraBold,
        )

        Spacer(Modifier.height(4.dp))

        Text(
            text = s.loginSubtitle,
            color = Theme.textMuted,
            fontSize = 14.sp,
            fontWeight = FontWeight.Medium,
        )

        Spacer(Modifier.height(34.dp))

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(20.dp))
                .background(Theme.card)
                .padding(6.dp)
        ) {
            FieldRow(
                icon = Icons.person,
                value = login,
                placeholder = s.loginPlaceholder,
                focusRequester = loginFocus,
                imeAction = ImeAction.Next,
                onImeAction = { passwordFocus.requestFocus() },
                onValueChange = { login = it; errorText = "" },
            )

            Box(
                Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 10.dp)
                    .height(1.dp)
                    .background(Theme.divider)
            )

            FieldRow(
                icon = Icons.lock,
                value = password,
                placeholder = s.passwordPlaceholder,
                focusRequester = passwordFocus,
                imeAction = ImeAction.Done,
                onImeAction = { submit() },
                onValueChange = { password = it; errorText = "" },
                visualTransformation = if (showPassword) VisualTransformation.None else PasswordVisualTransformation(),
                trailing = {
                    Icon(
                        imageVector = if (showPassword) Icons.eye else Icons.eyeOff,
                        contentDescription = if (showPassword) "Скрыть пароль" else "Показать пароль",
                        tint = Theme.text.copy(alpha = 0.4f),
                        modifier = Modifier
                            .size(40.dp)
                            .clip(CircleShape)
                            .clickable { showPassword = !showPassword }
                            .padding(9.dp),
                    )
                },
            )
        }

        if (errorText.isNotEmpty()) {
            Spacer(Modifier.height(8.dp))
            Text(
                text = errorText,
                color = Theme.accentSoft,
                fontSize = 13.sp,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 8.dp),
            )
        }

        Spacer(Modifier.height(12.dp))

        // CTA
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(56.dp)
                .clip(RoundedCornerShape(18.dp))
                .background(Theme.accentGradient)
                .clickable { submit() },
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = s.signIn,
                color = Color.White,
                fontSize = 17.sp,
                fontWeight = FontWeight.Bold,
            )
        }

        Spacer(Modifier.height(24.dp))

        Text(
            text = s.terms,
            color = Theme.textFaint,
            fontSize = 12.sp,
        )
    }
}

@Composable
private fun FieldRow(
    icon: ImageVector,
    value: String,
    placeholder: String,
    focusRequester: FocusRequester,
    imeAction: ImeAction,
    onImeAction: () -> Unit,
    onValueChange: (String) -> Unit,
    visualTransformation: VisualTransformation = VisualTransformation.None,
    trailing: (@Composable () -> Unit)? = null,
) {
    val interactionSource = remember { MutableInteractionSource() }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(52.dp)
            .clickable(interactionSource = interactionSource, indication = null) {
                focusRequester.requestFocus()
            }
            .padding(horizontal = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = Theme.text.copy(alpha = 0.4f),
            modifier = Modifier.size(20.dp),
        )

        Spacer(Modifier.width(12.dp))

        BasicTextField(
            value = value,
            onValueChange = onValueChange,
            singleLine = true,
            visualTransformation = visualTransformation,
            keyboardOptions = KeyboardOptions(imeAction = imeAction),
            keyboardActions = KeyboardActions(
                onNext = { onImeAction() },
                onDone = { onImeAction() },
            ),
            textStyle = TextStyle(
                color = Theme.text,
                fontSize = 16.sp,
                fontWeight = FontWeight.Medium,
            ),
            cursorBrush = SolidColor(Theme.vibrant),
            modifier = Modifier
                .weight(1f)
                .focusRequester(focusRequester),
            decorationBox = { innerTextField ->
                Box(contentAlignment = Alignment.CenterStart) {
                    if (value.isEmpty()) {
                        Text(
                            text = placeholder,
                            color = Theme.text.copy(alpha = 0.32f),
                            fontSize = 16.sp,
                            fontWeight = FontWeight.Medium,
                        )
                    }
                    innerTextField()
                }
            },
        )

        trailing?.invoke()
    }
}
