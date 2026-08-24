package cn.chiyaole.util

import android.content.Context
import android.media.AudioManager

/**
 * "If a dose is due during a phone call, it defers until the call ends — it never
 * interrupts the call" (spec §4.4 DoD). Deliberately reads [AudioManager.getMode] rather
 * than TelephonyManager.getCallState, which would require the READ_PHONE_STATE runtime
 * permission — one more permission dialog this product does not need (spec §2.1).
 */
object CallStateGuard {
    fun isInCall(context: Context): Boolean {
        val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as? AudioManager
            ?: return false
        return audioManager.mode == AudioManager.MODE_IN_CALL ||
            audioManager.mode == AudioManager.MODE_IN_COMMUNICATION
    }
}
