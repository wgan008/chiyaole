package cn.chiyaole.alarm

import android.app.Notification
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleService
import androidx.lifecycle.lifecycleScope
import cn.chiyaole.ChiYaoLeApp
import cn.chiyaole.R
import cn.chiyaole.data.ScheduleRepository
import cn.chiyaole.ui.HomeActivity
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlinx.coroutines.flow.launchIn
import kotlinx.coroutines.flow.onEach

/**
 * Layer 2 of the keep-alive defence (spec §4.1): "Its persistent notification doubles as
 * the pending-dose card — two purposes, so it is not pure keep-alive noise." Keeps the
 * process warm so [cn.chiyaole.ui.AlarmActivity] never has to cold-start on a weak SoC
 * (spec §3.4-③).
 */
class KeepAliveService : LifecycleService() {
    private lateinit var repo: ScheduleRepository

    override fun onCreate() {
        super.onCreate()
        repo = ScheduleRepository(this)
        startForeground(NOTIFICATION_ID, buildNotification(null))
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
        observeNextDose()
        return START_STICKY
    }

    private fun observeNextDose() {
        val now = System.currentTimeMillis()
        val endOfDay = now + 24 * 60 * 60 * 1000L
        repo.observeToday(now, endOfDay)
            .onEach { doses ->
                val next = doses.firstOrNull { it.state == "pending" }
                updateNotification(next?.let { "${timeFormat.format(Date(it.scheduledAtMillis))}  ${it.genericName}" })
            }
            .launchIn(lifecycleScope)
    }

    private fun updateNotification(pendingText: String?) {
        val manager = ContextCompat.getSystemService(this, android.app.NotificationManager::class.java)
        manager?.notify(NOTIFICATION_ID, buildNotification(pendingText))
    }

    private fun buildNotification(pendingText: String?): Notification {
        val contentIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, HomeActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        return NotificationCompat.Builder(this, ChiYaoLeApp.CHANNEL_KEEPALIVE)
            .setSmallIcon(R.drawable.ic_stat_notify)
            .setContentTitle(getString(R.string.keepalive_notification_title))
            .setContentText(pendingText ?: getString(R.string.keepalive_notification_text_idle))
            .setContentIntent(contentIntent)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    companion object {
        private const val NOTIFICATION_ID = 1
        private val timeFormat = SimpleDateFormat("HH:mm", Locale.CHINA)

        fun start(context: Context) {
            ContextCompat.startForegroundService(context, Intent(context, KeepAliveService::class.java))
        }
    }
}
