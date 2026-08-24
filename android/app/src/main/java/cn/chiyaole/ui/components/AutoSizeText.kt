package cn.chiyaole.ui.components

import androidx.compose.foundation.layout.Box
import androidx.compose.material3.LocalTextStyle
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.sp

/**
 * Shrinks in 2sp steps until it stops clipping, never below [minFontSize]. Needed because
 * this Compose BOM predates the built-in autosize Text API, and spec §3.4-④ is a hard
 * requirement: "at 1.75x display+font scaling, no screen truncates or overflows" — a fixed
 * font size on the alarm title or button labels WILL overflow at max Huawei font scaling.
 */
@Composable
fun AutoSizeText(
    text: String,
    modifier: Modifier = Modifier,
    style: TextStyle = LocalTextStyle.current,
    maxFontSize: TextUnit = style.fontSize,
    minFontSize: TextUnit = 16.sp,
    maxLines: Int = 2,
    textAlign: TextAlign? = null,
) {
    var fontSize by remember(text, maxFontSize) { mutableStateOf(maxFontSize) }
    var readyToDraw by remember(text, maxFontSize) { mutableStateOf(false) }

    Box(modifier = modifier, contentAlignment = Alignment.Center) {
        Text(
            text = text,
            style = style.copy(fontSize = fontSize),
            maxLines = maxLines,
            textAlign = textAlign,
            overflow = TextOverflow.Clip,
            softWrap = true,
            onTextLayout = { result ->
                if (!readyToDraw) {
                    if (result.hasVisualOverflow && fontSize > minFontSize) {
                        // TextUnit has a compareTo operator (so `>` above works) but does
                        // not implement Comparable<TextUnit>, so the generic maxOf() can't
                        // resolve for it — compare manually instead.
                        val shrunk = fontSize * 0.92f
                        fontSize = if (shrunk > minFontSize) shrunk else minFontSize
                    } else {
                        readyToDraw = true
                    }
                }
            },
        )
    }
}
