package cn.chiyaole.ui

import android.app.KeyguardManager
import android.graphics.BitmapFactory
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.Image
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.lifecycleScope
import cn.chiyaole.ChiYaoLeApp
import cn.chiyaole.alarm.AlarmScheduler
import cn.chiyaole.alarm.EXTRA_DOSE_ID
import cn.chiyaole.alarm.EXTRA_RING_INDEX
import cn.chiyaole.data.DoseEntity
import cn.chiyaole.data.ScheduleRepository
import cn.chiyaole.net.DeviceAuth
import cn.chiyaole.net.SyncWorker
import cn.chiyaole.ui.components.AutoSizeText
import cn.chiyaole.ui.components.BigButton
import cn.chiyaole.ui.components.SecondaryButton
import cn.chiyaole.ui.theme.ChiYaoLeTheme
import cn.chiyaole.ui.theme.Dimens
import cn.chiyaole.ui.theme.HotBg
import cn.chiyaole.ui.theme.HotBorder
import cn.chiyaole.ui.theme.InkText2
import cn.chiyaole.ui.theme.MutedText
import cn.chiyaole.ui.theme.PaperBg
import cn.chiyaole.ui.theme.PrimaryGreen
import cn.chiyaole.ui.theme.SecondaryBg
import cn.chiyaole.ui.theme.SecondaryBorder
import cn.chiyaole.ui.theme.White
import cn.chiyaole.util.RemoteConfig
import cn.chiyaole.util.TtsHelper
import cn.chiyaole.util.fillTemplate
import java.util.Calendar
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * Full-screen alarm UI — the one screen the whole product exists to reliably show (spec
 * §1: `AlarmManager → FullScreenIntent → AlarmActivity`).
 *
 * ★ onCreate makes NO network calls (spec §3.4-③): the dose photo is already on disk
 * ([DoseEntity.photoLocalPath], downloaded when the schedule was synced) and the copy
 * comes from [cn.chiyaole.util.RemoteConfigStore]'s local cache, not a live fetch.
 *
 * Visuals follow docs/design/02_Wireframe.html A1-A4 (老人端 ring screen): time+medicine
 * name in place of a generic title, and hierarchy between 吃了 and 等会儿吃/这次不吃 built
 * from SIZE (Dimens.buttonMinHeight vs secondaryButtonMinHeight) rather than from
 * color-coding — the wireframe is explicit that color must never be the only signal.
 *
 * ★ Deliberately has no voice Q&A (wireframe C1-C4) — hold-to-speak was built, wired end to
 * end, and then removed: it duplicated WeChat's own instant messaging, and the platform
 * constraints around it (no push channel to the elder device, no push channel to the
 * caregiver either beyond a text-only PushPlus link, 15-minute poll floor) meant it could
 * not actually replace WeChat well enough to be worth the surface area.
 */
class AlarmActivity : ComponentActivity() {
    private lateinit var repo: ScheduleRepository
    private lateinit var tts: TtsHelper

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        showOverLockScreen()

        val doseId = intent.getStringExtra(EXTRA_DOSE_ID)
        if (doseId == null) {
            finish()
            return
        }
        val ringIndex = intent.getIntExtra(EXTRA_RING_INDEX, 1)
        val alarmFiredAtMillis = intent.getLongExtra(EXTRA_ALARM_FIRED_AT_MILLIS, System.currentTimeMillis())
        val shownAtMillis = System.currentTimeMillis()

        repo = ScheduleRepository(this)
        val config = (application as ChiYaoLeApp).remoteConfigStore.current()
        // Cached at device registration (DeviceRegisterOut.display_name) — a local
        // SharedPreferences read, not a network call (spec §3.4-③).
        val patientName = DeviceAuth(this).patientDisplayName ?: "您"
        tts = TtsHelper(this, config.tts)

        // "Screen lights BEFORE speech" (spec §3.4-③) — the delay is fixed, not detected
        // from a real frame callback, matching remote_config.json's own description of it.
        // The spoken announcement still uses the full "{name}，该吃药了" template even
        // though the on-screen title no longer repeats it verbatim (wireframe A1 shows
        // time + medicine name instead) — TTS is the one place this copy still lives.
        Handler(Looper.getMainLooper()).postDelayed({
            tts.speak(config.copy.alarmTitleFmt.fillTemplate("name" to patientName))
        }, config.alarm.screenOnToSpeechDelayMs)

        setContent {
            ChiYaoLeTheme {
                var dose by remember { mutableStateOf<DoseEntity?>(null) }
                LaunchedEffect(doseId) { dose = repo.dose(doseId) }

                AlarmScreen(
                    dose = dose,
                    config = config,
                    onRecord = { action, skipReason ->
                        lifecycleScope.launch {
                            val d = dose ?: return@launch
                            repo.recordConfirmation(
                                dose = d,
                                action = action,
                                skipReason = skipReason,
                                alarmFiredAtMillis = alarmFiredAtMillis,
                                tappedAtMillis = System.currentTimeMillis(),
                                dwellMs = (System.currentTimeMillis() - shownAtMillis).toInt(),
                                ringIndex = ringIndex,
                                source = "alarm",
                            )
                            AlarmScheduler.rescheduleNext(this@AlarmActivity)
                            SyncWorker.enqueue(this@AlarmActivity)
                        }
                    },
                    onFinish = {
                        // Screen off immediately, does NOT wait for the coroutine/network
                        // (spec §1 "key data flow").
                        tts.shutdown()
                        finish()
                    },
                )
            }
        }
    }

    private fun showOverLockScreen() {
        if (Build.VERSION.SDK_INT >= 27) {
            setShowWhenLocked(true)
            setTurnScreenOn(true)
        } else {
            @Suppress("DEPRECATION")
            window.addFlags(
                WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
                    WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON or
                    WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON or
                    WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD,
            )
        }
        val keyguardManager = getSystemService(KeyguardManager::class.java)
        keyguardManager?.requestDismissKeyguard(this, null)
    }

    override fun onDestroy() {
        super.onDestroy()
        if (::tts.isInitialized) tts.shutdown()
    }

    companion object {
        const val EXTRA_ALARM_FIRED_AT_MILLIS = "alarm_fired_at_millis"
    }
}

/** Local-only UI state machine layered on top of the single [ScreenState.Ringing] moment —
 * none of this is persisted; [AlarmActivity.onCreate] wires [ScreenState.Taken] /
 * [ScreenState.Snoozed] to record the confirmation up front (spec §1: write before the
 * screen turns off) and only delays the *visual* dismissal, matching wireframe A2/A3's
 * ~2-3s feedback beat before the screen releases. */
private sealed interface ScreenState {
    data object Ringing : ScreenState
    data object Taken : ScreenState
    data object Snoozed : ScreenState
    data object SkipPicker : ScreenState
}

private data class SkipReason(val label: String, val value: String, val hot: Boolean)

private val SKIP_REASONS = listOf(
    SkipReason("我不在家", "away", hot = false),
    SkipReason("药吃完了", "out_of_stock", hot = false),
    SkipReason("今天不舒服", "unwell", hot = true),
    SkipReason("医生说停了", "doctor_stopped", hot = true),
)

@Composable
private fun AlarmScreen(
    dose: DoseEntity?,
    config: RemoteConfig,
    onRecord: (action: String, skipReason: String?) -> Unit,
    onFinish: () -> Unit,
) {
    var screenState by remember { mutableStateOf<ScreenState>(ScreenState.Ringing) }

    LaunchedEffect(screenState) {
        when (screenState) {
            ScreenState.Taken -> {
                delay(2000)
                onFinish()
            }
            ScreenState.Snoozed -> {
                delay(2500)
                onFinish()
            }
            else -> Unit
        }
    }

    Scaffold(containerColor = PaperBg) { padding ->
        when (screenState) {
            ScreenState.Ringing -> RingingContent(
                dose = dose,
                config = config,
                modifier = Modifier.padding(padding),
                onTaken = {
                    onRecord("taken", null)
                    screenState = ScreenState.Taken
                },
                onSnooze = {
                    onRecord("snooze", null)
                    screenState = ScreenState.Snoozed
                },
                onSkip = { screenState = ScreenState.SkipPicker },
            )
            ScreenState.Taken -> CenteredMessage(text = "✓ 知道了", modifier = Modifier.padding(padding))
            ScreenState.Snoozed -> CenteredMessage(text = "好，等会儿再叫你", modifier = Modifier.padding(padding))
            ScreenState.SkipPicker -> SkipReasonPicker(
                modifier = Modifier.padding(padding),
                onReasonChosen = { reason ->
                    onRecord("skip", reason)
                    onFinish()
                },
                onBack = { screenState = ScreenState.Ringing },
            )
        }
    }
}

@Composable
private fun RingingContent(
    dose: DoseEntity?,
    config: RemoteConfig,
    onTaken: () -> Unit,
    onSnooze: () -> Unit,
    onSkip: () -> Unit,
    modifier: Modifier = Modifier,
) {
    // ★ spec §3.4-④: "layout must survive 1.75x system font scaling ... never truncate or
    // overflow" — a fixed-height Column here WILL clip the last button off-screen once the
    // photo + two AutoSizeText blocks push past viewport height. verticalScroll makes
    // overflow scrollable instead of clipped; it never engages on a screen tall enough to
    // fit everything.
    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(Dimens.screenPadding),
        verticalArrangement = Arrangement.spacedBy(Dimens.buttonSpacing),
    ) {
        AutoSizeText(
            text = naturalTimeOf(dose?.scheduledAtMillis),
            maxFontSize = Dimens.primaryTextSp,
            minFontSize = Dimens.minTextSp,
            maxLines = 1,
            textAlign = TextAlign.Center,
            style = TextStyle(color = InkText2, fontWeight = FontWeight.Bold),
            modifier = Modifier.fillMaxWidth(),
        )

        dose?.genericName?.let {
            AutoSizeText(
                text = it,
                maxFontSize = Dimens.primaryTextSp,
                minFontSize = Dimens.minTextSp,
                maxLines = 2,
                textAlign = TextAlign.Center,
                style = TextStyle(color = PrimaryGreen, fontWeight = FontWeight.Bold),
                modifier = Modifier.fillMaxWidth(),
            )
        }

        // Real usage instruction from the caregiver's confirmed regimen (e.g. "饭后服
        // 用") — NOT a fabricated dosage-form unit. dose_per_take has no unit in the
        // data model (see server/agent/types.py Medication), so we deliberately don't
        // guess "片"/"粒"/etc. here (project-wide "never guess" rule).
        dose?.timingNote?.takeIf { it.isNotBlank() }?.let {
            Text(text = it, fontSize = Dimens.minTextSp, color = MutedText)
        }

        dose?.photoLocalPath?.let { path ->
            val bitmap = remember(path) { runCatching { BitmapFactory.decodeFile(path) }.getOrNull() }
            bitmap?.let {
                Image(
                    bitmap = it.asImageBitmap(),
                    contentDescription = null,
                    modifier = Modifier.fillMaxWidth().height(220.dp),
                )
            }
        }

        BigButton(
            text = config.copy.buttonTaken,
            backgroundColor = PrimaryGreen,
            contentColor = White,
            onClick = onTaken,
        )

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(Dimens.buttonSpacing),
        ) {
            SecondaryButton(
                text = config.copy.buttonSnooze,
                onClick = onSnooze,
                modifier = Modifier.weight(1f),
            )
            SecondaryButton(
                text = config.copy.buttonSkip,
                onClick = onSkip,
                modifier = Modifier.weight(1f),
            )
        }
    }
}

@Composable
private fun CenteredMessage(text: String, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier.fillMaxSize().padding(Dimens.screenPadding),
        verticalArrangement = Arrangement.Center,
    ) {
        AutoSizeText(
            text = text,
            maxFontSize = Dimens.primaryTextSp,
            minFontSize = Dimens.minTextSp,
            maxLines = 2,
            textAlign = TextAlign.Center,
            style = TextStyle(color = PrimaryGreen, fontWeight = FontWeight.Bold),
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

/** Wireframe A4: 这次不吃 always asks why before recording — a 2x2 grid, the two more
 * clinically-urgent reasons visually flagged (`.g.hot`, a warm red tint) so a caregiver
 * scanning history later can triage at a glance, plus a low-emphasis skip-out link for
 * "不说了" (records action=skip, skip_reason="unspecified" — never blocks the elder). */
@Composable
private fun SkipReasonPicker(
    onReasonChosen: (String) -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier.fillMaxSize().padding(Dimens.screenPadding),
        verticalArrangement = Arrangement.spacedBy(Dimens.buttonSpacing),
    ) {
        // ★ Distinct from "不说了" below — this records nothing at all, for the case where
        // 这次不吃 was tapped by mistake and the elder wants back to the ring screen intact.
        TextButton(onClick = onBack) {
            Text(text = "‹ 返回", fontSize = Dimens.minTextSp, color = MutedText)
        }

        Text(
            text = "为什么这次不吃？",
            fontSize = Dimens.minTextSp,
            fontWeight = FontWeight.Bold,
            color = InkText2,
        )

        LazyVerticalGrid(
            columns = GridCells.Fixed(2),
            horizontalArrangement = Arrangement.spacedBy(Dimens.buttonSpacing),
            verticalArrangement = Arrangement.spacedBy(Dimens.buttonSpacing),
            modifier = Modifier.weight(1f),
        ) {
            items(SKIP_REASONS) { reason ->
                Button(
                    onClick = { onReasonChosen(reason.value) },
                    modifier = Modifier.fillMaxWidth().aspectRatio(1.6f),
                    shape = RoundedCornerShape(12.dp),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = if (reason.hot) HotBg else SecondaryBg,
                        contentColor = InkText2,
                    ),
                    border = BorderStroke(1.5.dp, if (reason.hot) HotBorder else SecondaryBorder),
                ) {
                    AutoSizeText(
                        text = reason.label,
                        maxFontSize = Dimens.minTextSp,
                        minFontSize = 18.sp,
                        maxLines = 2,
                        style = TextStyle(fontWeight = FontWeight.Bold, color = InkText2),
                    )
                }
            }
        }

        TextButton(
            onClick = { onReasonChosen("unspecified") },
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text(text = "不说了 ›", fontSize = Dimens.minTextSp, color = MutedText)
        }
    }
}

/** "早上 8 点" style — matches wireframe A1's spoken-language time display. Falls back to
 * "现在" if the dose hasn't loaded from Room yet (LaunchedEffect race on first compose). */
private fun naturalTimeOf(scheduledAtMillis: Long?): String {
    if (scheduledAtMillis == null) return "现在"
    val cal = Calendar.getInstance().apply { timeInMillis = scheduledAtMillis }
    val hour = cal.get(Calendar.HOUR_OF_DAY)
    val minute = cal.get(Calendar.MINUTE)
    val period = when (hour) {
        in 0..4 -> "凌晨"
        in 5..8 -> "早上"
        in 9..10 -> "上午"
        in 11..12 -> "中午"
        in 13..17 -> "下午"
        else -> "晚上"
    }
    val hour12 = if (hour % 12 == 0) 12 else hour % 12
    val minutePart = when {
        minute == 0 -> "点"
        minute == 30 -> "点半"
        else -> "点${minute}分"
    }
    return "$period$hour12$minutePart"
}
