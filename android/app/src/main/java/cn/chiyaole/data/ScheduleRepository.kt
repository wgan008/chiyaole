package cn.chiyaole.data

import android.content.Context
import java.util.UUID

/**
 * The single point of access to on-device state. Fully functional offline (spec §1: "★
 * Fully functional offline; only reporting is deferred") — every method here reads/writes
 * Room only. Uploading [ConfirmationEventEntity] rows is [cn.chiyaole.net.SyncWorker]'s job,
 * not this class's.
 */
class ScheduleRepository(context: Context) {
    private val db = AppDatabase.get(context)
    private val doseDao = db.doseDao()
    private val eventDao = db.confirmationEventDao()

    suspend fun replaceSchedule(doses: List<DoseEntity>) = doseDao.upsertAll(doses)

    /** See DoseDao.deleteStalePending: purges local pending doses the server has dropped
     * from the synced window (stopped medication, edited schedule) so a stale alarm can't
     * keep ringing. */
    suspend fun purgeStalePending(sinceMillis: Long, keepIds: List<String>) =
        doseDao.deleteStalePending(sinceMillis, keepIds)

    suspend fun dose(doseId: String): DoseEntity? = doseDao.getById(doseId)

    suspend fun nextPendingAfter(afterMillis: Long): DoseEntity? = doseDao.nextPendingAfter(afterMillis)

    suspend fun pendingSince(sinceMillis: Long): List<DoseEntity> = doseDao.pendingSince(sinceMillis)

    suspend fun markMissed(dose: DoseEntity) = doseDao.update(dose.copy(state = "missed"))

    /** Drops doses scheduled before [beforeMillis] — local storage hygiene, not a safety
     * mechanism (real "was this ever confirmed" history lives server-side via synced
     * ConfirmationEvent rows, spec §5). Safe to call on every app launch. */
    suspend fun pruneOldDoses(beforeMillis: Long) = doseDao.deleteBefore(beforeMillis)

    fun observeToday(startOfDayMillis: Long, endOfDayMillis: Long) =
        doseDao.observeBetween(startOfDayMillis, endOfDayMillis)

    /**
     * Records a tap. Local write only, completes before the screen turns off (spec §1's
     * key data flow) — [cn.chiyaole.net.SyncWorker] is what later uploads it.
     */
    suspend fun recordConfirmation(
        dose: DoseEntity,
        action: String,
        skipReason: String?,
        alarmFiredAtMillis: Long,
        tappedAtMillis: Long,
        dwellMs: Int?,
        ringIndex: Int,
        source: String,
    ) {
        val newState = when (action) {
            "taken" -> "confirmed"
            "snooze" -> "snoozed"
            "skip" -> "skipped"
            else -> dose.state
        }
        doseDao.update(dose.copy(state = newState))
        eventDao.insert(
            ConfirmationEventEntity(
                id = UUID.randomUUID().toString(),
                doseId = dose.doseId,
                action = action,
                skipReason = skipReason,
                alarmFiredAtMillis = alarmFiredAtMillis,
                tappedAtMillis = tappedAtMillis,
                latencyMs = (tappedAtMillis - alarmFiredAtMillis).toInt(),
                dwellMs = dwellMs,
                ringIndex = ringIndex,
                source = source,
                syncedAtMillis = null,
            )
        )
    }

    suspend fun unsyncedEvents(): List<ConfirmationEventEntity> = eventDao.unsynced()

    suspend fun markSynced(ids: List<String>) {
        if (ids.isEmpty()) return
        eventDao.markSynced(ids, System.currentTimeMillis())
    }
}
