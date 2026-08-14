package com.frauddetector.service

object PhoneNumberUtils {
    /**
     * 把號碼正規化成純數字、國際碼統一轉成國內格式（+886912345678 → 0912345678），
     * 用於跨來源（通話紀錄／封鎖清單／後端風險資料庫）比對是否為同一支號碼，
     * 避免同一支號碼因為格式不同而比對不到。
     */
    fun normalize(number: String): String {
        val trimmed = number.trim()
        return if (trimmed.startsWith("+886")) {
            "0" + trimmed.removePrefix("+886").filter { it.isDigit() }
        } else {
            trimmed.filter { it.isDigit() }
        }
    }
}
