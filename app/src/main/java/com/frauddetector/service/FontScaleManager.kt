package com.frauddetector.service

import android.content.Context

/**
 * 使用者自訂的全域文字放大倍率管理。
 *
 * 倍率透過 [android.content.res.Configuration.fontScale] 套用（見
 * [com.frauddetector.ui.BaseActivity]），沿用 Android 原生「輔助功能字體大小」
 * 的機制，App 內所有以 sp 定義的 textSize 皆會依此倍率縮放，不需逐一修改版面檔案。
 */
object FontScaleManager {
    private const val PREFS = "font_scale_prefs"
    private const val KEY_SCALE = "font_scale"

    const val SCALE_SMALL = 0.9f
    const val SCALE_STANDARD = 1.0f
    const val SCALE_LARGE = 1.2f
    const val SCALE_EXTRA_LARGE = 1.5f

    /** 顯示於設定頁選單的選項，依序為（顯示文字, 倍率） */
    val OPTIONS = listOf(
        "小" to SCALE_SMALL,
        "標準" to SCALE_STANDARD,
        "大" to SCALE_LARGE,
        "特大" to SCALE_EXTRA_LARGE
    )

    fun getScale(context: Context): Float {
        val prefs = context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        return prefs.getFloat(KEY_SCALE, SCALE_STANDARD)
    }

    fun setScale(context: Context, scale: Float) {
        context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit().putFloat(KEY_SCALE, scale).apply()
    }

    fun currentLabel(context: Context): String {
        val scale = getScale(context)
        return OPTIONS.firstOrNull { it.second == scale }?.first ?: "標準"
    }
}
