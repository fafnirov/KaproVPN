package pro.kaprovpn.android.ui.theme

import androidx.compose.ui.graphics.Color

// Янтарная палитра (десктоп использует #F59E0B как accent). Несколько оттенков
// для разных Material3 ролей: primary (бренд), container (приглушённый фон под
// карточки/чипы), accent-dark (hover/pressed/disabled tints).
val AmberAccent = Color(0xFFF59E0B)
val AmberAccentDark = Color(0xFFB45309)
val AmberContainer = Color(0xFF3A2410)   // тёмный амбер-коричневый под карточки
val AmberOnContainer = Color(0xFFFFE0B2) // светлый амбер для текста на карточках

// Базовые тона тёмной темы. Десктоп-аналог — `gui/styles.py` DARK_QSS.
val DarkBackground = Color(0xFF0F0F12)
val DarkSurface = Color(0xFF1A1A1F)
val DarkSurfaceElevated = Color(0xFF26262C)
val DarkOnSurface = Color(0xFFE5E5E7)
val DarkOnSurfaceMuted = Color(0xFF9CA3AF)
