package cn.chiyaole.alarm

import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import cn.chiyaole.ChiYaoLeApp
import cn.chiyaole.R
import cn.chiyaole.data.ScheduleRepository
import cn.chiyaole.net.DeviceAuth
import cn.chiyaole.ui.AlarmActivity
import cn.chiyaole.util.CallStateGuard
import cn.chiyaole.util.fillTemplate
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

private const val CALL_DEFER_MS = 60_000L

/**
 * Fired by AlarmManager. Per spec §1: `AlarmManager → FullScreenIntent → AlarmActivity`.
 * Does the minimum synchronous work possible and hands off via [goAsync] — a
 * BroadcastReceiver has only a few seconds before the OS may kill it (spec §4 territory:
 * an alarm that silently fails here is exactly the failure mode this whole layer defends
 * against).
 */
class AlarmReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val doseId = intent.getStringExtra(EXTRA_DOSE_ID) ?: return
        val ringIndex = intent.getIntExtra(EXTRA_RING_INDEX, 1)
        val scheduledAtMillis = intent.getLongExtra(EXTRA_SCHEDULED_AT_MILLIS, System.currentTimeMillis())
        val alarmFiredAtMillis = System.currentTimeMillis()

        val pendingResult = goAsync()
        CoroutineScope(Dispatchers.IO).launch {
            try {
                handle(context, doseId, ringIndex, scheduledAtMillis, alarmFiredAtMillis)
            } finally {
                pendingResult.finish()
            }
        }
    }

    private suspend fun handle(
        context: Context,
        doseId: String,
        ringIndex: Int,
        scheduledAtMillis: Long,
        alarmFiredAtMillis: Long,
    ) {
        val repo = ScheduleRepository(context)
        val dose = repo.dose(doseId)

        // The dose may have been confirmed from HomeActivity's todo card between when this
        // ring was armed and when it fired — nothing to show, just arm the next one.
        if (dose == null || dose.state != "pending") {
            AlarmScheduler.rescheduleNext(context)
            return
        }

        val config = (context.applicationContext as ChiYaoLeApp).remoteConfigStore.current()
        if (CallStateGuard.isInCall(context) && config.alarm.deferDuringCall) {
            // ★ Never interrupts a call (spec §4.4 DoD). Same ring, tried again shortly —
            // does NOT advance to the next ring or touch rescheduleNext's global pick.
            AlarmScheduler.deferByMillis(context, doseId, ringIndex, scheduledAtMillis, CALL_DEFER_MS)
            return
        }

        showFullScreenAlarm(context, doseId, ringIndex, scheduledAtMillis, alarmFiredAtMillis, config)
        AlarmScheduler.rescheduleNext(context)
    }

    private fun showFullScreenAlarm(
        context: Context,
        doseId: String,
        ringIndex: Int,
        scheduledAtMillis: Long,
        alarmFiredAtMillis: Long,
        config: cn.chiyaole.util.RemoteConfig,
    ) {
        val fullScreenIntent = Intent(context, AlarmActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            putExtra(EXTRA_DOSE_ID, doseId)
            putExtra(EXTRA_RING_INDEX, ringIndex)
            putExtra(EXTRA_SCHEDULED_AT_MILLIS, scheduledAtMillis)
            putExtra(AlarmActivity.EXTRA_ALARM_FIRED_AT_MILLIS, alarmFiredAtMillis)
        }
        val fullScreenPendingIntent = PendingIntent.getActivity(
            context,
            doseId.hashCode(),
            fullScreenIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val name = DeviceAuth(context).patientDisplayName ?: ELDER_NAME_FALLBACK
        val title = config.copy.alarmTitleFmt.fillTemplate("name" to name)
        val notification = NotificationCompat.Builder(context, ChiYaoLeApp.CHANNEL_ALARM)
            .setSmallIcon(R.drawable.ic_stat_notify)
            .setContentTitle(title)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setFullScreenIntent(fullScreenPendingIntent, true)
            .setContentIntent(fullScreenPendingIntent)
            .setAutoCancel(true)
            .setOngoing(true)
            .build()

        val manager = context.getSystemService(NotificationManager::class.java)
        manager.notify(doseId.hashCode(), notification)
    }

    companion object {
        // DeviceAuth.patientDisplayName is fetched once at registration
        // (DeviceRegisterOut.display_name) and cached locally. This fallback only fires
        // if an alarm somehow rings before the device has ever registered — shouldn't
        // happen in practice (no schedule exists to alarm from, either), but "您" is a
        // safe, still-grammatical substitute rather than a crash or a blank title.
        private const val ELDER_NAME_FALLBACK = "您"
    }
}
