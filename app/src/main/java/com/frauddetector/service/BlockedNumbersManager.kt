package com.frauddetector.service

import android.content.Context

/**
 * 本機封鎖電話號碼清單 — 純本地功能（不涉及跨用戶共享），儲存於 SharedPreferences。
 * 效果：(1) 已封鎖的號碼不會出現在「電話」頁的查詢結果中；(2) 使用者把 FLASH 設為系統
 * 預設來電攔截 App 後（見 [CallBlockingService]），這張清單也會被拿去真的擋掉來電。
 */
object BlockedNumbersManager {
    private const val PREFS = "flash_blocked_numbers"
    private const val KEY = "numbers"

    fun isBlocked(context: Context, number: String): Boolean {
        val target = PhoneNumberUtils.normalize(number)
        if (target.isEmpty()) return false
        return getAll(context).any { PhoneNumberUtils.normalize(it) == target }
    }

    /** @return 切換後是否為「已封鎖」狀態 */
    fun toggle(context: Context, number: String): Boolean {
        return if (isBlocked(context, number)) {
            remove(context, number)
            false
        } else {
            add(context, number)
            true
        }
    }

    private fun add(context: Context, number: String) {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val current = prefs.getStringSet(KEY, emptySet())!!.toMutableSet()
        current.add(number)
        prefs.edit().putStringSet(KEY, current).apply()
    }

    private fun remove(context: Context, number: String) {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val current = prefs.getStringSet(KEY, emptySet())!!.toMutableSet()
        current.remove(number)
        prefs.edit().putStringSet(KEY, current).apply()
    }

    fun getAll(context: Context): Set<String> =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getStringSet(KEY, emptySet()) ?: emptySet()
}
