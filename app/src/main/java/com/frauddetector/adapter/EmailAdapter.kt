/**
 * EmailAdapter.kt — 郵件警報列表 Adapter
 *
 * 所屬模組：adapter（RecyclerView 適配器）
 *
 * 本 Adapter 負責在 [EmailFragment] 中渲染可疑郵件警報列表。
 * 每個項目顯示：郵件圖示、寄件人、主旨、郵件預覽、風險標籤。
 * 複用 item_message.xml 佈局，以統一的卡片樣式呈現。
 *
 * 支援依郵件供應商篩選：[filterByProvider]（全部/Gmail/Outlook）。
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
import com.frauddetector.data.EmailAlert
import com.google.android.material.chip.Chip
import com.google.android.material.chip.ChipGroup

class EmailAdapter(
    private var items: List<EmailAlert>,
    private val onClick: (EmailAlert) -> Unit
) : RecyclerView.Adapter<EmailAdapter.VH>() {

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
        val dp = holder.itemView.resources.displayMetrics.density

        holder.tvName.text = item.sender
        holder.tvTime.text = item.time
        holder.tvSource.text = item.subject
        holder.tvMsg.text = item.preview

        val riskColor = when (item.level) {
            "high" -> Color.parseColor("#FF3B30")
            "mid" -> Color.parseColor("#FF9500")
            else -> Color.parseColor("#34C759")
        }

        // Card background with left border
        val bg = GradientDrawable().apply {
            setColor(Color.WHITE)
            cornerRadius = 14f * dp
        }
        holder.itemView.background = bg
        holder.itemView.foreground = object : android.graphics.drawable.Drawable() {
            override fun draw(canvas: android.graphics.Canvas) {
                val paint = android.graphics.Paint().apply { color = riskColor }
                val pad = 3f * dp
                canvas.drawRoundRect(0f, 0f, pad, bounds.height().toFloat(), pad, pad, paint)
            }
            override fun setAlpha(a: Int) {}
            override fun setColorFilter(cf: android.graphics.ColorFilter?) {}
            @Deprecated("Deprecated in Java")
            override fun getOpacity() = android.graphics.PixelFormat.TRANSLUCENT
        }

        // Avatar
        val avatarBg = GradientDrawable().apply {
            shape = GradientDrawable.RECTANGLE
            cornerRadius = 12f * dp
            setColor(Color.parseColor("#1A5856D6"))
        }
        holder.ivAvatar.background = avatarBg
        holder.ivAvatar.setImageResource(android.R.drawable.sym_action_email)
        holder.ivAvatar.setColorFilter(Color.parseColor("#5856D6"))

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
                    tag == "安全" -> Color.parseColor("#34C759")
                    item.level == "high" -> Color.parseColor("#FF3B30")
                    else -> Color.parseColor("#FF9500")
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

    fun filterByProvider(provider: String) {
        filteredItems = if (provider == "全部") items else items.filter { it.provider == provider }
        notifyDataSetChanged()
    }
}
