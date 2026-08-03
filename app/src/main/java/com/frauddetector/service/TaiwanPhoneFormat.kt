package com.frauddetector.service

/**
 * 判斷一個電話號碼字串是否符合台灣門號的常規格式（純字串規則比對，
 * 不查詢任何後端／AI，跟風險等級、社群舉報完全無關，只是額外的一個獨立線索）。
 *
 * 只抓「明顯不對」的情況，不是精確比對電信局公告的完整區碼長度表：
 * - 手機：09 開頭 + 共 10 碼（例如 0912345678）
 * - 付費/免付費服務號碼：0800 或 0809 開頭 + 共 10 碼
 * - 市話：0 + 區碼（1-3 碼）+ 本地號碼，總長度 8-10 碼、區碼開頭是 2-8
 *   （例如台北 02 是 1 碼區碼、苗栗 037 是 2 碼區碼，這裡用長度範圍簡化涵蓋，
 *   不逐一列出每個縣市確切的區碼長度）
 * - +886 開頭視為國際格式的台灣號碼，去掉 +886 還原成國內格式（補一個 0）後
 *   套用上面同一套規則
 * - 任何其他國碼開頭（+1、+44、+81…）或完全不是這些格式的號碼，一律視為異常
 */
object TaiwanPhoneFormat {

    private val MOBILE = Regex("^09\\d{8}$")
    private val SERVICE = Regex("^0(800|809)\\d{6}$")
    private val LANDLINE = Regex("^0[2-8]\\d{6,8}$")

    fun isAbnormal(rawNumber: String): Boolean {
        val trimmed = rawNumber.trim()

        val domestic = when {
            trimmed.startsWith("+886") -> "0" + trimmed.removePrefix("+886").filter { it.isDigit() }
            trimmed.startsWith("+") -> return true // 其他國碼，一律視為非台灣常規格式
            else -> trimmed
        }

        val digits = domestic.filter { it.isDigit() }
        if (!digits.startsWith("0")) return true

        return !(MOBILE.matches(digits) || SERVICE.matches(digits) || LANDLINE.matches(digits))
    }
}
