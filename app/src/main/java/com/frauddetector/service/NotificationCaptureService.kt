package com.frauddetector.service

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Log
import com.frauddetector.db.AppDatabase
import com.frauddetector.db.CapturedNotification
import java.util.concurrent.Executors

/**
 * 通知監聽服務 — 擷取來自指定 App 的通知並儲存至 Room DB。
 *
 * 支援的訊息類 App：LINE, WhatsApp, Messenger, Google 簡訊, Samsung 簡訊
 * 支援的郵件類 App：Gmail, Outlook
 */
class NotificationCaptureService : NotificationListenerService() {

    companion object {
        private const val TAG = "NotifCapture"

        /** packageName → (顯示名稱, 分類) */
        private val APP_MAP = mapOf(
            // ── 訊息類 ──
            // LINE
            "jp.naver.line.android" to Pair("LINE", "message"),
            "com.linecorp.LINE" to Pair("LINE", "message"),
            // WhatsApp
            "com.whatsapp" to Pair("WhatsApp", "message"),
            "com.whatsapp.w4b" to Pair("WhatsApp Business", "message"),
            // Facebook Messenger
            "com.facebook.orca" to Pair("Messenger", "message"),
            "com.facebook.mlite" to Pair("Messenger Lite", "message"),
            // Telegram
            "org.telegram.messenger" to Pair("Telegram", "message"),
            "org.telegram.messenger.web" to Pair("Telegram", "message"),
            // Signal
            "org.thoughtcrime.securesms" to Pair("Signal", "message"),
            // 微信
            "com.tencent.mm" to Pair("微信", "message"),
            // Instagram DM
            "com.instagram.android" to Pair("Instagram", "message"),
            // Twitter / X DM
            "com.twitter.android" to Pair("X (Twitter)", "message"),
            // Discord
            "com.discord" to Pair("Discord", "message"),
            // Viber
            "com.viber.voip" to Pair("Viber", "message"),
            // KakaoTalk
            "com.kakao.talk" to Pair("KakaoTalk", "message"),
            // Skype
            "com.skype.raider" to Pair("Skype", "message"),
            // Teams (聊天)
            "com.microsoft.teams" to Pair("Teams", "message"),
            // Slack
            "com.Slack" to Pair("Slack", "message"),
            // 簡訊
            "com.google.android.apps.messaging" to Pair("簡訊", "message"),
            "com.samsung.android.messaging" to Pair("簡訊", "message"),
            "com.android.mms" to Pair("簡訊", "message"),

            // ── 郵件類 ──
            "com.google.android.gm" to Pair("Gmail", "email"),
            "com.microsoft.office.outlook" to Pair("Outlook", "email"),
            "com.yahoo.mobile.client.android.mail" to Pair("Yahoo Mail", "email"),
            "com.samsung.android.email.provider" to Pair("Samsung Email", "email"),
            "me.proton.android.mail" to Pair("Proton Mail", "email"),
            "com.apple.android.email" to Pair("Apple Mail", "email"),
            "ru.yandex.mail" to Pair("Yandex Mail", "email"),
            "com.readdle.spark" to Pair("Spark", "email")
        )
    }

    private val executor = Executors.newSingleThreadExecutor()

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        sbn ?: return
        val mapping = APP_MAP[sbn.packageName] ?: return

        val extras = sbn.notification.extras ?: return
        val title = extras.getString(Notification.EXTRA_TITLE)
            ?: extras.getCharSequence(Notification.EXTRA_TITLE)?.toString()
            ?: ""
        val text = extras.getCharSequence(Notification.EXTRA_TEXT)?.toString()
            ?: extras.getCharSequence(Notification.EXTRA_BIG_TEXT)?.toString()
            ?: ""
        val subText = extras.getCharSequence(Notification.EXTRA_SUB_TEXT)?.toString() ?: ""

        // 跳過空白通知和系統摘要通知
        if (text.isBlank() && title.isBlank()) return
        if (sbn.notification.flags and Notification.FLAG_GROUP_SUMMARY != 0) return

        val (appName, type) = mapping

        // 解析群組/私訊
        // LINE 群組通知格式: title = "群組名稱", subText/conversationTitle 可能有群組名
        // LINE 私訊格式: title = "發送者名稱"
        // WhatsApp 群組: title = "sender @ 群組名稱" 或 subText = "群組名稱"
        val (sender, groupName) = parseSenderAndGroup(appName, title, subText)

        val notification = CapturedNotification(
            app = appName,
            sender = sender,
            content = text,
            timestamp = sbn.postTime,
            type = type,
            packageName = sbn.packageName,
            groupName = groupName
        )

        executor.execute {
            try {
                AppDatabase.getInstance(applicationContext)
                    .capturedNotificationDao()
                    .insert(notification)
                Log.d(TAG, "Captured [$appName] ${if (groupName.isNotEmpty()) "($groupName) " else ""}$sender: ${text.take(50)}")
            } catch (e: Exception) {
                Log.e(TAG, "Failed to save notification", e)
            }
        }
    }

    /**
     * 解析通知的 sender 和 groupName
     * @return Pair(sender, groupName)  groupName 為空代表私訊
     */
    private fun parseSenderAndGroup(app: String, title: String, subText: String): Pair<String, String> {
        return when (app) {
            "LINE" -> {
                // LINE 群組通知: subText 有時會包含群組名
                if (subText.isNotEmpty()) Pair(title, subText) else Pair(title, "")
            }
            "WhatsApp", "WhatsApp Business" -> {
                // WhatsApp 群組格式: "sender @ 群組名稱"
                if (title.contains(" @ ")) {
                    val parts = title.split(" @ ", limit = 2)
                    Pair(parts[0].trim(), parts[1].trim())
                } else {
                    Pair(title, "")
                }
            }
            "Messenger", "Messenger Lite" -> {
                // Messenger 群組有時 subText 是群組名
                if (subText.isNotEmpty()) Pair(title, subText) else Pair(title, "")
            }
            "Telegram" -> {
                // Telegram 群組/頻道: subText 通常是群組名
                if (subText.isNotEmpty()) Pair(title, subText) else Pair(title, "")
            }
            "Discord" -> {
                // Discord: subText 通常是 #頻道名 或伺服器名
                if (subText.isNotEmpty()) Pair(title, subText) else Pair(title, "")
            }
            "Teams", "Slack" -> {
                // Teams/Slack: subText 通常是頻道或團隊名
                if (subText.isNotEmpty()) Pair(title, subText) else Pair(title, "")
            }
            "微信" -> {
                // 微信群組: subText 可能是群組名
                if (subText.isNotEmpty()) Pair(title, subText) else Pair(title, "")
            }
            else -> Pair(title, "")
        }
    }
}
