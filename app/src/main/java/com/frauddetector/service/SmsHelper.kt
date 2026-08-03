package com.frauddetector.service

import android.content.Context
import android.net.Uri
import com.frauddetector.db.CapturedNotification

/**
 * 讀取系統簡訊收件匣歷史的工具類
 */
object SmsHelper {

    /**
     * 讀取簡訊收件匣（僅收到的簡訊）
     * @param context Context
     * @param limit 最多回傳幾筆，預設 200
     */
    fun getInboxMessages(context: Context, limit: Int = 200): List<CapturedNotification> {
        val results = mutableListOf<CapturedNotification>()
        val cursor = context.contentResolver.query(
            Uri.parse("content://sms/inbox"),
            arrayOf("_id", "address", "body", "date", "read"),
            null, null,
            "date DESC"
        ) ?: return results

        var count = 0
        cursor.use {
            while (it.moveToNext() && count < limit) {
                val address = it.getString(1) ?: "未知號碼"
                val body = it.getString(2) ?: ""
                val date = it.getLong(3)
                val read = it.getInt(4) == 1

                if (body.isBlank()) continue

                results.add(
                    CapturedNotification(
                        app = "簡訊",
                        sender = address,
                        content = body,
                        timestamp = date,
                        type = "message",
                        packageName = "sms_history",  // 標記為歷史匯入
                        groupName = "",
                        isRead = read
                    )
                )
                count++
            }
        }
        return results
    }
}
