package cn.chiyaole.ui

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Divider
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.lifecycleScope
import cn.chiyaole.ChiYaoLeApp
import cn.chiyaole.alarm.AlarmScheduler
import cn.chiyaole.alarm.KeepAliveService
import cn.chiyaole.data.DoseEntity
import cn.chiyaole.data.ScheduleRepository
import android.widget.Toast
import cn.chiyaole.net.DeviceAuth
import cn.chiyaole.net.SyncWorker
import cn.chiyaole.ui.components.SecondaryButton
import cn.chiyaole.ui.theme.ChiYaoLeTheme
import cn.chiyaole.ui.theme.Dimens
import cn.chiyaole.ui.theme.PrimaryGreen
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale
import kotlinx.coroutines.launch

/** The elder's entry point. Deliberately just "today, and whether it's done" — every other
 * concern (setup, install checks, caregiver dashboard) lives outside this screen (spec's
 * three-deliverable split: large-print sheet / elder APK / caregiver web page). */
class HomeActivity : ComponentActivity() {
    private lateinit var repo: ScheduleRepository

    override fun onCreate(savedInstanceState: Bundle?) {
        installSplashScreen()
        super.onCreate(savedInstanceState)

        // ★ A doses-of-today screen has nothing to show for a device not yet attached to a
        // patient — send it to the formal pairing flow first (PairingActivity's own
        // docstring), before touching Room/WorkManager/AlarmManager at all.
        if (!DeviceAuth(this).isRegistered) {
            startActivity(Intent(this, PairingActivity::class.java))
            finish()
            return
        }

        repo = ScheduleRepository(this)

        KeepAliveService.start(this)
        lifecycleScope.launch { AlarmScheduler.rescheduleNext(this@HomeActivity) }
        // ★ Confirmed live: SyncWorker.enqueuePeriodic's 6-hour timer is set once ever
        // (ExistingPeriodicWorkPolicy.KEEP) and nothing else was pulling fresh data down —
        // a caregiver changing today's schedule and then having the elder open the app
        // could sit stale for hours. observeToday() below is a Room Flow, so a sync
        // landing new rows updates the UI on its own; no extra wiring needed here beyond
        // kicking the sync off.
        SyncWorker.enqueue(this)

        if (!PermissionSetupActivity.allStepsDone(this)) {
            startActivity(Intent(this, PermissionSetupActivity::class.java))
        }

        val (startOfDay, endOfDay) = todayRangeMillis()
        // Local storage hygiene, not a safety mechanism — cheap to run on every launch
        // (see ScheduleRepository.pruneOldDoses). Keeps yesterday's already-resolved
        // doses from piling up in the "今天" list forever.
        lifecycleScope.launch { repo.pruneOldDoses(startOfDay) }

        val doctorButtonLabel = (application as ChiYaoLeApp).remoteConfigStore.current().copy.buttonDoctor

        setContent {
            ChiYaoLeTheme {
                val doses by repo.observeToday(startOfDay, endOfDay).collectAsState(initial = emptyList())
                HomeScreen(
                    doses = doses,
                    doctorButtonLabel = doctorButtonLabel,
                    onOpenSetup = { startActivity(Intent(this, PermissionSetupActivity::class.java)) },
                    onOpenDoctorView = { startActivity(Intent(this, DoctorViewActivity::class.java)) },
                    onAskQuestion = { startActivity(Intent(this, QaActivity::class.java)) },
                    onRefresh = {
                        SyncWorker.enqueue(this)
                        Toast.makeText(this, "正在同步…", Toast.LENGTH_SHORT).show()
                    },
                )
            }
        }
    }

    private fun todayRangeMillis(): Pair<Long, Long> {
        val cal = Calendar.getInstance()
        cal.set(Calendar.HOUR_OF_DAY, 0)
        cal.set(Calendar.MINUTE, 0)
        cal.set(Calendar.SECOND, 0)
        cal.set(Calendar.MILLISECOND, 0)
        val start = cal.timeInMillis
        return start to (start + 24 * 60 * 60 * 1000L)
    }
}

@Composable
private fun HomeScreen(
    doses: List<DoseEntity>,
    doctorButtonLabel: String,
    onOpenSetup: () -> Unit,
    onOpenDoctorView: () -> Unit,
    onAskQuestion: () -> Unit,
    onRefresh: () -> Unit,
) {
    Scaffold { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(Dimens.screenPadding),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(text = "今天", fontSize = Dimens.primaryTextSp, fontWeight = FontWeight.Bold)
                Row {
                    TextButton(onClick = onRefresh) {
                        Text(text = "刷新", fontSize = Dimens.minTextSp)
                    }
                    TextButton(onClick = onOpenDoctorView) {
                        Text(text = doctorButtonLabel, fontSize = Dimens.minTextSp)
                    }
                    TextButton(onClick = onOpenSetup) {
                        Text(text = "设置", fontSize = Dimens.minTextSp)
                    }
                }
            }

            SecondaryButton(
                text = "🎤 问一问",
                onClick = onAskQuestion,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = Dimens.buttonSpacing),
            )

            if (doses.isEmpty()) {
                Text(
                    text = "今天没有安排",
                    fontSize = Dimens.minTextSp,
                    modifier = Modifier.padding(top = Dimens.screenPadding),
                )
            } else {
                LazyColumn(
                    contentPadding = PaddingValues(vertical = Dimens.buttonSpacing),
                    verticalArrangement = Arrangement.spacedBy(Dimens.buttonSpacing),
                ) {
                    items(doses) { dose -> DoseRow(dose) }
                }
            }
        }
    }
}

@Composable
private fun DoseRow(dose: DoseEntity) {
    Surface {
        Column(modifier = Modifier.fillMaxWidth().padding(vertical = 12.dp)) {
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(text = timeFormat.format(Date(dose.scheduledAtMillis)), fontSize = Dimens.minTextSp)
                Text(text = stateLabel(dose.state), fontSize = Dimens.minTextSp, color = PrimaryGreen)
            }
            Text(text = dose.genericName, fontSize = Dimens.minTextSp)
            Divider(modifier = Modifier.padding(top = 8.dp))
        }
    }
}

private fun stateLabel(state: String): String = when (state) {
    "confirmed" -> "已吃"
    "snoozed" -> "等会儿吃"
    "skipped" -> "不吃"
    "missed" -> "没确认"
    else -> "待吃"
}

private val timeFormat = SimpleDateFormat("HH:mm", Locale.CHINA)
