package cn.chiyaole.alarm

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.util.Log
import cn.chiyaole.data.DoseEntity
import cn.chiyaole.data.ScheduleRepository
import cn.chiyaole.util.RemoteConfig

const val EXTRA_DOSE_ID = "dose_id"
const val EXTRA_RING_INDEX = "ring_index"
const val EXTRA_SCHEDULED_AT_MILLIS = "scheduled_at_millis"

/**
 * Layer 1 of the three-layer keep-alive defence (spec §4.1). Only one exact alarm is ever
 * outstanding at a time — [rescheduleNext] scans all cached pending doses, picks the
 * earliest not-yet-passed ring across all of them, and schedules exactly that one. This
 * makes recovery trivial: BootReceiver and every AlarmReceiver firing just call
 * [rescheduleNext] again rather than maintaining a set of N scheduled alarms that could
 * drift out of sync with what's in Room.
 */
object AlarmScheduler {
    private const val TAG = "AlarmScheduler"
    private const val REQUEST_CODE = 4200

    /**
     * The dual-path form spec §3.4-① makes mandatory: USE_EXACT_ALARM (declared in the
     * manifest) is a normal permission and should make this true unconditionally from API
     * 33, but the runtime check is the safety net — devices/ROMs are not always faithful to
     * the platform contract. Below API 31, SCHEDULE_EXACT_ALARM is pre-granted, so exact
     * alarms always work without asking.
     */
    fun canScheduleExact(context: Context): Boolean {
        if (Build.VERSION.SDK_INT < 31) return true
        val alarmManager = context.getSystemService(AlarmManager::class.java)
        return alarmManager.canScheduleExactAlarms()
    }

    /** Only reachable on Android 12+ when [canScheduleExact] is false — see
     * PermissionSetupActivity, which is the only place this should be launched from. */
    fun exactAlarmSettingsIntent(context: Context): Intent =
        Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM, Uri.parse("package:${context.packageName}"))

    suspend fun rescheduleNext(context: Context) {
        val repo = ScheduleRepository(context)
        val config = (context.applicationContext as cn.chiyaole.ChiYaoLeApp)
            .remoteConfigStore.current().alarm
        val now = System.currentTimeMillis()

        val candidates = repo.pendingSince(now - MAX_LOOKBACK_MS)
        val target = candidates
            .mapNotNull { dose -> nextRingFor(dose, now, config.ringSeriesMs) }
            .minByOrNull { it.triggerAtMillis }

        if (target == null) {
            cancel(context)
            Log.i(TAG, "no upcoming dose to schedule")
            return
        }
        scheduleExact(context, target)
    }

    /** Used by AlarmReceiver to defer a due dose without disturbing an in-progress call
     * (spec §4.4 DoD) — reschedules the SAME ring a short delay later, not the next ring. */
    fun deferByMillis(context: Context, doseId: String, ringIndex: Int, scheduledAtMillis: Long, delayMs: Long) {
        scheduleExact(
            context,
            RingTarget(doseId, ringIndex, System.currentTimeMillis() + delayMs, scheduledAtMillis),
        )
    }

    fun cancel(context: Context) {
        val alarmManager = context.getSystemService(AlarmManager::class.java)
        alarmManager.cancel(pendingIntent(context, RingTarget("", 0, 0, 0)))
    }

    /** internal, not private: exercised directly by AlarmSchedulerTest (spec §8.2 style —
     * pure ring-series math, no Android framework dependency, testable off-device). */
    internal fun nextRingFor(dose: DoseEntity, nowMillis: Long, ringOffsetsMs: List<Long>): RingTarget? =
        ringOffsetsMs.withIndex()
            .map { (i, offset) -> (i + 1) to (dose.scheduledAtMillis + offset) }
            .firstOrNull { (_, triggerAt) -> triggerAt > nowMillis }
            ?.let { (ringIndex, triggerAt) ->
                RingTarget(dose.doseId, ringIndex, triggerAt, dose.scheduledAtMillis)
            }

    private fun scheduleExact(context: Context, target: RingTarget) {
        val alarmManager = context.getSystemService(AlarmManager::class.java)
        val pendingIntent = pendingIntent(context, target)
        // setExactAndAllowWhileIdle pierces Doze (spec §4.1 layer 1); available since API 23,
        // well below minSdk 26.
        alarmManager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, target.triggerAtMillis, pendingIntent)
        Log.i(TAG, "scheduled dose=${target.doseId} ring=${target.ringIndex} at=${target.triggerAtMillis}")
    }

    private fun pendingIntent(context: Context, target: RingTarget): PendingIntent {
        val intent = Intent(context, AlarmReceiver::class.java).apply {
            putExtra(EXTRA_DOSE_ID, target.doseId)
            putExtra(EXTRA_RING_INDEX, target.ringIndex)
            putExtra(EXTRA_SCHEDULED_AT_MILLIS, target.scheduledAtMillis)
        }
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        return PendingIntent.getBroadcast(context, REQUEST_CODE, intent, flags)
    }

    internal data class RingTarget(
        val doseId: String,
        val ringIndex: Int,
        val triggerAtMillis: Long,
        val scheduledAtMillis: Long,
    )

    /** How far back a dose can still be considered "upcoming" — covers the last ring
     * offset (30 min) plus slack; anything older is left for the missed-dose path instead
     * of being re-armed. */
    private const val MAX_LOOKBACK_MS = 40 * 60 * 1000L
}
