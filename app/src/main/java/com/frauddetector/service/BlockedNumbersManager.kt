package com.frauddetector.service

import android.content.Context

/**
 * 本機封鎖電話號碼清單 — 純本地功能（不涉及跨用戶共享），儲存於 SharedPreferences。
 * 沒有真正的通話攔截（需要 CallScreeningService，屬未來規劃），
 * 目前效果為：已封鎖的號碼不會出現在「電話」頁的查詢結果中。
 */
object BlockedNumbersManager {
    private const val PREFS = "flash_blocked_numbers"
    private const val KEY = "numbers"

    fun isBlocked(context: Context, number: String): Boolean = getAll(context).contains(number)

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
