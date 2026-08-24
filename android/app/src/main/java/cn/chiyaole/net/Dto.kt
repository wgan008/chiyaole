package cn.chiyaole.net

import kotlinx.serialization.Serializable

/** Mirrors server/app/schemas.py device-side models (spec §6.2). Timestamps are ISO-8601
 * strings on the wire — see [toIso]/[fromIso] — matching Pydantic's `datetime` JSON encoding. */

@Serializable
data class DeviceRegisterRequest(
    val patient_id: String,
    val device_info: Map<String, String> = emptyMap(),
)

@Serializable
data class DeviceRegisterOut(val device_token: String, val display_name: String)

/** The formal pairing flow (PairingActivity) — the code comes from the caregiver's
 * setup.html page, read aloud to whoever is installing this APK. */
@Serializable
data class DevicePairRequest(val code: String)

@Serializable
data class ScheduleItemDto(
    val dose_id: String,
    val medication_id: String,
    val scheduled_at: String,
    val generic_name: String,
    val dose_per_take: Double,
    val timing_note: String?,
    /** ★ Must be downloaded and cached to a local file before this is written to Room —
     * AlarmActivity.onCreate must never make a network call (spec §3.4-③). */
    val photo_url: String?,
)

@Serializable
data class ScheduleOut(val items: List<ScheduleItemDto>, val generated_at: String)

@Serializable
data class EventIn(
    val id: String,
    val dose_id: String,
    val action: String,
    val skip_reason: String? = null,
    val alarm_fired_at: String,
    val tapped_at: String,
    val latency_ms: Int,
    val dwell_ms: Int? = null,
    val ring_index: Int = 1,
    val source: String = "alarm",
)

@Serializable
data class EventsRequest(val events: List<EventIn>)

@Serializable
data class EventsOut(val accepted: Int, val duplicates: Int)

@Serializable
data class DoctorViewMedicationDto(
    val generic_name: String,
    val strength_value: Double?,
    val strength_unit: String?,
    val dose_per_take: Double,
    val times_per_day: Int,
    val timing_note: String?,
)

@Serializable
data class DoctorViewDoseDto(
    val dose_id: String,
    val scheduled_at: String,
    val medication: String,
    val state: String,
)

@Serializable
data class DoctorViewOut(
    val patient_id: String,
    val display_name: String,
    val medications: List<DoctorViewMedicationDto>,
    val today: List<DoctorViewDoseDto>,
)

@Serializable
data class AsrOut(val text: String, val confidence: Double)

@Serializable
data class QaRequest(val text: String)

/** No escalation_id — the caregiver-reply loop (wireframe C3->C4) is not wired up this
 * pass, see server/app/api/device.py's module docstring. A refused question already comes
 * back with a spoken decline naming the caregiver; there is nothing further to poll for. */
@Serializable
data class QaOut(val spoken: String, val intent: String, val refused: Boolean = false)

@Serializable
data class ErrorBody(val code: String, val message: String)

@Serializable
data class ErrorResponse(val error: ErrorBody)

fun Long.toIso(): String = java.time.Instant.ofEpochMilli(this).toString()

/** ★ Instant.parse() only accepts a literal "Z" (UTC) offset and throws
 * DateTimeParseException on anything else — confirmed live: the server serializes
 * scheduled_at with its actual zone offset (e.g. "2026-08-13T06:30:00+08:00" from a
 * Postgres session in China time), which crashed SyncWorker silently (caught by a broad
 * `catch (t: Throwable)` with no logging) on every sync. OffsetDateTime.parse() accepts
 * both "Z" and an explicit offset.
 *
 * ★ Confirmed live a second time, against a SQLite-backed dev server (`DATABASE_URL=
 * sqlite:///...`, no docker/postgres): SQLite has no timezone-aware datetime type, so a
 * `DateTime(timezone=True)` column silently loses its offset there even though the same
 * column is genuinely offset-aware on real Postgres — the wire value comes back as a bare
 * "2026-08-17T10:34:12.140392", no offset at all, which OffsetDateTime.parse() rejects
 * outright. This only happens against SQLite (a local-dev convenience the server intends to
 * support — see server/app/models/base.py's GUID type and Escalation.context_json's own
 * `.with_variant`), never against production Postgres (spec §2: "Production is always
 * PostgreSQL 16"). Since a SQLite dev server and this device are always the same machine,
 * interpreting the missing offset as the system's local zone is correct for that case. */
fun String.isoToMillis(): Long =
    runCatching { java.time.OffsetDateTime.parse(this).toInstant().toEpochMilli() }
        .getOrElse {
            java.time.LocalDateTime.parse(this)
                .atZone(java.time.ZoneId.systemDefault())
                .toInstant()
                .toEpochMilli()
        }
