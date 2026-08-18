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
 * 支援的郵件類 App：Outlook（Gmail 已改用信箱連接的 API 同步取得完整內容，不再走通知擷取）
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
            // Gmail 不在這裡：已改用「已連接信箱」的 Gmail API 同步取得完整信件內容，
            // 不再需要本機通知擷取這條路徑（通知只有摘要片段，且會跟 API 同步的資料
            // 重複顯示）。目前只有 Gmail 走 API 整合，Outlook 還沒實作，所以 Outlook
            // 通知擷取先保留。
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
        val (appName, type) = mapping

        val extras = sbn.notification.extras ?: return

        // 摘要通知（例如 Gmail 短時間內收到很多信，系統把它們合併成一則「N 封新郵件」的
        // 彙總通知）：如果只處理個別通知、直接跳過摘要通知，遇到來源 App 選擇只發摘要、
        // 不逐封個別發送的情況（實測證實真的會發生），這些信就完全不會被擷取到。
        // 改成：摘要通知改去讀 EXTRA_TEXT_LINES（InboxStyle 常見欄位，彙總時每行通常對應
        // 一則被合併的通知），逐行拆開各自存一筆，而不是整個丟棄。
        // 這個解析方式還沒有拿真實 Gmail 通知洪峰驗證過格式一定符合預期，是最佳猜測寫法，
        // 之後要用真實裝置製造一次通知洪峰重新確認。
        if (sbn.notification.flags and Notification.FLAG_GROUP_SUMMARY != 0) {
            val lines = extras.getCharSequenceArray(Notification.EXTRA_TEXT_LINES)
            if (lines.isNullOrEmpty()) return // 沒有可拆解的內容，真的沒東西可存
            lines.forEachIndexed { index, line ->
                insertFromSummaryLine(appName, type, sbn, line.toString(), index)
            }
            return
        }

        val title = extras.getString(Notification.EXTRA_TITLE)
            ?: extras.getCharSequence(Notification.EXTRA_TITLE)?.toString()
            ?: ""
        // 優先用 EXTRA_BIG_TEXT（BigTextStyle 展開後的較完整內容），
        // 沒有的話才退回 EXTRA_TEXT（收合狀態的短預覽）——注意這仍然受限於
        // 來源 App（Gmail/Outlook 等）自己選擇塞進通知裡多少內容，不代表信件全文。
        val text = extras.getCharSequence(Notification.EXTRA_BIG_TEXT)?.toString()
            ?: extras.getCharSequence(Notification.EXTRA_TEXT)?.toString()
            ?: ""
        val subText = extras.getCharSequence(Notification.EXTRA_SUB_TEXT)?.toString() ?: ""

        if (text.isBlank() && title.isBlank()) return

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
            groupName = groupName,
            notificationKey = sbn.key
        )

        save(notification)
    }

    /**
     * 摘要通知拆解出來的單行，格式沒有保證，常見的是「寄件者: 內容」或「寄件者 - 內容」，
     * 抓不到分隔符號就整行當內容、寄件者退回顯示 App 名稱。
     * notificationKey 額外加上行號後綴——同一則摘要通知更新時，只要合併的信件組合不變，
     * 同一行的 key 就會一樣，靠 unique index 擋掉重複；組合一變（新信加入）行號對應的內容
     * 跟著變，等同於一筆新資料，這是合理的行為（本來就是新信）。
     */
    private fun insertFromSummaryLine(appName: String, type: String, sbn: StatusBarNotification, line: String, index: Int) {
        if (line.isBlank()) return
        // 實測發現：部分系統版本合成彙總通知的每一行時，會在最前面多包一層
        // 「App 名稱: 」的外層前綴（例如「簡訊: 0912345678  你好」），這層前綴
        // 不是真正的寄件者。沒剝掉的話，下面的分隔符號偵測會抓到這個前綴自帶的
        // 冒號，誤判成「寄件者 = 簡訊」，導致完全不同號碼的訊息全部被歸成同一個
        // 假對話（連帶風險等級、卡片顏色也會跟著混在一起）。
        val stripped = if (line.startsWith("$appName: ")) line.removePrefix("$appName: ") else line
        val separator = when {
            stripped.contains(": ") -> ": "
            stripped.contains(" - ") -> " - "
            stripped.contains("  ") -> "  " // 剝掉外層前綴後常見「號碼␣␣內容」格式，沒有冒號可分
            else -> null
        }
        val (sender, content) = if (separator != null) {
            val parts = stripped.split(separator, limit = 2)
            Pair(parts[0].trim(), parts.getOrElse(1) { stripped }.trim())
        } else {
            Pair(appName, stripped)
        }
        save(
            CapturedNotification(
                app = appName,
                sender = sender,
                content = content,
                timestamp = sbn.postTime,
                type = type,
                packageName = sbn.packageName,
                notificationKey = "${sbn.key}#$index"
            )
        )
    }

    private fun save(notification: CapturedNotification) {
        executor.execute {
            try {
                AppDatabase.getInstance(applicationContext)
                    .capturedNotificationDao()
                    .insert(notification)
                Log.d(TAG, "Captured [${notification.app}] ${if (notification.groupName.isNotEmpty()) "(${notification.groupName}) " else ""}${notification.sender}: ${notification.content.take(50)}")
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
