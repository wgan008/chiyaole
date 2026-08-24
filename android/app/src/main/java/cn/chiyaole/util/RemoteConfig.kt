package cn.chiyaole.util

import android.content.Context
import android.util.Log
import java.io.File
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * Mirrors data/remote_config.json. "★ Wording, timings and feature flags. Edit here —
 * changing any of this must NOT require shipping a new APK" (remote_config.json _meta).
 *
 * The device fetches GET /api/config once daily (spec §6.2) and keeps the last good copy;
 * if it has never fetched successfully, [DEFAULT] — baked into the APK, kept in sync by
 * hand with data/remote_config.json — is used instead. This class only owns the on-disk
 * cache and the fallback; [cn.chiyaole.net.ApiService] performs the actual fetch and hands
 * the raw JSON to [RemoteConfigStore.save].
 */
@Serializable
data class RemoteConfig(
    val alarm: AlarmConfig = AlarmConfig(),
    val tts: TtsConfig = TtsConfig(),
    val copy: CopyConfig = CopyConfig(),
) {
    @Serializable
    data class AlarmConfig(
        val screenOnToSpeechDelayMs: Long = 400,
        /** Offsets in ms from scheduled_at for ring 1/2/3: 0, +10 min, +30 min. */
        val ringSeriesMs: List<Long> = listOf(0L, 600_000L, 1_800_000L),
        val autoDismissMs: Long = 120_000L,
        val snoozeMinutes: Int = 15,
        val maxSnoozes: Int = 2,
        val deferDuringCall: Boolean = true,
        val missedAfterMinutes: Int = 60,
    )

    @Serializable
    data class TtsConfig(
        val rate: Float = 0.85f,
        val pitch: Float = 1.0f,
    )

    @Serializable
    data class CopyConfig(
        val alarmTitleFmt: String = "{name}，该吃药了",
        val buttonTaken: String = "吃了",
        val buttonSnooze: String = "等会儿吃",
        val buttonSkip: String = "这次不吃",
        val buttonSpeak: String = "长按说话",
        val buttonDoctor: String = "给医生看",
        val refusalGeneric: String = "这个我不能答，我帮你问{caregiver}",
        val refusalMedChange: String = "加药减药停药这种事我不能说，我帮你问{caregiver}",
        val refusalSymptom: String = "身上不舒服我不能判断，我帮你问{caregiver}",
        val unresolvedEntity: String = "这个我没找到，我不敢乱猜。我帮你问{caregiver}",
    )

    companion object {
        /** Baked-in fallback. Keep in sync by hand with data/remote_config.json. */
        val DEFAULT = RemoteConfig()
    }
}

/** Fills a `{name}`/`{caregiver}` template — the only templating remote_config.json uses. */
fun String.fillTemplate(vararg pairs: Pair<String, String>): String =
    pairs.fold(this) { acc, (key, value) -> acc.replace("{$key}", value) }

class RemoteConfigStore(private val context: Context) {
    private val cacheFile: File get() = File(context.filesDir, "remote_config_cache.json")
    private val json = Json { ignoreUnknownKeys = true; isLenient = true }

    @Volatile private var cached: RemoteConfig? = null

    /** Synchronous by design — [cn.chiyaole.alarm.AlarmReceiver] reads this on the alarm
     * delivery path and must never block on network or a slow read. */
    fun current(): RemoteConfig {
        cached?.let { return it }
        val fromDisk = runCatching {
            if (cacheFile.exists()) json.decodeFromString<RemoteConfig>(cacheFile.readText()) else null
        }.getOrElse {
            Log.w("RemoteConfigStore", "cached config unreadable, using DEFAULT", it)
            null
        }
        val resolved = fromDisk ?: RemoteConfig.DEFAULT
        cached = resolved
        return resolved
    }

    /** Called by the networking layer after a successful GET /api/config. */
    fun save(rawJson: String) {
        val parsed = runCatching { json.decodeFromString<RemoteConfig>(rawJson) }.getOrNull() ?: return
        cacheFile.writeText(rawJson)
        cached = parsed
    }
}
