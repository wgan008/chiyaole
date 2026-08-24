package cn.chiyaole.vendor

import android.content.Context
import android.content.Intent
import android.os.Build
import android.provider.Settings
import android.util.Log
import androidx.core.net.toUri

/**
 * Per-OEM allow-list deep links (spec §4.2). Walked by the adult child at install time —
 * never expect the elder to do this themselves (spec §4.1 layer 3).
 *
 * ★ Vendor Activity names change between ROM versions. Every path here is wrapped so a
 * resolution failure falls back to the app-details settings page and this function must
 * never crash (spec §4.2 contract: `openVendorAutoStartSettings`).
 */
object VendorAutoStart {
    private const val TAG = "VendorAutoStart"

    enum class Vendor { HUAWEI, XIAOMI, OPPO, VIVO, OTHER }

    fun detect(): Vendor {
        val manufacturer = Build.MANUFACTURER.lowercase()
        return when {
            manufacturer.contains("huawei") || manufacturer.contains("honor") -> Vendor.HUAWEI
            manufacturer.contains("xiaomi") || manufacturer.contains("redmi") -> Vendor.XIAOMI
            manufacturer.contains("oppo") || manufacturer.contains("oneplus") -> Vendor.OPPO
            manufacturer.contains("vivo") -> Vendor.VIVO
            else -> Vendor.OTHER
        }
    }

    /**
     * Returns whether the deep link succeeded; on failure the caller shows the illustrated
     * guide (spec §4.2 contract). Deliberately does not throw.
     */
    fun openVendorAutoStartSettings(context: Context): Boolean {
        val intent = vendorIntent(context, detect())
        return runCatching {
            context.startActivity(intent)
            true
        }.getOrElse {
            Log.w(TAG, "vendor deep link failed, falling back to app details", it)
            runCatching { context.startActivity(appDetailsIntent(context)) }
            false
        }
    }

    private fun vendorIntent(context: Context, vendor: Vendor): Intent {
        val candidate = when (vendor) {
            Vendor.HUAWEI -> componentIntent(
                "com.huawei.systemmanager",
                "com.huawei.systemmanager.startupmgr.ui.StartupNormalAppListActivity",
            )
            Vendor.XIAOMI -> componentIntent(
                "com.miui.securitycenter",
                "com.miui.permcenter.autostart.AutoStartManagementActivity",
            )
            Vendor.OPPO -> componentIntent(
                "com.coloros.safecenter",
                "com.coloros.safecenter.startupapp.StartupAppListActivity",
            )
            Vendor.VIVO -> componentIntent(
                "com.vivo.permissionmanager",
                "com.vivo.permissionmanager.activity.BgStartUpManagerActivity",
            )
            Vendor.OTHER -> null
        }
        val resolves = candidate != null &&
            context.packageManager.resolveActivity(candidate, 0) != null
        return if (resolves) candidate!! else appDetailsIntent(context)
    }

    private fun componentIntent(packageName: String, className: String): Intent =
        Intent().apply {
            component = android.content.ComponentName(packageName, className)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }

    private fun appDetailsIntent(context: Context): Intent =
        Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
            data = "package:${context.packageName}".toUri()
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
}
