/**
 * RiskCardStyle.kt — 訊息／郵件列表卡片的風險配色
 *
 * 所屬模組：ui
 *
 * 2026-08-17 改版：卡片從「米白卡＋左側風險色條」改成「整張卡依風險上色」
 * （安全＝米白、可疑＝塵土赤陶、詐騙＝深銹紅，見 dev-notes/UI配色規範.txt）。
 *
 * 抽成共用物件而不是兩個 Adapter 各寫一份：訊息卡與郵件卡在設計稿上是同一張卡，
 * 之前兩邊各自維護一份 GradientDrawable 與色碼，已經出現過郵件的回報圖示跟電話頁
 * 不一致這種漂移。配色只寫在這裡一處，兩邊就不可能再走鐘。
 *
 * 色碼全部取自配色規範的十色，這裡不自創顏色。
 */
package com.frauddetector.ui

import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.view.View
import android.widget.ImageView
import android.widget.TextView
import com.google.android.material.chip.Chip
import com.google.android.material.chip.ChipGroup

object RiskCardStyle {

    private const val CREAM = "#FDFAF4"      // 柔和米白
    private const val PARCHMENT = "#F4F0E8"  // 暖羊皮紙
    private const val STEEL = "#4A7FA5"      // 鋼藍
    private const val SAGE = "#7A9E7E"       // 柔和鼠尾草綠
    private const val TERRACOTTA = "#C46B4A" // 塵土赤陶
    private const val RUST = "#A63D2F"       // 深銹紅
    private const val WARM_GREY = "#8C8480"  // 暖灰
    private const val GREY_LIGHT = "#C8C4C0" // 淺灰

    /**
     * 一張卡片用到的全部顏色。
     *
     * @param card 卡片底色
     * @param title 名稱（郵件是主旨）
     * @param body 內容預覽
     * @param muted 來源、時間、內容標籤
     * @param avatarCircle 左側頭像的圓底
     * @param avatarGlyph 頭像裡對話框／信封字形的著色
     * @param chipText 標籤文字色
     * @param chipBg 標籤底色
     */
    data class Palette(
        val card: Int,
        val title: Int,
        val body: Int,
        val muted: Int,
        val avatarCircle: Int,
        val avatarGlyph: Int,
        val chipText: Int,
        val chipBg: Int
    )

    /**
     * @param level "high" / "mid" / "unanalyzed" / 其餘皆視為安全
     *
     * 詐騙卡的文字色刻意用米白與羊皮紙、不是純白——純白壓在赤陶／銹紅上會刺眼，
     * 而且會脫離整套暖色系。
     */
    fun of(level: String): Palette = when (level) {
        "high" -> onColouredCard(Color.parseColor(RUST))
        "mid" -> onColouredCard(Color.parseColor(TERRACOTTA))
        "unanalyzed" -> Palette(
            // 「未分析」刻意跟安全卡的米白＋鋼藍拉開：灰底＋暖灰頭像，
            // 一眼就能跟「已判斷為安全」分開，不會被誤讀成安心的訊號。
            card = Color.parseColor(PARCHMENT),
            title = Color.parseColor(WARM_GREY),
            body = Color.parseColor(WARM_GREY),
            muted = Color.parseColor(GREY_LIGHT),
            avatarCircle = Color.parseColor(GREY_LIGHT),
            avatarGlyph = Color.parseColor(WARM_GREY),
            chipText = Color.parseColor(WARM_GREY),
            chipBg = withAlpha(Color.parseColor(WARM_GREY), 25)
        )
        else -> Palette(
            card = Color.parseColor(CREAM),
            title = Color.parseColor(WARM_GREY),
            body = Color.parseColor(WARM_GREY),
            muted = Color.parseColor(GREY_LIGHT),
            // 安全卡的頭像是鋼藍圓底＋白色字形，跟設計稿的訊息／郵件統一圖示一致
            avatarCircle = Color.parseColor(STEEL),
            avatarGlyph = Color.WHITE,
            chipText = Color.parseColor(SAGE),
            chipBg = withAlpha(Color.parseColor(SAGE), 25)
        )
    }

    /** 赤陶／銹紅這兩張彩色卡的配色規則一樣，只有底色不同 */
    private fun onColouredCard(cardColour: Int) = Palette(
        card = cardColour,
        title = Color.parseColor(CREAM),
        body = Color.parseColor(PARCHMENT),
        muted = withAlpha(Color.parseColor(PARCHMENT), 179),
        // 彩色卡上的頭像反過來：米白圓底，字形用卡片自己的風險色
        avatarCircle = Color.parseColor(CREAM),
        avatarGlyph = cardColour,
        // 標籤在彩色卡上要壓「暗」不能壓「亮」：先前用半透明白當底，疊在赤陶／銹紅上
        // 會變成很淺的粉膚色，米白字壓上去幾乎讀不到。改用半透明黑，底色會變成同色系
        // 的深一階，米白字才有足夠對比。
        chipText = Color.parseColor(CREAM),
        chipBg = withAlpha(Color.BLACK, 51)
    )

    private fun withAlpha(colour: Int, alpha: Int) =
        Color.argb(alpha, Color.red(colour), Color.green(colour), Color.blue(colour))

    /** 套用卡片底色與圓角。四角同圓角——舊版左側有風險色條所以左邊切齊，現在整張卡就是色條。 */
    fun applyCard(view: View, palette: Palette) {
        val radius = 16f * view.resources.displayMetrics.density
        view.background = GradientDrawable().apply {
            setColor(palette.card)
            cornerRadius = radius
        }
        // ViewHolder 會被回收，舊版畫左側色條用的 foreground 一定要清掉，
        // 不然新卡片上會殘留上一筆的色條
        view.foreground = null
    }

    /** 套用頭像的圓底與字形著色 */
    fun applyAvatar(imageView: ImageView, palette: Palette) {
        imageView.background = GradientDrawable().apply {
            shape = GradientDrawable.OVAL
            setColor(palette.avatarCircle)
        }
        imageView.setColorFilter(palette.avatarGlyph)
    }

    /** 套用卡片上各段文字的顏色 */
    fun applyText(
        palette: Palette,
        title: TextView,
        source: TextView,
        time: TextView,
        contentLabel: TextView,
        body: TextView
    ) {
        title.setTextColor(palette.title)
        source.setTextColor(palette.muted)
        time.setTextColor(palette.muted)
        contentLabel.setTextColor(palette.muted)
        body.setTextColor(palette.body)
    }

    /** 重建標籤列。傳入的 tags 為空時 ChipGroup 會是空的（不佔高度）。 */
    fun applyChips(chipGroup: ChipGroup, palette: Palette, tags: List<String>) {
        chipGroup.removeAllViews()
        tags.forEach { tag ->
            chipGroup.addView(Chip(chipGroup.context).apply {
                text = tag
                textSize = 10f
                isClickable = false
                chipMinHeight = 0f
                chipStartPadding = 4f
                chipEndPadding = 4f
                chipStrokeWidth = 0f
                setTextColor(palette.chipText)
                chipBackgroundColor = ColorStateList.valueOf(palette.chipBg)
            })
        }
    }
}
