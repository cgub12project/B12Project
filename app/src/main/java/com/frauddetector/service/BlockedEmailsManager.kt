package com.frauddetector.service

import android.content.Context

/**
 * 本機封鎖信箱寄件人清單 — 純本地功能（不涉及跨用戶共享），儲存於 SharedPreferences。
 * 沒有真正阻止對方寄信或動到真實信箱（需要 Gmail/Graph API 才做得到，屬未來規劃），
 * 目前效果為：已封鎖的寄件人不會出現在「郵件」頁的列表中。
 */
object BlockedEmailsManager {
    private const val PREFS = "flash_blocked_emails"
    private const val KEY = "senders"

    fun isBlocked(context: Context, sender: String): Boolean = getAll(context).contains(sender)

    /** @return 切換後是否為「已封鎖」狀態 */
    fun toggle(context: Context, sender: String): Boolean {
        return if (isBlocked(context, sender)) {
            remove(context, sender)
            false
        } else {
            add(context, sender)
            true
        }
    }

    private fun add(context: Context, sender: String) {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val current = prefs.getStringSet(KEY, emptySet())!!.toMutableSet()
        current.add(sender)
        prefs.edit().putStringSet(KEY, current).apply()
    }

    private fun remove(context: Context, sender: String) {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val current = prefs.getStringSet(KEY, emptySet())!!.toMutableSet()
        current.remove(sender)
        prefs.edit().putStringSet(KEY, current).apply()
    }

    fun getAll(context: Context): Set<String> =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getStringSet(KEY, emptySet()) ?: emptySet()
}
