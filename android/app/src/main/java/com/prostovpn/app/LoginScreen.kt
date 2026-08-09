package com.prostovpn.app

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsFocusedAsState
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
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
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
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@Composable
fun LoginScreen(state: AppState) {
    var login by rememberSaveable { mutableStateOf("") }
    var password by rememberSaveable { mutableStateOf("") }
    var showPassword by rememberSaveable { mutableStateOf(false) }
    var errorText by remember { mutableStateOf("") }
    var isLoading by remember { mutableStateOf(false) }
    var isDone by remember { mutableStateOf(false) }

    val s = state.s
    val scope = rememberCoroutineScope()
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
            delay(1200)

            val joined = credentials.filterNot { it.isWhitespace() }
            if (joined.startsWith("vpn://") && KeyParser.extractServer(joined) == null) {
                isLoading = false
                errorText = s.errBadKey
                return@launch
            }

            isLoading = false
            isDone = true
            haptics.success()

            delay(450)
            state.login(credentials)
        }
    }

    BoxWithConstraints(modifier = Modifier.fillMaxSize()) {
        val viewportHeight = maxHeight

        FloatingOrbs()

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
                    .padding(horizontal = 28.dp)
                    .padding(top = 24.dp, bottom = 40.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Header(
                    tagline = s.tagline,
                    modifier = Modifier
                        .padding(top = 44.dp)
                        .fadeUp(),
                )

                Spacer(
                    Modifier
                        .weight(1f)
                        .heightIn(min = 24.dp)
                )

                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .fadeUp(120),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    FormBlock(
                        login = login,
                        password = password,
                        showPassword = showPassword,
                        loginPlaceholder = s.loginPlaceholder,
                        passwordPlaceholder = s.passwordPlaceholder,
                        onLoginChange = { login = it; errorText = "" },
                        onPasswordChange = { password = it; errorText = "" },
                        onTogglePassword = { showPassword = !showPassword },
                        onSubmit = ::submit,
                    )

                    if (errorText.isNotEmpty()) {
                        Text(
                            text = errorText,
                            style = manrope(13.sp, W.semibold, Theme.accentSoft),
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 8.dp),
                        )
                    }

                    SubmitButton(
                        text = when {
                            isLoading -> s.signingIn
                            isDone -> s.signInDone
                            else -> s.signIn
                        },
                        isLoading = isLoading,
                        isDone = isDone,
                        onClick = ::submit,
                    )

                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(40.dp)
                            .clip(RoundedCornerShape(12.dp))
                            .scaleClickable(0.98f, enabled = !isLoading && !isDone) {
                                focusManager.clearFocus()
                                state.loginAsGuest()
                            },
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(
                            text = s.continueWithoutAccount,
                            style = manrope(14.sp, W.semibold, Theme.textSecondary),
                            textAlign = TextAlign.Center,
                        )
                    }
                }

                Footer(
                    prefix = s.termsPrefix,
                    link = s.termsLink,
                    modifier = Modifier
                        .padding(top = 28.dp)
                        .fadeUp(220),
                )
            }
        }
    }
}

@Composable
private fun Header(tagline: String, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        LogoImage(
            modifier = Modifier.size(width = 190.dp, height = 127.dp),
            glowAlpha = 0.35f,
        )

        Text(
            text = "Prosto VPN",
            style = manrope(28.sp, W.extraBold, Theme.text, letterSpacing = 0.5.sp),
            modifier = Modifier.offset(y = (-8).dp),
        )

        Spacer(Modifier.height(4.dp))

        Text(
            text = tagline,
            style = manrope(14.sp, W.medium, Theme.textSecondary),
            modifier = Modifier.offset(y = (-8).dp),
        )
    }
}

@Composable
private fun FormBlock(
    login: String,
    password: String,
    showPassword: Boolean,
    loginPlaceholder: String,
    passwordPlaceholder: String,
    onLoginChange: (String) -> Unit,
    onPasswordChange: (String) -> Unit,
    onTogglePassword: () -> Unit,
    onSubmit: () -> Unit,
) {
    val loginFocus = remember { FocusRequester() }
    val passwordFocus = remember { FocusRequester() }

    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        FieldRow(
            icon = Icons.person,
            value = login,
            placeholder = loginPlaceholder,
            focusRequester = loginFocus,
            imeAction = ImeAction.Next,
            onImeAction = { passwordFocus.requestFocus() },
            onValueChange = onLoginChange,
        )

        Box(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 4.dp)
                .height(1.dp)
                .background(Theme.divider)
        )

        FieldRow(
            icon = Icons.lock,
            value = password,
            placeholder = passwordPlaceholder,
            focusRequester = passwordFocus,
            imeAction = ImeAction.Go,
            onImeAction = onSubmit,
            onValueChange = onPasswordChange,
            visualTransformation = if (showPassword) {
                VisualTransformation.None
            } else {
                PasswordVisualTransformation()
            },
            trailing = {
                Box(
                    modifier = Modifier
                        .size(width = 32.dp, height = 44.dp)
                        .clip(CircleShape)
                        .noRippleClickable(onClick = onTogglePassword),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        imageVector = if (showPassword) Icons.eye else Icons.eyeOff,
                        contentDescription = null,
                        tint = Theme.textMuted,
                        modifier = Modifier.size(19.dp),
                    )
                }
            },
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
    val interaction = remember { MutableInteractionSource() }
    val focused by interaction.collectIsFocusedAsState()
    val bgAlpha by animateFloatAsState(
        targetValue = if (focused) 1f else 0f,
        animationSpec = tween(200),
        label = "fieldBg",
    )

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(52.dp)
            .clip(RoundedCornerShape(14.dp))
            .background(Theme.rowActive.copy(alpha = Theme.rowActive.alpha * bgAlpha))
            .noRippleClickable { focusRequester.requestFocus() }
            .padding(horizontal = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.width(22.dp), contentAlignment = Alignment.Center) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = Theme.textMuted,
                modifier = Modifier.size(21.dp),
            )
        }

        Spacer(Modifier.width(12.dp))

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
            textStyle = manrope(16.sp, W.medium, Theme.text),
            cursorBrush = SolidColor(Theme.link),
            modifier = Modifier
                .weight(1f)
                .focusRequester(focusRequester),
            decorationBox = { innerTextField ->
                Box(contentAlignment = Alignment.CenterStart) {
                    if (value.isEmpty()) {
                        Text(
                            text = placeholder,
                            style = manrope(16.sp, W.medium, Theme.text.copy(alpha = 0.32f)),
                        )
                    }
                    innerTextField()
                }
            },
        )

        trailing?.invoke()
    }
}

@Composable
private fun SubmitButton(
    text: String,
    isLoading: Boolean,
    isDone: Boolean,
    onClick: () -> Unit,
) {
    val successAlpha by animateFloatAsState(
        targetValue = if (isDone) 1f else 0f,
        animationSpec = tween(300),
        label = "success",
    )
    val contentAlpha by animateFloatAsState(
        targetValue = if (isLoading) 0.7f else 1f,
        animationSpec = tween(200),
        label = "loading",
    )

    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(56.dp)
            .softShadow(Theme.accent.copy(alpha = 0.35f), 14.dp, 18.dp, yOffset = 8.dp)
            .clip(RoundedCornerShape(18.dp))
            .background(Theme.accentGradient)
            .drawWithContent {
                if (successAlpha > 0f) {
                    drawRoundRect(
                        brush = Theme.successGradient,
                        cornerRadius = CornerRadius(18.dp.toPx(), 18.dp.toPx()),
                        alpha = successAlpha,
                    )
                }
                drawContent()
                val strokeW = 1.dp.toPx()
                drawRoundRect(
                    brush = Brush.verticalGradient(
                        0f to Color.White.copy(alpha = 0.25f),
                        0.5f to Color.Transparent,
                    ),
                    topLeft = Offset(strokeW / 2f, strokeW / 2f),
                    size = androidx.compose.ui.geometry.Size(size.width - strokeW, size.height - strokeW),
                    cornerRadius = CornerRadius(18.dp.toPx() - strokeW / 2f, 18.dp.toPx() - strokeW / 2f),
                    style = Stroke(width = strokeW),
                )
            }
            .scaleClickable(0.98f, enabled = !isLoading && !isDone, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = text,
            style = manrope(17.sp, W.bold, Color.White),
            modifier = Modifier.alpha(contentAlpha),
        )
    }
}

@Composable
private fun Footer(prefix: String, link: String, modifier: Modifier = Modifier) {
    val annotated: AnnotatedString = buildAnnotatedString {
        withStyle(SpanStyle(color = Theme.textFaint)) { append(prefix) }
        withStyle(SpanStyle(color = Theme.text.copy(alpha = 0.5f))) { append(link) }
    }
    Text(
        text = annotated,
        style = manrope(12.sp, W.regular),
        textAlign = TextAlign.Center,
        modifier = modifier.fillMaxWidth(),
    )
}

@Composable
private fun FloatingOrbs() {
    val drift by rememberInfiniteTransition(label = "orbs").animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            tween(9000, easing = androidx.compose.animation.core.FastOutSlowInEasing),
            RepeatMode.Reverse,
        ),
        label = "drift1",
    )
    val drift2 by rememberInfiniteTransition(label = "orbs2").animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            tween(11000, easing = androidx.compose.animation.core.FastOutSlowInEasing),
            RepeatMode.Reverse,
        ),
        label = "drift2",
    )
    val density = LocalDensity.current

    androidx.compose.foundation.Canvas(Modifier.fillMaxSize()) {
        with(density) {
            val c1 = Offset(
                90.dp.toPx() + drift * 30.dp.toPx(),
                50.dp.toPx() - drift * 40.dp.toPx(),
            )
            val r1 = 170.dp.toPx() * (1f + 0.15f * drift)
            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(Theme.accent.copy(alpha = 0.20f), Color.Transparent),
                    center = c1,
                    radius = r1,
                ),
                radius = r1,
                center = c1,
            )

            val c2 = Offset(
                size.width - 50.dp.toPx() - drift2 * 40.dp.toPx(),
                size.height - 200.dp.toPx() + drift2 * 30.dp.toPx(),
            )
            val r2 = 150.dp.toPx() * (1f + 0.10f * drift2)
            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(Theme.accentWarm.copy(alpha = 0.14f), Color.Transparent),
                    center = c2,
                    radius = r2,
                ),
                radius = r2,
                center = c2,
            )
        }
    }
}
