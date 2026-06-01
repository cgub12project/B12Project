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
            "high" -> Color.parseColor("#FF3B30")
            "mid" -> Color.parseColor("#FF9500")
            else -> Color.parseColor("#34C759")
        }
        val bg = GradientDrawable().apply {
            setColor(Color.WHITE)
            cornerRadius = 14f * holder.itemView.resources.displayMetrics.density
        }
        holder.itemView.background = bg
        holder.itemView.apply {
            val pad = (3 * resources.displayMetrics.density).toInt()
            val borderBg = GradientDrawable().apply {
                setColor(Color.WHITE)
                cornerRadius = 14f * resources.displayMetrics.density
                setStroke(1, Color.parseColor("#10000000"))
            }
            background = borderBg
            // Use foreground for border-left effect
            foreground = object : android.graphics.drawable.Drawable() {
                override fun draw(canvas: android.graphics.Canvas) {
                    val paint = android.graphics.Paint().apply { color = borderColor }
                    val r = 14f * resources.displayMetrics.density
                    canvas.drawRoundRect(0f, 0f, pad.toFloat(), bounds.height().toFloat(), r, r, paint)
                }
                override fun setAlpha(alpha: Int) {}
                override fun setColorFilter(cf: android.graphics.ColorFilter?) {}
                @Deprecated("Deprecated in Java")
                override fun getOpacity() = android.graphics.PixelFormat.TRANSLUCENT
            }
        }

        // Avatar tint
        val avatarBg = GradientDrawable().apply {
            shape = GradientDrawable.RECTANGLE
            cornerRadius = 12f * holder.itemView.resources.displayMetrics.density
            when (item.app) {
                "LINE" -> setColor(Color.parseColor("#06C755"))
                "簡訊" -> setColor(Color.parseColor("#1A2196F3"))
                else -> setColor(Color.parseColor("#F0F0F5"))
            }
        }
        holder.ivAvatar.background = avatarBg
        holder.ivAvatar.setColorFilter(
            if (item.app == "LINE") Color.WHITE else Color.parseColor("#666666")
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
                    item.level == "high" && tag != "安全" -> Color.parseColor("#FF3B30")
                    item.level == "mid" && tag != "安全" -> Color.parseColor("#FF9500")
                    else -> Color.parseColor("#34C759")
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
        filteredItems = if (level == "all") items else items.filter { it.level == level }
        notifyDataSetChanged()
    }

    fun filterByApp(app: String) {
        filteredItems = if (app == "全部") items else items.filter { it.app == app }
        notifyDataSetChanged()
    }

    fun updateItems(newItems: List<AlertItem>) {
        items = newItems
        filteredItems = items.toList()
        notifyDataSetChanged()
    }
}
