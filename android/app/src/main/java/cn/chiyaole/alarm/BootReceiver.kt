package cn.chiyaole.alarm

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/**
 * "After a reboot, the schedule restores automatically" (spec §4.4 DoD). Exact alarms do
 * not survive a reboot on Android — this is the only way they come back. Also starts the
 * foreground service (layer 2 of the keep-alive defence) so the process doesn't have to
 * cold-start again the next time an alarm fires.
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        when (intent.action) {
            Intent.ACTION_BOOT_COMPLETED,
            Intent.ACTION_MY_PACKAGE_REPLACED,
            "android.intent.action.QUICKBOOT_POWERON" -> {
                val pendingResult = goAsync()
                CoroutineScope(Dispatchers.IO).launch {
                    try {
                        AlarmScheduler.rescheduleNext(context)
                    } finally {
                        pendingResult.finish()
                    }
                }
                ContextCompat.startForegroundService(context, Intent(context, KeepAliveService::class.java))
            }
        }
    }
}
