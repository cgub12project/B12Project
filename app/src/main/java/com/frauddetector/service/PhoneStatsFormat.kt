/**
 * PhoneStatsFormat.kt — 電話統計欄位的顯示格式
 *
 * 所屬模組：service（領域邏輯）
 *
 * 電話詳情頁的三個統計方塊各只有畫面寬度的三分之一，內容一長就會折成兩行、
 * 把方塊撐高，看起來歪掉。這裡統一處理兩個會撐爆欄位的值：
 * - 舉報次數：超過 999 就顯示 "999+"
 * - 最近舉報日期：同一年只顯示 MM/DD，跨年才補上兩位數年份
 */
package com.frauddetector.service

import java.util.Calendar

object PhoneStatsFormat {

    /** 超過這個數字就不再顯示精確值——統計方塊放不下，而且對使用者來說「很多」就夠了。 */
    private const val COUNT_CAP = 999

    /** 舉報次數：0-999 照實顯示，超過一律 "999+"。 */
    fun reportCount(count: Int): String =
        if (count > COUNT_CAP) "$COUNT_CAP+" else count.toString()

    /**
     * 最近舉報日期：後端給的是 ISO 字串（例如 "2026-08-30T12:16:09"）。
     * 同一年顯示 "08/30"，不同年顯示 "25/08/30"——年份不同時如果只給月日，
     * 使用者會誤以為是今年的舉報。
     *
     * @param isoTimestamp 後端的 ISO 時間字串，null 或格式不符時回傳 "—"
     */
    fun reportDate(isoTimestamp: String?): String {
        val date = isoTimestamp?.take(10) ?: return "—"
        val parts = date.split("-")
        if (parts.size != 3) return date
        val (year, month, day) = parts
        if (year.length != 4 || month.length != 2 || day.length != 2) return date
        val currentYear = Calendar.getInstance().get(Calendar.YEAR).toString()
        return if (year == currentYear) "$month/$day" else "${year.takeLast(2)}/$month/$day"
    }
}
