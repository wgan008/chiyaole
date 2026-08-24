package cn.chiyaole.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight

/**
 * ★ Deliberately does not offer a dark variant per system setting. This app has exactly one
 * palette — high fixed contrast for low vision / cataracts (spec §"Visual rules") — and
 * following the system dark-mode toggle would silently change contrast ratios that were
 * chosen and tested against a specific population.
 */
private val ChiYaoLeColorScheme = lightColorScheme(
    primary = PrimaryGreen,
    onPrimary = White,
    secondary = BrandYellow,
    onSecondary = TrueBlack,
    error = AlertRed,
    onError = White,
    background = White,
    onBackground = TrueBlack,
    surface = White,
    onSurface = TrueBlack,
)

private val ChiYaoLeTypography = Typography(
    bodyLarge = TextStyle(fontSize = Dimens.minTextSp, fontWeight = FontWeight.Normal),
    titleLarge = TextStyle(fontSize = Dimens.primaryTextSp, fontWeight = FontWeight.Bold),
    labelLarge = TextStyle(fontSize = Dimens.minTextSp, fontWeight = FontWeight.Medium),
)

@Composable
fun ChiYaoLeTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = ChiYaoLeColorScheme,
        typography = ChiYaoLeTypography,
        content = content,
    )
}
