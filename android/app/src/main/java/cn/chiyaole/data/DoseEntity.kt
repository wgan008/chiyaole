package cn.chiyaole.data

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * Local cache of one dose occurrence, synced from GET /api/schedule (spec §6.2).
 *
 * [photoLocalPath] is a file already downloaded to app-private storage at sync time —
 * AlarmActivity.onCreate must never make a network call (spec §3.4-③), so the photo has to
 * exist on disk before the alarm that needs it ever fires.
 */
@Entity(tableName = "doses")
data class DoseEntity(
    @PrimaryKey val doseId: String,
    val medicationId: String,
    val scheduledAtMillis: Long,
    val genericName: String,
    val dosePerTake: Double,
    val timingNote: String?,
    val photoLocalPath: String?,
    /** pending | confirmed | snoozed | skipped | missed — mirrors server `doses.state`,
     * updated locally the instant a button is tapped, before any network round trip. */
    val state: String = "pending",
)
