package cn.chiyaole.net

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import cn.chiyaole.ChiYaoLeApp
import cn.chiyaole.alarm.AlarmScheduler
import cn.chiyaole.data.ConfirmationEventEntity
import cn.chiyaole.data.DoseEntity
import cn.chiyaole.data.ScheduleRepository
import java.io.File
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request

/**
 * "WorkManager syncs to server in background (retries up to 7 days)" (spec §1). One worker,
 * three jobs, in order: drain the offline event outbox, pull the next 7 days of schedule
 * (caching each dose photo to disk — never done from AlarmActivity, spec §3.4-③), and
 * refresh remote_config.json at most once a day.
 *
 * The 7-day retry window isn't a single backoff timer; it falls out of running this worker
 * both on-demand (after every button tap, [enqueue]) and periodically ([enqueuePeriodic]) —
 * an event that fails to upload today gets picked up again on tomorrow's periodic run.
 */
class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val auth = DeviceAuth(applicationContext)
        if (!auth.isRegistered) return@withContext Result.success()

        val repo = ScheduleRepository(applicationContext)
        val api = NetworkModule.api(applicationContext)

        try {
            uploadUnsyncedEvents(repo, api)
            mergeSchedule(applicationContext, repo, api)
            // ★ Deliberately its own try/catch, not part of the outer one: config refresh
            // is explicitly best-effort by design (RemoteConfigStore falls back to the
            // baked-in default when it "has never fetched successfully" — see its
            // docstring) but was wired so ANY failure here — including the 404 from
            // /api/config not existing yet server-side — marked the WHOLE sync as
            // Result.retry(), even though the schedule (the part that actually matters)
            // had already synced successfully. A soft feature must not be able to block a
            // hard one.
            try {
                maybeRefreshConfig(applicationContext, api)
            } catch (t: Throwable) {
                android.util.Log.w("SyncWorker", "config refresh failed, using cached/default", t)
            }
            AlarmScheduler.rescheduleNext(applicationContext)
            Result.success()
        } catch (t: Throwable) {
            // ★ Was a bare `Result.retry()` with no logging — a real failure here (e.g. a
            // date-parsing bug, confirmed live) looked identical to a transient network
            // blip, retrying forever with nothing in logcat to explain why. This is a
            // background worker; a Log line is the only diagnostic trail it can leave.
            android.util.Log.e("SyncWorker", "sync failed, will retry", t)
            Result.retry()
        }
    }

    private suspend fun uploadUnsyncedEvents(repo: ScheduleRepository, api: ApiService) {
        val unsynced = repo.unsyncedEvents()
        if (unsynced.isEmpty()) return
        api.postEvents(EventsRequest(unsynced.map { it.toDto() }))
        // POST /api/events is idempotent by client id (spec §6.2) — safe to mark all synced
        // even if some were duplicates the server had already seen from a prior partial run.
        repo.markSynced(unsynced.map { it.id })
    }

    /** Only inserts doses the device has never seen — never overwrites local state.
     * ScheduleItem carries no `state` field on the wire; the device is the state authority
     * once a dose exists locally (confirmations happen client-first, spec §1). Still purges
     * local *pending* doses the server no longer lists in this window (see
     * ScheduleRepository.purgeStalePending) — a stopped or rescheduled medication must not
     * keep ringing at a time the caregiver already changed.
     *
     * `since` is local midnight, not "now": the caregiver can edit/stop a medication after
     * today's dose time has already passed but before the elder acted on it (still
     * `pending` server-side) — using "now" as the window floor would exclude that dose from
     * both the fetch and the purge, so the device would never learn it was deleted. */
    private suspend fun mergeSchedule(context: Context, repo: ScheduleRepository, api: ApiService) {
        val sinceMillis = startOfTodayMillis()
        val response = api.schedule(sinceMillis.toIso())
        val newDoses = mutableListOf<DoseEntity>()
        for (item in response.items) {
            if (repo.dose(item.dose_id) != null) continue
            val localPhotoPath = item.photo_url?.let { downloadAndCachePhoto(context, item.dose_id, it) }
            newDoses += DoseEntity(
                doseId = item.dose_id,
                medicationId = item.medication_id,
                scheduledAtMillis = item.scheduled_at.isoToMillis(),
                genericName = item.generic_name,
                dosePerTake = item.dose_per_take,
                timingNote = item.timing_note,
                photoLocalPath = localPhotoPath,
                state = "pending",
            )
        }
        if (newDoses.isNotEmpty()) repo.replaceSchedule(newDoses)
        repo.purgeStalePending(sinceMillis, response.items.map { it.dose_id })
    }

    private fun startOfTodayMillis(): Long {
        val cal = java.util.Calendar.getInstance()
        cal.set(java.util.Calendar.HOUR_OF_DAY, 0)
        cal.set(java.util.Calendar.MINUTE, 0)
        cal.set(java.util.Calendar.SECOND, 0)
        cal.set(java.util.Calendar.MILLISECOND, 0)
        return cal.timeInMillis
    }

    private fun downloadAndCachePhoto(context: Context, doseId: String, url: String): String? = runCatching {
        val client = OkHttpClient()
        val request = Request.Builder().url(url).build()
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                android.util.Log.w("SyncWorker", "photo fetch non-2xx for dose=$doseId url=$url code=${response.code}")
                return@runCatching null
            }
            val dir = File(context.filesDir, "photos").apply { mkdirs() }
            val file = File(dir, "$doseId.jpg")
            response.body?.byteStream()?.use { input -> file.outputStream().use { input.copyTo(it) } }
            file.absolutePath
        }
    }.onFailure {
        // ★ Was a bare .getOrNull() with no logging — confirmed live: BASE_URL pointed at
        // "localhost", unreachable from inside the emulator's network namespace, and this
        // failed completely silently. The alarm screen just showed no photo with no trail
        // explaining why. Failure here is expected/tolerable (AlarmActivity already
        // handles a null photoLocalPath gracefully) but must never be silent.
        android.util.Log.w("SyncWorker", "photo download failed for dose=$doseId url=$url", it)
    }.getOrNull()

    private suspend fun maybeRefreshConfig(context: Context, api: ApiService) {
        val prefs = context.getSharedPreferences("device_prefs", Context.MODE_PRIVATE)
        val lastFetch = prefs.getLong(KEY_CONFIG_LAST_FETCH, 0L)
        if (System.currentTimeMillis() - lastFetch < TimeUnit.DAYS.toMillis(1)) return
        val body = api.config().string()
        (context.applicationContext as ChiYaoLeApp).remoteConfigStore.save(body)
        prefs.edit().putLong(KEY_CONFIG_LAST_FETCH, System.currentTimeMillis()).apply()
    }

    companion object {
        private const val KEY_CONFIG_LAST_FETCH = "config_last_fetched_millis"
        private const val UNIQUE_WORK_NAME = "sync"
        private const val PERIODIC_WORK_NAME = "periodic_sync"

        private fun constraints() = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()

        /** Fire-and-forget after every button tap — best-effort prompt delivery, never
         * blocks the UI (spec §1: screen turns off before this even starts). */
        fun enqueue(context: Context) {
            val request = OneTimeWorkRequestBuilder<SyncWorker>()
                .setConstraints(constraints())
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 60, TimeUnit.SECONDS)
                .build()
            WorkManager.getInstance(context).enqueueUniqueWork(UNIQUE_WORK_NAME, ExistingWorkPolicy.REPLACE, request)
        }

        /** The 7-day retry floor: even if every on-demand attempt fails, this keeps trying. */
        fun enqueuePeriodic(context: Context) {
            val request = PeriodicWorkRequestBuilder<SyncWorker>(6, TimeUnit.HOURS)
                .setConstraints(constraints())
                .build()
            WorkManager.getInstance(context)
                .enqueueUniquePeriodicWork(PERIODIC_WORK_NAME, ExistingPeriodicWorkPolicy.KEEP, request)
        }

    }
}

private fun ConfirmationEventEntity.toDto(): EventIn = EventIn(
    id = id,
    dose_id = doseId,
    action = action,
    skip_reason = skipReason,
    alarm_fired_at = alarmFiredAtMillis.toIso(),
    tapped_at = tappedAtMillis.toIso(),
    latency_ms = latencyMs,
    dwell_ms = dwellMs,
    ring_index = ringIndex,
    source = source,
)
