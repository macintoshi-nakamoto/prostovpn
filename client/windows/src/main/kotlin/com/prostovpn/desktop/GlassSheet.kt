package com.prostovpn.desktop

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.hoverable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsHoveredAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.TransformOrigin
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.PointerEventType
import androidx.compose.ui.input.pointer.isSecondaryPressed
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * Стеклянная шторка внутри окна приложения.
 *
 * Системные окна (ModalBottomSheet/Dialog) на десктопе рисуются отдельным окном
 * с прямыми углами и не умеют сэмплировать фон приложения, поэтому шторка живёт
 * прямо в окне: скруглённая всегда, стекло берёт фон из [backdrop], выезд —
 * пружиной, закрытие — по клику на затемнение, свайпу вниз или Esc.
 */
@Composable
fun GlassSheet(
    visible: Boolean,
    backdrop: BackdropState,
    onDismiss: () -> Unit,
    corner: Dp = Layout.sheetCorner,
    content: @Composable ColumnScope.() -> Unit,
) {
    // Держим содержимое в композиции, пока шторка уезжает
    var keepAlive by remember { mutableStateOf(visible) }
    val progress = remember { Animatable(0f) }

    LaunchedEffect(visible) {
        if (visible) {
            keepAlive = true
            progress.animateTo(1f, spring(dampingRatio = 0.86f, stiffness = 320f))
        } else {
            progress.animateTo(0f, tween(240))
            keepAlive = false
        }
    }

    if (!keepAlive) return

    Box(Modifier.fillMaxSize()) {
        // Затемнение фона
        Box(
            Modifier
                .fillMaxSize()
                .graphicsLayer { alpha = progress.value }
                .background(Color.Black.copy(alpha = 0.45f))
                .noRippleClickable { onDismiss() }
        )

        Column(
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth()
                .graphicsLayer {
                    translationY = (1f - progress.value) * size.height
                }
                .clip(RoundedCornerShape(topStart = corner, topEnd = corner))
                .liquidGlass(
                    backdrop = backdrop,
                    cornerRadius = corner,
                    blurRadius = 26.dp,
                    saturation = 1.7f,
                    refractionHeight = 18.dp,
                    refractionAmount = 16.dp,
                    tintAlpha = 0.06f,
                )
                // Свайп вниз закрывает шторку
                .pointerInput(Unit) {
                    var dragged = 0f
                    detectDragGestures(
                        onDragStart = { dragged = 0f },
                        onDragEnd = { if (dragged > 60f) onDismiss() },
                    ) { change, drag ->
                        change.consume()
                        if (drag.y > 0) dragged += drag.y
                    }
                }
                // Клик по самой шторке не должен её закрывать
                .noRippleClickable { },
        ) {
            SheetHandle()
            content()
        }
    }
}

@Composable
fun SheetHandle() {
    Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
        Box(
            modifier = Modifier
                .padding(top = 10.dp, bottom = 2.dp)
                .size(width = 38.dp, height = 5.dp)
                .clip(RoundedCornerShape(2.5.dp))
                .background(Color.White.copy(alpha = 0.20f))
        )
    }
}

/**
 * Модальное окно-карточка по центру (замена системного Dialog):
 * всегда со скруглёнными углами, стекло сэмплирует фон приложения.
 */
@Composable
fun GlassDialog(
    visible: Boolean,
    backdrop: BackdropState,
    onDismiss: () -> Unit,
    content: @Composable ColumnScope.() -> Unit,
) {
    var keepAlive by remember { mutableStateOf(visible) }
    val progress = remember { Animatable(0f) }

    LaunchedEffect(visible) {
        if (visible) {
            keepAlive = true
            progress.animateTo(1f, spring(dampingRatio = 0.8f, stiffness = 380f))
        } else {
            progress.animateTo(0f, tween(200))
            keepAlive = false
        }
    }

    if (!keepAlive) return

    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Box(
            Modifier
                .fillMaxSize()
                .graphicsLayer { alpha = progress.value }
                .background(Color.Black.copy(alpha = 0.5f))
                .noRippleClickable { onDismiss() }
        )

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 28.dp)
                .graphicsLayer {
                    val p = progress.value
                    alpha = p
                    scaleX = 0.9f + 0.1f * p
                    scaleY = 0.9f + 0.1f * p
                }
                .clip(RoundedCornerShape(26.dp))
                .liquidGlass(
                    backdrop = backdrop,
                    cornerRadius = 26.dp,
                    blurRadius = 28.dp,
                    saturation = 1.7f,
                    refractionHeight = 16.dp,
                    refractionAmount = 14.dp,
                    tintAlpha = 0.07f,
                )
                .noRippleClickable { }
                .padding(horizontal = 22.dp, vertical = 22.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(0.dp),
            content = content,
        )
    }
}

/**
 * Контекстное меню по правой кнопке мыши — стеклянная карточка
 * рядом с курсором.
 */
@Composable
fun GlassContextMenu(
    visible: Boolean,
    position: Offset,
    backdrop: BackdropState,
    onDismiss: () -> Unit,
    content: @Composable ColumnScope.() -> Unit,
) {
    val alpha by animateFloatAsState(
        targetValue = if (visible) 1f else 0f,
        animationSpec = tween(if (visible) 140 else 110),
        label = "menuAlpha",
    )
    if (!visible && alpha < 0.01f) return

    Box(Modifier.fillMaxSize()) {
        Box(
            Modifier
                .fillMaxSize()
                .noRippleClickable { onDismiss() }
        )

        Column(
            modifier = Modifier
                .graphicsLayer {
                    this.alpha = alpha
                    translationX = position.x
                    translationY = position.y
                    scaleX = 0.94f + 0.06f * alpha
                    scaleY = 0.94f + 0.06f * alpha
                    transformOrigin = TransformOrigin(0f, 0f)
                }
                .clip(RoundedCornerShape(16.dp))
                .liquidGlass(
                    backdrop = backdrop,
                    cornerRadius = 16.dp,
                    blurRadius = 22.dp,
                    saturation = 1.7f,
                    refractionHeight = 12.dp,
                    refractionAmount = 11.dp,
                    tintAlpha = 0.08f,
                )
                .padding(5.dp),
            content = content,
        )
    }
}

/**
 * Правый клик по элементу: отдаёт позицию курсора в координатах окна,
 * чтобы меню появилось точно под указателем.
 */
fun Modifier.rightClickable(onRightClick: (Offset) -> Unit): Modifier = composed {
    var origin by remember { mutableStateOf(Offset.Zero) }
    this
        .onGloballyPositioned { origin = it.positionInWindow() }
        .pointerInput(Unit) {
            awaitPointerEventScope {
                while (true) {
                    val event = awaitPointerEvent(PointerEventPass.Main)
                    if (event.type == PointerEventType.Press &&
                        event.buttons.isSecondaryPressed
                    ) {
                        val local = event.changes.firstOrNull()?.position ?: Offset.Zero
                        event.changes.forEach { it.consume() }
                        onRightClick(origin + local)
                    }
                }
            }
        }
}

/** Пункт контекстного меню. */
@Composable
fun ContextMenuItem(
    text: String,
    destructive: Boolean = false,
    icon: ImageVector? = null,
    onClick: () -> Unit,
) {
    val interaction = remember { MutableInteractionSource() }
    val hovered by interaction.collectIsHoveredAsState()
    Row(
        modifier = Modifier
            .clip(RoundedCornerShape(11.dp))
            .background(
                if (hovered) Color.White.copy(alpha = 0.08f) else Color.Transparent
            )
            .hoverable(interaction)
            .noRippleClickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 9.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (icon != null) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = if (destructive) Theme.link else Theme.text.copy(alpha = 0.8f),
                modifier = Modifier.size(15.dp),
            )
            Spacer(Modifier.width(9.dp))
        }
        Text(
            text = text,
            style = manrope(
                13.5.sp,
                W.semibold,
                if (destructive) Theme.link else Theme.text.copy(alpha = 0.9f),
            ),
        )
    }
}
