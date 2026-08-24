package cn.chiyaole.data

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * ★ Named `confirmation_events`, never `medication_taken` — we record that a button was
 * pressed, not that a pill was swallowed (docs/spec §5). Written the instant the elder taps
 * a button, screen turns off immediately; [syncedAtMillis] is filled in later by
 * [cn.chiyaole.net.SyncWorker], which is why this table is also the offline outbox.
 *
 * [id] is client-generated (UUID) so POST /api/events is idempotent under retry (spec §6.2).
 */
@Entity(tableName = "confirmation_events")
data class ConfirmationEventEntity(
    @PrimaryKey val id: String,
    val doseId: String,
    /** taken | snooze | skip */
    val action: String,
    val skipReason: String?,
    val alarmFiredAtMillis: Long,
    val tappedAtMillis: Long,
    val latencyMs: Int,
    val dwellMs: Int?,
    val ringIndex: Int,
    /** alarm | notification | todo_card */
    val source: String,
    val syncedAtMillis: Long?,
)
