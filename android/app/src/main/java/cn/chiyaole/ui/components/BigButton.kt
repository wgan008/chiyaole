package cn.chiyaole.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import cn.chiyaole.ui.theme.Dimens
import cn.chiyaole.ui.theme.SecondaryBg
import cn.chiyaole.ui.theme.SecondaryBorder
import cn.chiyaole.ui.theme.SecondaryText

/**
 * The primary interaction primitive — spec: "All tap. No swiping, anywhere." heightIn(min
 * = ...), never height(...), so it can grow past [minHeight] rather than clip when the
 * label wraps at max font scale (spec §3.4-④). [minHeight] defaults to the full primary
 * size; pass [Dimens.secondaryButtonMinHeight] for a wireframe-style secondary action.
 */
@Composable
fun BigButton(
    text: String,
    backgroundColor: Color,
    contentColor: Color,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    minHeight: Dp = Dimens.buttonMinHeight,
    maxFontSize: androidx.compose.ui.unit.TextUnit = Dimens.primaryTextSp,
) {
    Button(
        onClick = onClick,
        modifier = modifier
            .fillMaxWidth()
            .heightIn(min = minHeight),
        shape = RoundedCornerShape(16.dp),
        colors = ButtonDefaults.buttonColors(containerColor = backgroundColor, contentColor = contentColor),
    ) {
        AutoSizeText(
            text = text,
            style = TextStyle(fontWeight = FontWeight.Bold, color = contentColor),
            maxFontSize = maxFontSize,
            minFontSize = Dimens.minTextSp,
            maxLines = 2,
        )
    }
}

/**
 * Wireframe `.b-2` / `.b-2.w` — the 等会儿吃 / 这次不吃 pair. Deliberately muted (light
 * background + border, not a saturated color): the wireframe's whole point is that
 * hierarchy between "吃了" and these two comes from SIZE, not from color-coding severity.
 * Meant to sit two-in-a-row (`row2` in the wireframe), each `Modifier.weight(1f)`.
 */
@Composable
fun SecondaryButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    backgroundColor: Color = SecondaryBg,
    borderColor: Color = SecondaryBorder,
    contentColor: Color = SecondaryText,
) {
    Button(
        onClick = onClick,
        modifier = modifier.heightIn(min = Dimens.secondaryButtonMinHeight),
        shape = RoundedCornerShape(10.dp),
        colors = ButtonDefaults.buttonColors(containerColor = backgroundColor, contentColor = contentColor),
        border = BorderStroke(1.5.dp, borderColor),
    ) {
        AutoSizeText(
            text = text,
            style = TextStyle(fontWeight = FontWeight.Bold, color = contentColor),
            maxFontSize = 22.sp,
            minFontSize = 16.sp,
            maxLines = 2,
        )
    }
}

