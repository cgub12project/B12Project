package com.frauddetector.service

import android.content.Context
import android.provider.CallLog
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 通話紀錄項目
 */
data class CallRecord(
    val number: String,
    val type: Int,          // CallLog.Calls.INCOMING_TYPE / OUTGOING_TYPE / MISSED_TYPE
    val date: Long,         // epoch millis
    val duration: Long,     // seconds
    val displayTime: String // 格式化的時間字串
) {
    val typeLabel: String
        get() = when (type) {
            CallLog.Calls.INCOMING_TYPE -> "來電"
            CallLog.Calls.OUTGOING_TYPE -> "撥出"
            CallLog.Calls.MISSED_TYPE -> "未接"
            CallLog.Calls.REJECTED_TYPE -> "拒接"
            else -> "未知"
        }
}

/**
 * 讀取系統通話紀錄的工具類
 */
object CallLogHelper {

    /**
     * 讀取最近的通話紀錄
     * @param context Context
     * @param limit 最多回傳幾筆，預設 50
     */
    fun getRecentCalls(context: Context, limit: Int = 50): List<CallRecord> {
        val records = mutableListOf<CallRecord>()
        val cursor = context.contentResolver.query(
            CallLog.Calls.CONTENT_URI,
            arrayOf(
                CallLog.Calls.NUMBER,
                CallLog.Calls.TYPE,
                CallLog.Calls.DATE,
                CallLog.Calls.DURATION
            ),
            null, null,
            "${CallLog.Calls.DATE} DESC"
        ) ?: return records

        val sdf = SimpleDateFormat("MM/dd HH:mm", Locale.getDefault())
        var count = 0
        cursor.use {
            while (it.moveToNext() && count < limit) {
                val number = it.getString(0) ?: "未知號碼"
                val type = it.getInt(1)
                val date = it.getLong(2)
                val duration = it.getLong(3)

                records.add(
                    CallRecord(
                        number = number,
                        type = type,
                        date = date,
                        duration = duration,
                        displayTime = sdf.format(Date(date))
                    )
                )
                count++
            }
        }
        return records
    }
}
