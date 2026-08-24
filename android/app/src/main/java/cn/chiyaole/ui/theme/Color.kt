package cn.chiyaole.ui.theme

import androidx.compose.ui.graphics.Color

// data/remote_config.json ui.colors / docs/design/05_Technical_Spec_EN.md "Visual rules".
// Color never carries information alone — every screen must still work in greyscale.
val PrimaryGreen = Color(0xFF0B6B33) // 7.4:1 against white, AAA
val BrandYellow = Color(0xFFFFD500)  // 15:1 against TrueBlack
val TrueBlack = Color(0xFF0A0A0A)
val SkipGrey = Color(0xFF5A5A5A)
val AlertRed = Color(0xFFB3261E)
val White = Color(0xFFFFFFFF)

// docs/design/02_Wireframe.html :root — secondary-button and muted-text palette. The
// wireframe deliberately keeps 等会儿吃/这次不吃 both muted (hierarchy via SIZE, not a
// third saturated color) — see BigButton.kt's SecondaryButton.
val SecondaryBg = Color(0xFFEEF1F4)     // --panel-ish, b-2 background
val SecondaryBorder = Color(0xFFC8CFD6) // --line2
val SecondaryText = Color(0xFF333A41)
val SkipTanBg = Color(0xFFFDF4E7)       // b-2.w background
val SkipTanBorder = Color(0xFFE3C795)
val SkipTanText = Color(0xFF8A5A00)
val MutedText = Color(0xFF7B838C)       // --mute
val InkText2 = Color(0xFF40474F)        // --ink2
val PaperBg = Color(0xFFFCFCFD)         // --paper, the default (light) screen background
val HotBg = Color(0xFFFBEEED)           // .g.hot — high-urgency skip-reason tile
val HotBorder = Color(0xFFE5B6B1)
