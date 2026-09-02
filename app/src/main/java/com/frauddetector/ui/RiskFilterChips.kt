/**
 * RiskFilterChips.kt — 風險等級篩選 Chips（高危／可疑／安全）
 *
 * 所屬模組：ui（共用畫面元件）
 *
 * 電話分頁與郵件分頁共用同一組篩選列，樣式也共用這一份，兩頁不會長得不一樣。
 * 訊息分頁不用這個——那頁本來就是點上方的「高危／可疑／安全」統計方塊來篩選
 * （見 [com.frauddetector.ui.main.MessagesFragment.toggleLevelFilter]），已經有等價功能。
 *
 * 設計取捨：
 * - Chip 上直接寫數量（例如「高危 3」），使用者按下去之前就知道會篩出幾筆，
 *   篩到空清單時也不會以為是壞掉了。
 * - 選取狀態用該等級的實色底（跟訊息／郵件卡片依風險上色是同一套色彩語言），
 *   未選取則是米白底＋淺灰邊框，整排看起來安靜、不會跟卡片搶視覺。
 * - 顏色全部取自專案十色規範（見 dev-notes/UI配色規範.txt）。
 */
package com.frauddetector.ui

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Color
import androidx.core.content.ContextCompat
import com.frauddetector.R
import com.google.android.material.chip.Chip
import com.google.android.material.chip.ChipGroup

object RiskFilterChips {

    /** 「全部」＝不篩選 */
    const val LEVEL_ALL = "all"

    /** 依顯示順序排列的等級與中文標籤。 */
    private val LEVELS = listOf(
        LEVEL_ALL to "全部",
        "high" to "高危",
        "mid" to "可疑",
        "safe" to "安全",
    )

    private fun accentColorOf(context: Context, level: String): Int = ContextCompat.getColor(
        context,
        when (level) {
            "high" -> R.color.risk_high
            "mid" -> R.color.risk_mid
            "safe" -> R.color.risk_safe
            else -> R.color.steel_blue
        }
    )

    /**
     * 重建整排篩選 Chips。資料每次刷新都會重畫（數量要跟著更新），因此用 [selectedLevel]
     * 還原使用者原本選的那一顆，不會把篩選重置回「全部」。
     *
     * @param counts 各等級的筆數，key 為 "high"/"mid"/"safe"；「全部」自動用總數
     * @param onSelect 使用者切換時回呼，值為 [LEVEL_ALL] 或 high/mid/safe
     */
    fun render(
        chipGroup: ChipGroup,
        counts: Map<String, Int>,
        selectedLevel: String,
        onSelect: (String) -> Unit
    ) {
        val context = chipGroup.context
        val density = context.resources.displayMetrics.density
        val cream = ContextCompat.getColor(context, R.color.soft_cream)
        val mutedText = ContextCompat.getColor(context, R.color.warm_grey)
        val idleStroke = Color.parseColor("#33C8C4C0")

        // 先拆掉舊的監聽器再重建，否則 removeAllViews() 造成的取消勾選會被當成使用者操作
        chipGroup.setOnCheckedStateChangeListener(null)
        chipGroup.removeAllViews()

        val total = counts.values.sum()
        val chipIdToLevel = mutableMapOf<Int, String>()

        LEVELS.forEach { (level, label) ->
            val count = if (level == LEVEL_ALL) total else (counts[level] ?: 0)
            val accent = accentColorOf(context, level)
            val chip = Chip(context).apply {
                text = "$label $count"
                textSize = 11f
                isCheckable = true
                isCheckedIconVisible = false
                isChecked = level == selectedLevel
                chipBackgroundColor = ColorStateList(
                    arrayOf(intArrayOf(android.R.attr.state_checked), intArrayOf()),
                    intArrayOf(accent, cream)
                )
                setTextColor(
                    ColorStateList(
                        arrayOf(intArrayOf(android.R.attr.state_checked), intArrayOf()),
                        intArrayOf(cream, mutedText)
                    )
                )
                chipStrokeWidth = 1f * density
                chipStrokeColor = ColorStateList(
                    arrayOf(intArrayOf(android.R.attr.state_checked), intArrayOf()),
                    intArrayOf(accent, idleStroke)
                )
            }
            chipGroup.addView(chip)
            chipIdToLevel[chip.id] = level
        }

        chipGroup.setOnCheckedStateChangeListener { _, checkedIds ->
            // 再點一次已選取的 chip 會變成沒有任何選取，這時等同「全部」
            val level = checkedIds.firstOrNull()?.let { chipIdToLevel[it] } ?: LEVEL_ALL
            onSelect(level)
        }
    }
}
