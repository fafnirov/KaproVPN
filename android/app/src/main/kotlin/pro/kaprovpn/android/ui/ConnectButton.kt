package pro.kaprovpn.android.ui

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import pro.kaprovpn.android.R

/**
 * Большая круглая кнопка-индикатор подключения — главный visual element
 * на Home-экране. Дизайн копирует десктоп-клиент:
 * - 3 концентрических кольца с glow от центра к краю
 * - При Connected — янтарный, при Idle — приглушённый, при Failed — красный
 * - При Starting/Stopping — янтарный с пульсацией opacity
 *
 * Реализация через [Canvas] вместо `Modifier.blur` потому что blur доступен
 * только с API 31, а minSdk у нас 24. Три stroke-круга с разной альфой
 * визуально дают тот же эффект "glow".
 */
@Composable
fun ConnectButton(
    state: ConnectState,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    size: androidx.compose.ui.unit.Dp = 280.dp,
) {
    val accent = MaterialTheme.colorScheme.primary
    val muted = MaterialTheme.colorScheme.onSurfaceVariant
    val error = Color(0xFFEF4444)

    val targetColor = when (state) {
        ConnectState.Connected -> accent
        ConnectState.Failed -> error
        ConnectState.Idle -> muted
        else -> accent  // Starting/Stopping
    }
    val ringColor by animateColorAsState(
        targetValue = targetColor,
        animationSpec = tween(durationMillis = 400),
        label = "ringColor",
    )

    // Пульсация для transient state. От 0.4 до 1.0 alpha.
    val transient = state == ConnectState.Starting || state == ConnectState.Stopping
    val pulseAlpha = if (transient) {
        val transition = rememberInfiniteTransition(label = "pulse")
        val alpha by transition.animateFloat(
            initialValue = 0.4f,
            targetValue = 1.0f,
            animationSpec = infiniteRepeatable(
                animation = tween(800, easing = LinearEasing),
                repeatMode = RepeatMode.Reverse,
            ),
            label = "pulseAlpha",
        )
        alpha
    } else 1.0f

    val label = when (state) {
        ConnectState.Connected -> stringResource(R.string.home_disconnect)
        ConnectState.Idle, ConnectState.Failed -> stringResource(R.string.home_connect)
        ConnectState.Starting -> stringResource(R.string.home_connecting)
        ConnectState.Stopping -> stringResource(R.string.home_status_disconnecting).uppercase()
    }

    Box(
        modifier = modifier
            .size(size)
            .clip(CircleShape)
            .clickable { onClick() },
        contentAlignment = Alignment.Center,
    ) {
        Canvas(modifier = Modifier.size(size)) {
            val center = this.size.minDimension / 2f
            // Внешнее тонкое кольцо — самое блёклое (halo).
            drawCircle(
                color = ringColor.copy(alpha = 0.12f * pulseAlpha),
                radius = center,
                style = Stroke(width = 1.dp.toPx()),
            )
            // Среднее — полу-прозрачное.
            drawCircle(
                color = ringColor.copy(alpha = 0.35f * pulseAlpha),
                radius = center - 10.dp.toPx(),
                style = Stroke(width = 3.dp.toPx()),
            )
            // Основное — sharp янтарное.
            drawCircle(
                color = ringColor.copy(alpha = pulseAlpha),
                radius = center - 22.dp.toPx(),
                style = Stroke(width = 4.dp.toPx()),
            )
        }
        Text(
            text = label,
            style = MaterialTheme.typography.headlineMedium.copy(
                fontWeight = FontWeight.Bold,
            ),
            color = ringColor,
        )
    }
}

/** Упрощённое state для [ConnectButton]. Маппится из [pro.kaprovpn.android.vpn.XrayBridge.State]. */
enum class ConnectState { Idle, Starting, Connected, Stopping, Failed }
