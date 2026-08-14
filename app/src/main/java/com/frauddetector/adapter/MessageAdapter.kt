/**
 * MessageAdapter.kt — 訊息警報列表 Adapter
 *
 * 所屬模組：adapter（RecyclerView 適配器）
 *
 * 本 Adapter 負責在 [MessagesFragment] 中渲染訊息警報列表。
 * 每個項目顯示：來源 App 圖示、傳送者名稱、時間、訊息預覽、風險標籤。
 * 左側邊框以風險三級制色彩編碼：紅色（高危）、橘色（可疑）、綠色（安全）。
 *
 * 支援兩種篩選方式：
 * - [filterByLevel]：依風險等級篩選（high/mid/safe/all）
 * - [filterByApp]：依來源平台篩選（LINE/簡訊/WhatsApp/Messenger/全部）
 */
package com.frauddetector.adapter

import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.TextView
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.RecyclerView
import com.frauddetector.R
import com.frauddetector.data.AlertItem
import com.google.android.material.chip.Chip
import com.google.android.material.chip.ChipGroup

class MessageAdapter(
    private var items: List<AlertItem>,
    private val onClick: (AlertItem) -> Unit
) : RecyclerView.Adapter<MessageAdapter.VH>() {

    private var filteredItems = items.toList()
    private var currentLevel = "all"
    private var currentApp = "全部"

    class VH(view: View) : RecyclerView.ViewHolder(view) {
        val ivAvatar: ImageView = view.findViewById(R.id.ivAvatar)
        val tvName: TextView = view.findViewById(R.id.tvItemName)
        val tvTime: TextView = view.findViewById(R.id.tvItemTime)
        val tvSource: TextView = view.findViewById(R.id.tvItemSource)
        val tvMsg: TextView = view.findViewById(R.id.tvItemMsg)
        val chipGroup: ChipGroup = view.findViewById(R.id.chipGroupTags)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val view = LayoutInflater.from(parent.context).inflate(R.layout.item_message, parent, false)
        return VH(view)
    }

    override fun onBindViewHolder(holder: VH, position: Int) {
        val item = filteredItems[position]
        holder.tvName.text = item.name
        holder.tvTime.text = item.time
        holder.tvSource.text = item.source
        holder.tvMsg.text = item.message

        // Left border color based on risk level
        val borderColor = when (item.level) {
            "high" -> Color.parseColor("#A63D2F")
            "mid" -> Color.parseColor("#C46B4A")
            else -> Color.parseColor("#7A9E7E")
        }
        holder.itemView.apply {
            val dp = resources.displayMetrics.density
            val pad = (3 * dp).toInt()
            // 卡片左側要跟色條貼合、不能有圓角，右側維持圓角
            val rightRadius = 14f * dp
            val cardBg = GradientDrawable().apply {
                setColor(Color.parseColor("#FDFAF4"))
                cornerRadii = floatArrayOf(0f, 0f, rightRadius, rightRadius, rightRadius, rightRadius, 0f, 0f)
                setStroke(1, Color.parseColor("#10000000"))
            }
            background = cardBg
            // Use foreground for border-left effect（純方形，不畫圓角，緊貼卡片左邊）
            foreground = object : android.graphics.drawable.Drawable() {
                override fun draw(canvas: android.graphics.Canvas) {
                    val paint = android.graphics.Paint().apply { color = borderColor }
                    canvas.drawRect(0f, 0f, pad.toFloat(), bounds.height().toFloat(), paint)
                }
                override fun setAlpha(alpha: Int) {}
                override fun setColorFilter(cf: android.graphics.ColorFilter?) {}
                @Deprecated("Deprecated in Java")
                override fun getOpacity() = android.graphics.PixelFormat.TRANSLUCENT
            }
        }

        // Avatar tint（LINE/簡訊等品牌色維持不變，只調整中性色調）
        val avatarBg = GradientDrawable().apply {
            shape = GradientDrawable.RECTANGLE
            cornerRadius = 12f * holder.itemView.resources.displayMetrics.density
            when (item.app) {
                "LINE" -> setColor(Color.parseColor("#06C755"))
                "簡訊" -> setColor(Color.parseColor("#1A4A7FA5"))
                else -> setColor(Color.parseColor("#F0EDE8"))
            }
        }
        holder.ivAvatar.background = avatarBg
        holder.ivAvatar.setColorFilter(
            if (item.app == "LINE") Color.WHITE else Color.parseColor("#8C8480")
        )

        // Tags
        holder.chipGroup.removeAllViews()
        item.tags.forEach { tag ->
            val chip = Chip(holder.chipGroup.context).apply {
                text = tag
                textSize = 10f
                isClickable = false
                chipMinHeight = 0f
                chipStartPadding = 4f
                chipEndPadding = 4f
                val tagColor = when {
                    item.level == "high" && tag != "安全" -> Color.parseColor("#A63D2F")
                    item.level == "mid" && tag != "安全" -> Color.parseColor("#C46B4A")
                    else -> Color.parseColor("#7A9E7E")
                }
                setTextColor(tagColor)
                chipBackgroundColor = android.content.res.ColorStateList.valueOf(
                    Color.argb(25, Color.red(tagColor), Color.green(tagColor), Color.blue(tagColor))
                )
                chipStrokeWidth = 0f
            }
            holder.chipGroup.addView(chip)
        }

        holder.itemView.setOnClickListener { onClick(item) }
    }

    override fun getItemCount() = filteredItems.size

    fun filterByLevel(level: String) {
        currentLevel = level
        applyFilters()
    }

    fun filterByApp(app: String) {
        currentApp = app
        applyFilters()
    }

    /**
     * 依目前的等級/平台篩選條件重新計算 filteredItems，並用 DiffUtil 局部更新畫面。
     * 即時刷新（見 MessagesFragment 的 InvalidationTracker 觀察者）可能頻繁呼叫到這裡，
     * 用 notifyDataSetChanged() 會讓整個列表閃爍、捲動位置跳掉，改用 DiffUtil 只更新真正變化的項目。
     */
    private fun applyFilters() {
        val newItems = items
            .filter { currentLevel == "all" || it.level == currentLevel }
            .filter { currentApp == "全部" || it.app == currentApp }
        submitFilteredItems(newItems)
    }

    private fun submitFilteredItems(newItems: List<AlertItem>) {
        val diffResult = DiffUtil.calculateDiff(object : DiffUtil.Callback() {
            override fun getOldListSize() = filteredItems.size
            override fun getNewListSize() = newItems.size
            override fun areItemsTheSame(oldItemPosition: Int, newItemPosition: Int) =
                filteredItems[oldItemPosition].id == newItems[newItemPosition].id
            override fun areContentsTheSame(oldItemPosition: Int, newItemPosition: Int) =
                filteredItems[oldItemPosition] == newItems[newItemPosition]
        })
        filteredItems = newItems
        diffResult.dispatchUpdatesTo(this)
    }

    fun updateItems(newItems: List<AlertItem>) {
        items = newItems
        applyFilters()
    }

    fun getItemAt(position: Int): AlertItem = filteredItems[position]

    fun getAllItems(): List<AlertItem> = items

    fun removeItem(id: String) {
        items = items.filterNot { it.id == id }
        filteredItems = filteredItems.filterNot { it.id == id }
        notifyDataSetChanged()
    }
}
