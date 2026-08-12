package com.prostovpn.desktop

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.togetherWith
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
fun LoginScreen(
    state: AppState,
    drag: @Composable (@Composable () -> Unit) -> Unit,
) {
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
        if (password.length < 4) {
            errorText = s.errShortPassword
            return
        }

        focusManager.clearFocus()
        errorText = ""
        isLoading = true

        scope.launch {
            // Единственный способ войти — логин и пароль из панели, их
            // выдают при покупке. Ключи vpn:// больше не принимаются:
            // человек за весь срок видит ровно две строки.
            val result = state.login(credentials, password)
            isLoading = false

            result
                .onSuccess {
                    isDone = true
                    haptics.success()
                    delay(450)
                }
                .onFailure { error ->
                    // Не текст панели: он русский, а интерфейс бывает
                    // английским. Перевод выбирается по коду причины.
                    errorText = state.loginError(error)
                }
        }
    }

    BoxWithConstraints(modifier = Modifier.fillMaxSize()) {
        val viewportHeight = maxHeight

        FloatingOrbs()


        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                ,
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = viewportHeight)
                    .height(IntrinsicSize.Min)
                    .padding(horizontal = 28.dp)
                    .padding(top = 56.dp, bottom = 36.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                // Отступ над знаком — такой же, как под ним: логотип встаёт по
                // центру свободного поля между верхом окна и формой, а не
                // липнет к самому верху.
                Spacer(
                    Modifier
                        .weight(1f)
                        .heightIn(min = 24.dp)
                )

                Header(
                    tagline = s.tagline,
                    modifier = Modifier.fadeUp(),
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

                    // Текст ошибки держим и во время анимации скрытия
                    val displayedError = remember { mutableStateOf("") }
                    if (errorText.isNotEmpty()) displayedError.value = errorText

                    androidx.compose.animation.AnimatedVisibility(
                        visible = errorText.isNotEmpty(),
                        enter = androidx.compose.animation.expandVertically(Theme.spring(280)) +
                            androidx.compose.animation.fadeIn(tween(220)),
                        exit = androidx.compose.animation.shrinkVertically(Theme.spring(220)) +
                            androidx.compose.animation.fadeOut(tween(150)),
                    ) {
                        Text(
                            text = displayedError.value,
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
        // Название отдельной строкой не пишем: его теперь несёт сам знак, а
        // подпись под ним говорит, что это за сервис.
        LogoImage(
            modifier = Modifier.size(width = 216.dp, height = 29.dp),
            glowAlpha = 0.28f,
        )

        Spacer(Modifier.height(12.dp))

        Text(
            text = tagline,
            style = manrope(14.sp, W.medium, Theme.textSecondary),
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

    val interaction = remember { MutableInteractionSource() }
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(56.dp)
            // масштаб — в начале цепочки, чтобы сжималась вся кнопка с тенью
            .pressScale(interaction, 0.98f)
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
            .clickable(
                interactionSource = interaction,
                indication = null,
                enabled = !isLoading && !isDone,
                onClick = onClick,
            ),
        contentAlignment = Alignment.Center,
    ) {
        androidx.compose.animation.AnimatedContent(
            targetState = text,
            label = "submitText",
            transitionSpec = {
                (androidx.compose.animation.scaleIn(
                    initialScale = 0.88f,
                    animationSpec = androidx.compose.animation.core.spring(
                        dampingRatio = 0.6f,
                        stiffness = 600f,
                    ),
                ) + androidx.compose.animation.fadeIn(tween(160))).togetherWith(
                    androidx.compose.animation.scaleOut(targetScale = 0.9f, animationSpec = tween(140)) +
                        androidx.compose.animation.fadeOut(tween(120))
                )
            },
        ) { label ->
            Text(
                text = label,
                style = manrope(17.sp, W.bold, Color.White),
                modifier = Modifier.alpha(contentAlpha),
            )
        }
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
