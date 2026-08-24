package cn.chiyaole.ui

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import cn.chiyaole.data.DoseEntity
import cn.chiyaole.data.ScheduleRepository
import cn.chiyaole.net.DeviceAuth
import cn.chiyaole.net.DoctorViewDoseDto
import cn.chiyaole.net.DoctorViewMedicationDto
import cn.chiyaole.net.DoctorViewOut
import cn.chiyaole.net.NetworkModule
import cn.chiyaole.ui.theme.ChiYaoLeTheme
import cn.chiyaole.ui.theme.Dimens
import cn.chiyaole.ui.theme.MutedText
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * "Show the doctor": one tap in the clinic, the phone is handed over full-screen (README
 * "Three deliverables"). ★ Transcribe / compare / enlarge only — this screen must never
 * phrase a recommendation, only display what was recorded (product boundary #1).
 *
 * Calls the real GET /api/doctor-view/{patient_id} (spec §6.2) for the server-computed
 * regimen + today view. Falls back to the local Room cache (the old offline-only behaviour)
 * if the network call fails — this screen isn't alarm-critical, so a spinner-then-fallback
 * is fine, unlike AlarmActivity's "never make a network call" rule.
 */
class DoctorViewActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val repo = ScheduleRepository(this)
        val patientId = DeviceAuth(this).patientId
        val (start, end) = todayRangeMillis()

        setContent {
            ChiYaoLeTheme {
                var remote by remember { mutableStateOf<DoctorViewOut?>(null) }
                var loadFailed by remember { mutableStateOf(false) }
                val localDoses by repo.observeToday(start, end).collectAsState(initial = emptyList())

                LaunchedEffect(patientId) {
                    if (patientId == null) {
                        loadFailed = true
                        return@LaunchedEffect
                    }
                    val result = withContext(Dispatchers.IO) {
                        runCatching { NetworkModule.api(this@DoctorViewActivity).doctorView(patientId) }
                    }
                    remote = result.getOrNull()
                    loadFailed = result.isFailure
                }

                Scaffold { padding ->
                    Column(
                        modifier = Modifier.fillMaxSize().padding(padding).padding(Dimens.screenPadding),
                        verticalArrangement = Arrangement.spacedBy(Dimens.buttonSpacing),
                    ) {
                        TextButton(onClick = { finish() }) {
                            Text(text = "‹ 返回", fontSize = Dimens.minTextSp)
                        }
                        Text(text = "今天的用药情况", fontSize = Dimens.primaryTextSp, fontWeight = FontWeight.Bold)
                        val out = remote
                        if (out != null) {
                            DoctorViewContent(out)
                        } else {
                            if (loadFailed) {
                                Text(text = "网络不通，显示本机记录", fontSize = Dimens.minTextSp, color = MutedText)
                            }
                            LazyColumn { items(localDoses) { dose -> DoctorDoseRow(dose) } }
                        }
                    }
                }
            }
        }
    }

    private fun todayRangeMillis(): Pair<Long, Long> {
        val cal = Calendar.getInstance()
        cal.set(Calendar.HOUR_OF_DAY, 0); cal.set(Calendar.MINUTE, 0)
        cal.set(Calendar.SECOND, 0); cal.set(Calendar.MILLISECOND, 0)
        val start = cal.timeInMillis
        return start to (start + 24 * 60 * 60 * 1000L)
    }
}

@Composable
private fun DoctorViewContent(out: DoctorViewOut) {
    LazyColumn {
        items(out.medications) { med -> DoctorMedicationRow(med) }
        items(out.today) { dose -> DoctorRemoteDoseRow(dose) }
    }
}

@Composable
private fun DoctorMedicationRow(med: DoctorViewMedicationDto) {
    val strength = if (med.strength_value != null) "${med.strength_value}${med.strength_unit ?: ""}" else ""
    Text(
        text = "${med.generic_name} $strength  ${med.timing_note ?: ""}",
        fontSize = Dimens.minTextSp,
    )
}

@Composable
private fun DoctorRemoteDoseRow(dose: DoctorViewDoseDto) {
    Text(
        text = "${isoTime(dose.scheduled_at)}  ${dose.medication}  ${stateLabelFor(dose.state)}",
        fontSize = Dimens.minTextSp,
    )
}

@Composable
private fun DoctorDoseRow(dose: DoseEntity) {
    Text(
        text = "${timeFormat.format(Date(dose.scheduledAtMillis))}  ${dose.genericName}  ${stateLabelFor(dose.state)}",
        fontSize = Dimens.minTextSp,
    )
}

private fun stateLabelFor(state: String): String = when (state) {
    "confirmed" -> "已吃"
    "snoozed" -> "推迟"
    "skipped" -> "未吃"
    "missed" -> "未确认"
    else -> "待吃"
}

private fun isoTime(iso: String): String = runCatching {
    timeFormat.format(Date(java.time.OffsetDateTime.parse(iso).toInstant().toEpochMilli()))
}.getOrDefault(iso)

private val timeFormat = SimpleDateFormat("HH:mm", Locale.CHINA)
