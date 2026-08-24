package cn.chiyaole.net

import android.content.Context

/** Elder device auth = `device_token` issued at registration (spec §6, "Conventions").
 * Stored locally; never backed up (manifest allowBackup=false covers this too). */
class DeviceAuth(context: Context) {
    private val prefs = context.getSharedPreferences("device_prefs", Context.MODE_PRIVATE)

    var deviceToken: String?
        get() = prefs.getString(KEY_DEVICE_TOKEN, null)
        set(value) = prefs.edit().putString(KEY_DEVICE_TOKEN, value).apply()

    var patientId: String?
        get() = prefs.getString(KEY_PATIENT_ID, null)
        set(value) = prefs.edit().putString(KEY_PATIENT_ID, value).apply()

    /** How TTS addresses the elder — 「王阿姨」. Fetched once at registration
     * (DeviceRegisterOut.display_name) and cached here so AlarmActivity.onCreate never
     * needs a network call to know who to address (spec §3.4-③). */
    var patientDisplayName: String?
        get() = prefs.getString(KEY_PATIENT_DISPLAY_NAME, null)
        set(value) = prefs.edit().putString(KEY_PATIENT_DISPLAY_NAME, value).apply()

    val isRegistered: Boolean get() = deviceToken != null

    companion object {
        private const val KEY_DEVICE_TOKEN = "device_token"
        private const val KEY_PATIENT_ID = "patient_id"
        private const val KEY_PATIENT_DISPLAY_NAME = "patient_display_name"
    }
}
