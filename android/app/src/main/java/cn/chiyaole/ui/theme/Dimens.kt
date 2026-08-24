package cn.chiyaole.ui.theme

import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * data/remote_config.json `ui`: min_text_sp 24, primary_text_sp 40, button_min_height_dp 96.
 * ★ "Layout must survive 1.75x system font scaling (spec §3.4-④). Never hard-code heights."
 * — every screen built from these must use Modifier.heightIn(min = ...), never height(...),
 * and every Text must carry maxLines + an autosize fallback.
 */
object Dimens {
    val minTextSp: TextUnit = 24.sp
    val primaryTextSp: TextUnit = 40.sp
    val buttonMinHeight: Dp = 96.dp
    val screenPadding: Dp = 24.dp
    val buttonSpacing: Dp = 16.dp

    // Wireframe A1 annotation: "次级两个：灰底、约主按钮 55% 高度。用尺寸而非隐藏来建立层级"
    // (secondary buttons: grey background, ~55% of the primary button's height —
    // hierarchy comes from SIZE, not from hiding or a third saturated color).
    val secondaryButtonMinHeight: Dp = 56.dp // ~55% of 96dp, still comfortably tappable
    val micButtonMinHeight: Dp = 52.dp
}
