package cn.chiyaole.ui

import android.app.AlarmManager
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.core.app.NotificationManagerCompat
import androidx.core.net.toUri
import cn.chiyaole.R
import cn.chiyaole.ui.theme.AlertRed
import cn.chiyaole.ui.theme.ChiYaoLeTheme
import cn.chiyaole.ui.theme.Dimens
import cn.chiyaole.ui.theme.PrimaryGreen
import cn.chiyaole.vendor.VendorAutoStart

/** One row on the permission setup screen — mirrors the spec §3.5② pseudocode's `Step`. */
data class PermissionStep(val id: String, val title: String, val done: Boolean, val open: () -> Unit)

/**
 * spec §3.5②: "This screen is for the child, not the elder. Telling a 78-year-old 'your
 * reminders may not fire' is meaningless to them and impossible for them to act on — it
 * only produces anxiety." Answers exactly two questions per step: on or off, no severity
 * grading. Opened automatically once (from HomeActivity, when any step is incomplete) and
 * otherwise reachable from Home's "设置" button for the adult child to retry later.
 */
class PermissionSetupActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val context = this
        setContent {
            ChiYaoLeTheme {
                var refreshTick by remember { mutableIntStateOf(0) }
                val steps = remember(refreshTick) { permissionSteps(context) }
                PermissionSetupScreen(
                    steps = steps,
                    onOpen = { it.open(); refreshTick++ },
                    onRecheck = {
                        if (steps.all { it.done }) finish() else refreshTick++
                    },
                    onBack = { finish() },
                )
            }
        }
    }

    companion object {
        fun allStepsDone(context: Context): Boolean = permissionSteps(context).all { it.done }
    }
}

private const val PREFS = "device_prefs"
private const val KEY_AUTOSTART_CONFIRMED = "autostart_confirmed"
private const val KEY_BG_POPUP_CONFIRMED = "bg_popup_confirmed"

/** Mirrors the spec §3.5② pseudocode 1:1 — four (five, on 34+) checks, each simply on or off. */
fun permissionSteps(context: Context): List<PermissionStep> = listOfNotNull(
    if (Build.VERSION.SDK_INT >= 31) {
        val alarmManager = context.getSystemService(AlarmManager::class.java)
        PermissionStep(
            id = "exact_alarm",
            title = context.getString(R.string.permission_step_exact_alarm),
            done = alarmManager.canScheduleExactAlarms(),
            open = { context.startActivity(exactAlarmIntent(context)) },
        )
    } else null,

    PermissionStep(
        id = "notifications",
        title = context.getString(R.string.permission_step_notifications),
        done = NotificationManagerCompat.from(context).areNotificationsEnabled(),
        open = { context.startActivity(notificationSettingsIntent(context)) },
    ),

    PermissionStep(
        id = "battery",
        title = context.getString(R.string.permission_step_battery),
        done = (context.getSystemService(Context.POWER_SERVICE) as PowerManager)
            .isIgnoringBatteryOptimizations(context.packageName),
        open = { context.startActivity(batteryIntent(context)) },
    ),

    if (Build.VERSION.SDK_INT >= 34) {
        val notificationManager = context.getSystemService(NotificationManager::class.java)
        PermissionStep(
            id = "full_screen_intent",
            title = "允许全屏提醒",
            done = notificationManager.canUseFullScreenIntent(),
            open = { context.startActivity(fullScreenIntentSettingsIntent(context)) },
        )
    } else null,

    // Vendor autostart: no API can read this — the user confirms it themselves
    // (spec §3.5②). manuallyConfirmed() reads that confirmation back.
    PermissionStep(
        id = "autostart",
        title = context.getString(R.string.permission_step_autostart),
        done = manuallyConfirmed(context, KEY_AUTOSTART_CONFIRMED),
        open = {
            VendorAutoStart.openVendorAutoStartSettings(context)
            setManuallyConfirmed(context, KEY_AUTOSTART_CONFIRMED, true)
        },
    ),

    // ★ Confirmed live, a genuinely separate permission from autostart above: an alarm
    // fired correctly (AlarmManager's own log confirmed the wakeup) but MIUI blocked the
    // app's startActivity() call at that exact moment — "MIUILOG- Permission Denied
    // Activity" — because this permission was never granted. See VendorAutoStart.
    // openBackgroundPopupSettings's own docstring for why full-screen-intent notifications
    // don't already bypass this on MIUI the way they do on stock Android.
    if (VendorAutoStart.detect() == VendorAutoStart.Vendor.XIAOMI) {
        PermissionStep(
            id = "bg_popup",
            title = context.getString(R.string.permission_step_bg_popup),
            done = manuallyConfirmed(context, KEY_BG_POPUP_CONFIRMED),
            open = {
                VendorAutoStart.openBackgroundPopupSettings(context)
                setManuallyConfirmed(context, KEY_BG_POPUP_CONFIRMED, true)
            },
        )
    } else null,
)

private fun exactAlarmIntent(context: Context): Intent =
    Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM, "package:${context.packageName}".toUri())

private fun notificationSettingsIntent(context: Context): Intent =
    Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
        .putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)

private fun batteryIntent(context: Context): Intent =
    Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, "package:${context.packageName}".toUri())

private fun fullScreenIntentSettingsIntent(context: Context): Intent =
    Intent(Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT, "package:${context.packageName}".toUri())

private fun prefs(context: Context): SharedPreferences =
    context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

private fun manuallyConfirmed(context: Context, key: String = KEY_AUTOSTART_CONFIRMED): Boolean =
    prefs(context).getBoolean(key, false)

private fun setManuallyConfirmed(context: Context, key: String, value: Boolean) {
    prefs(context).edit().putBoolean(key, value).apply()
}

@Composable
private fun PermissionSetupScreen(
    steps: List<PermissionStep>,
    onOpen: (PermissionStep) -> Unit,
    onRecheck: () -> Unit,
    onBack: () -> Unit,
) {
    Scaffold { padding ->
        Column(
            modifier = Modifier.fillMaxSize().padding(padding).padding(Dimens.screenPadding),
            verticalArrangement = Arrangement.spacedBy(Dimens.buttonSpacing),
        ) {
            TextButton(onClick = onBack) {
                Text(text = "‹ 返回", fontSize = Dimens.minTextSp)
            }
            Text(
                text = stringResource(R.string.permission_setup_title),
                fontSize = Dimens.primaryTextSp,
                fontWeight = FontWeight.Bold,
            )
            steps.forEach { step ->
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text(
                        text = (if (step.done) "✓ " else "✗ ") + step.title,
                        fontSize = Dimens.minTextSp,
                        color = if (step.done) PrimaryGreen else AlertRed,
                        modifier = Modifier.weight(1f),
                    )
                    if (!step.done) {
                        TextButton(onClick = { onOpen(step) }) {
                            Text(text = stringResource(R.string.permission_open_settings), fontSize = Dimens.minTextSp)
                        }
                    }
                }
            }
            Button(onClick = onRecheck, modifier = Modifier.fillMaxWidth()) {
                Text(text = stringResource(R.string.permission_recheck), fontSize = Dimens.minTextSp)
            }
        }
    }
}
