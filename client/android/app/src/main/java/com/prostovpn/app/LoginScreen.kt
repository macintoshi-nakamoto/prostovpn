package com.prostovpn.app

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@Composable
fun LoginScreen(state: AppState) {
    var login by rememberSaveable { mutableStateOf("") }
    var password by rememberSaveable { mutableStateOf("") }
    var showPassword by rememberSaveable { mutableStateOf(false) }

    var errorText by remember { mutableStateOf(state.consumeSignedOutReason()) }
    var isLoading by remember { mutableStateOf(false) }
    var isDone by remember { mutableStateOf(false) }

    val s = state.s
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val focusManager = LocalFocusManager.current
    val haptics = rememberHaptics()

    fun submit() {
        if (isLoading || isDone) return

        val credentials = login.trim()
        if (credentials.isEmpty()) {
            errorText = s.errEmptyLogin
            return
        }
        if (!credentials.startsWith("vpn://") && password.length < 4) {
            errorText = s.errShortPassword
            return
        }

        focusManager.clearFocus()
        errorText = ""
        isLoading = true

        scope.launch {
            if (credentials.startsWith("vpn://")) {
                isLoading = false
                if (state.loginWithKey(credentials)) {
                    isDone = true
                    haptics.success()
                    delay(450)
                } else {
                    errorText = s.errBadKey
                }
                return@launch
            }

            val result = state.login(credentials, password)
            isLoading = false
            result
                .onSuccess {
                    isDone = true
                    haptics.success()
                    delay(450)
                }
                .onFailure { error -> errorText = error.message ?: s.errBadKey }
        }
    }

    BoxWithConstraints(modifier = Modifier.fillMaxSize()) {
        val viewportHeight = maxHeight

        Box(Modifier.fillMaxSize().background(Theme.canvas))
        CanvasGlow(color = Theme.accent.copy(alpha = if (Theme.isLight) 0.16f else 0.30f))

        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .imePadding(),
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = viewportHeight)
                    .height(IntrinsicSize.Min)
                    .statusBarsPadding()
                    .navigationBarsPadding()
                    .padding(horizontal = 20.dp)
                    .padding(top = 24.dp, bottom = 26.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                androidx.compose.foundation.Image(
                    painter = androidx.compose.ui.res.painterResource(R.drawable.logo_wordmark),
                    contentDescription = "Prosto VPN",
                    contentScale = androidx.compose.ui.layout.ContentScale.Fit,
                    modifier = Modifier
                        .padding(top = 20.dp)
                        .height(22.dp)
                        .fadeUp(),
                )

                Spacer(Modifier.weight(1f))

                Column(
                    modifier = Modifier.fillMaxWidth().fadeUp(80),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Text(
                        text = s.loginTitle,
                        style = pro(38.sp, W.bold, Theme.text, tracking = em(38.sp, -0.035f)),
                    )
                    Spacer(Modifier.height(10.dp))
                    Text(
                        text = s.loginSub,
                        style = pro(15.sp, W.regular, Theme.textMuted),
                        textAlign = TextAlign.Center,
                    )
                }

                Spacer(Modifier.height(30.dp))

                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .glass(28.dp)
                        .fadeUp(140),
                ) {
                    val loginFocus = remember { FocusRequester() }
                    val passwordFocus = remember { FocusRequester() }

                    FieldRow(
                        label = s.loginField,
                        value = login,
                        focusRequester = loginFocus,
                        imeAction = ImeAction.Next,
                        onImeAction = { passwordFocus.requestFocus() },
                        onValueChange = { login = it; errorText = "" },
                    )
                    HairLine(inset = 20.dp)
                    FieldRow(
                        label = s.passwordField,
                        value = password,
                        focusRequester = passwordFocus,
                        imeAction = ImeAction.Go,
                        onImeAction = ::submit,
                        onValueChange = { password = it; errorText = "" },
                        visualTransformation = if (showPassword) {
                            VisualTransformation.None
                        } else {
                            PasswordVisualTransformation()
                        },
                        trailing = {
                            Text(
                                text = if (showPassword) s.hidePassword else s.showPassword,
                                style = pro(14.sp, W.semibold, Theme.textFaint),
                                modifier = Modifier
                                    .clip(RoundedCornerShape(10.dp))
                                    .noRippleClickable { showPassword = !showPassword }
                                    .padding(horizontal = 6.dp, vertical = 6.dp),
                            )
                        },
                    )
                }

                AnimatedVisibility(
                    visible = errorText.isNotEmpty(),
                    enter = expandVertically(tween(240)) + fadeIn(tween(200)),
                    exit = shrinkVertically(tween(180)) + fadeOut(tween(120)),
                ) {
                    Text(
                        text = errorText,
                        style = pro(13.sp, W.medium, Theme.errorText, lineHeight = 18.sp),
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(top = 12.dp, start = 6.dp, end = 6.dp),
                    )
                }

                Spacer(Modifier.height(14.dp))

                PrimaryPill(
                    text = when {
                        isLoading -> s.signingIn
                        isDone -> s.signInDone
                        else -> s.signIn
                    },
                    enabled = !isLoading && !isDone,
                    modifier = Modifier.fadeUp(180),
                    onClick = ::submit,
                )

                Spacer(Modifier.height(24.dp))

                Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
                    Text(
                        text = s.register,
                        style = pro(14.sp, W.medium, Theme.textFaint),
                        modifier = Modifier.noRippleClickable {
                            openUrl(context, "https://prostovpn.cc/login?mode=signup")
                        },
                    )
                    Text(
                        text = s.forgotPassword,
                        style = pro(14.sp, W.medium, Theme.textFaint),
                        modifier = Modifier.noRippleClickable {
                            openUrl(context, "https://prostovpn.cc/reset")
                        },
                    )
                }

                Spacer(Modifier.weight(0.32f))
            }
        }
    }
}

@Composable
private fun FieldRow(
    label: String,
    value: String,
    focusRequester: FocusRequester,
    imeAction: ImeAction,
    onImeAction: () -> Unit,
    onValueChange: (String) -> Unit,
    visualTransformation: VisualTransformation = VisualTransformation.None,
    trailing: (@Composable () -> Unit)? = null,
) {
    val interaction = remember { MutableInteractionSource() }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(68.dp)
            .noRippleClickable(haptic = false) { focusRequester.requestFocus() }
            .padding(horizontal = 20.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(label, style = pro(12.sp, W.semibold, Theme.textFaint))
            BasicTextField(
                value = value,
                onValueChange = onValueChange,
                singleLine = true,
                interactionSource = interaction,
                visualTransformation = visualTransformation,
                keyboardOptions = KeyboardOptions(
                    capitalization = KeyboardCapitalization.None,
                    autoCorrectEnabled = false,
                    imeAction = imeAction,
                ),
                keyboardActions = KeyboardActions(
                    onNext = { onImeAction() },
                    onGo = { onImeAction() },
                    onDone = { onImeAction() },
                ),
                textStyle = pro(16.sp, W.medium, Theme.text),
                cursorBrush = SolidColor(Theme.accent),
                modifier = Modifier
                    .fillMaxWidth()
                    .focusRequester(focusRequester),
                decorationBox = { innerTextField ->
                    Box(contentAlignment = Alignment.CenterStart) { innerTextField() }
                },
            )
        }

        if (trailing != null) {
            Spacer(Modifier.width(10.dp))
            trailing()
        }
    }
}
