package com.frauddetector.service

import android.app.role.RoleManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.text.TextUtils

/**
 * 權限檢查與引導工具
 */
object PermissionHelper {

    /**
     * 檢查本 App 是否已取得通知存取權 (NotificationListenerService)
     */
    fun isNotificationListenerEnabled(context: Context): Boolean {
        val flat = Settings.Secure.getString(
            context.contentResolver,
            "enabled_notification_listeners"
        ) ?: return false

        val componentName = ComponentName(context, NotificationCaptureService::class.java)
        return flat.split(":").any {
            val cn = ComponentName.unflattenFromString(it)
            cn != null && cn == componentName
        }
    }

    /**
     * 開啟系統的「通知存取權」設定頁面
     */
    fun openNotificationListenerSettings(context: Context) {
        context.startActivity(
            Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
        )
    }

    /**
     * 檢查 FLASH 是否已被使用者設為系統的「預設來電辨識/垃圾電話攔截」App
     * （`ROLE_CALL_SCREENING`，Android 10+ 才有這個角色）。
     * 只有設定成功，[CallBlockingService] 才會真的被系統呼叫、封鎖名單才會真的擋到來電。
     */
    fun isCallScreeningRoleHeld(context: Context): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return false
        val roleManager = context.getSystemService(RoleManager::class.java) ?: return false
        return roleManager.isRoleHeld(RoleManager.ROLE_CALL_SCREENING)
    }

    /**
     * 取得「請求設為預設來電攔截 App」的系統 Intent，交給 Activity/Fragment 用
     * `registerForActivityResult` 啟動。裝置版本太舊（Android 10 以下）或此角色不可用時回傳 null，
     * 呼叫端要自行處理（引導使用者手動到系統設定調整）。
     */
    fun createCallScreeningRoleRequestIntent(context: Context): Intent? {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return null
        val roleManager = context.getSystemService(RoleManager::class.java) ?: return null
        if (!roleManager.isRoleAvailable(RoleManager.ROLE_CALL_SCREENING)) return null
        return roleManager.createRequestRoleIntent(RoleManager.ROLE_CALL_SCREENING)
    }

    /**
     * 檢查是否已授權「顯示在其他應用程式上層」（`SYSTEM_ALERT_WINDOW`）。
     * [CallBlockingService] 響鈴時顯示風險標籤懸浮視窗（[CallRiskOverlay]）需要這個權限，
     * 跟 [isCallScreeningRoleHeld] 是兩個獨立的權限，都要有才能看到懸浮標籤。
     */
    fun canDrawOverlays(context: Context): Boolean = Settings.canDrawOverlays(context)

    /**
     * 取得「允許顯示在其他應用程式上層」的系統設定頁 Intent。這個權限沒有標準的
     * `registerForActivityResult` 回傳授權結果的方式（系統不保證 result code 準確反映
     * 使用者是否真的授權），呼叫端回來後應該用 [canDrawOverlays] 重新檢查一次目前狀態。
     */
    fun createOverlayPermissionRequestIntent(context: Context): Intent =
        Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:${context.packageName}"))
}
