package cn.chiyaole

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import cn.chiyaole.net.SyncWorker
import cn.chiyaole.util.RemoteConfigStore

class ChiYaoLeApp : Application() {
    lateinit var remoteConfigStore: RemoteConfigStore
        private set

    override fun onCreate() {
        super.onCreate()
        remoteConfigStore = RemoteConfigStore(this)
        createNotificationChannels()
        SyncWorker.enqueuePeriodic(this)
    }

    /** minSdk 26 was chosen specifically because API 26 introduced NotificationChannel
     * (spec §2.1) — no pre-26 branch needed. */
    private fun createNotificationChannels() {
        val manager = getSystemService(NotificationManager::class.java)

        val alarmChannel = NotificationChannel(
            CHANNEL_ALARM,
            getString(R.string.alarm_channel_name),
            NotificationManager.IMPORTANCE_HIGH,
        ).apply {
            description = getString(R.string.alarm_channel_desc)
            enableVibration(true)
            setBypassDnd(true)
            lockscreenVisibility = android.app.Notification.VISIBILITY_PUBLIC
        }

        val keepAliveChannel = NotificationChannel(
            CHANNEL_KEEPALIVE,
            getString(R.string.keepalive_channel_name),
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = getString(R.string.keepalive_channel_desc)
        }

        manager.createNotificationChannel(alarmChannel)
        manager.createNotificationChannel(keepAliveChannel)
    }

    companion object {
        const val CHANNEL_ALARM = "alarm"
        const val CHANNEL_KEEPALIVE = "keepalive"
    }
}
