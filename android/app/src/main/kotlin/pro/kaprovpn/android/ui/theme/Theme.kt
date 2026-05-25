package pro.kaprovpn.android.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val DarkScheme = darkColorScheme(
    primary = AmberAccent,
    onPrimary = Color.Black,
    primaryContainer = AmberContainer,
    onPrimaryContainer = AmberOnContainer,
    secondary = AmberAccentDark,
    onSecondary = Color.Black,
    secondaryContainer = AmberContainer,
    onSecondaryContainer = AmberOnContainer,
    // tertiary мы тоже амбер-варианты, иначе M3-компоненты (chips, badges)
    // улетают в дефолтный M3-фиолетовый.
    tertiary = AmberAccent,
    onTertiary = Color.Black,
    tertiaryContainer = AmberContainer,
    onTertiaryContainer = AmberOnContainer,
    background = DarkBackground,
    surface = DarkSurface,
    surfaceVariant = DarkSurfaceElevated,
    onBackground = DarkOnSurface,
    onSurface = DarkOnSurface,
    onSurfaceVariant = DarkOnSurfaceMuted,
)

@Composable
fun KaproVpnTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = DarkScheme, content = content)
}
