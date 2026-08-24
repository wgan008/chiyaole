package cn.chiyaole.data

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query

@Dao
interface ConfirmationEventDao {
    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insert(event: ConfirmationEventEntity)

    /** The offline outbox SyncWorker drains — spec §1: "unsynced events" survive a restart
     * because they live in SQLite, not memory. */
    @Query("SELECT * FROM confirmation_events WHERE syncedAtMillis IS NULL ORDER BY tappedAtMillis ASC")
    suspend fun unsynced(): List<ConfirmationEventEntity>

    @Query("UPDATE confirmation_events SET syncedAtMillis = :syncedAtMillis WHERE id IN (:ids)")
    suspend fun markSynced(ids: List<String>, syncedAtMillis: Long)

    @Query("SELECT COUNT(*) FROM confirmation_events WHERE doseId = :doseId AND action = 'taken'")
    suspend fun takenCountForDose(doseId: String): Int
}
