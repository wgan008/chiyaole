package cn.chiyaole.data

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Update
import kotlinx.coroutines.flow.Flow

@Dao
interface DoseDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertAll(doses: List<DoseEntity>)

    @Update
    suspend fun update(dose: DoseEntity)

    @Query("SELECT * FROM doses WHERE doseId = :doseId")
    suspend fun getById(doseId: String): DoseEntity?

    /** Next pending dose strictly after [afterMillis] — what AlarmScheduler reschedules
     * towards after each ring or after a boot (spec §4.1 layer 1). */
    @Query(
        "SELECT * FROM doses WHERE scheduledAtMillis > :afterMillis AND state = 'pending' " +
            "ORDER BY scheduledAtMillis ASC LIMIT 1"
    )
    suspend fun nextPendingAfter(afterMillis: Long): DoseEntity?

    @Query(
        "SELECT * FROM doses WHERE scheduledAtMillis BETWEEN :startMillis AND :endMillis " +
            "ORDER BY scheduledAtMillis ASC"
    )
    fun observeBetween(startMillis: Long, endMillis: Long): Flow<List<DoseEntity>>

    @Query("SELECT * FROM doses WHERE scheduledAtMillis >= :sinceMillis ORDER BY scheduledAtMillis ASC")
    suspend fun allSince(sinceMillis: Long): List<DoseEntity>

    /** All still-pending doses whose scheduled time hasn't fallen fully off the ring
     * window — the candidate set AlarmScheduler picks the next wake-up from. */
    @Query(
        "SELECT * FROM doses WHERE state = 'pending' AND scheduledAtMillis >= :sinceMillis " +
            "ORDER BY scheduledAtMillis ASC"
    )
    suspend fun pendingSince(sinceMillis: Long): List<DoseEntity>

    @Query("DELETE FROM doses WHERE scheduledAtMillis < :beforeMillis")
    suspend fun deleteBefore(beforeMillis: Long)

    /** Drops local doses the server no longer knows about within the synced window — e.g.
     * a medication got stopped, or its schedule was edited, so the old Dose rows were
     * deleted server-side. Scoped to state = 'pending' only: never touches a dose the elder
     * has already acted on (spec: the device is the state authority for anything it's
     * already recorded — see SyncWorker.mergeSchedule's docstring). Without this, a stopped
     * or rescheduled medication keeps ringing at its old time forever, since
     * GET /api/schedule is purely additive and carries no deletion signal. */
    @Query(
        "DELETE FROM doses WHERE state = 'pending' AND scheduledAtMillis >= :sinceMillis " +
            "AND doseId NOT IN (:keepIds)"
    )
    suspend fun deleteStalePending(sinceMillis: Long, keepIds: List<String>)
}
