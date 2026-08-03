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
    private var currentProvider = "全部"
    private var currentQuery = ""

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
            "high" -> Color.parseColor("#A63D2F")
            "mid" -> Color.parseColor("#C46B4A")
            else -> Color.parseColor("#7A9E7E")
        }

        // Card background with left border（左側貼合不留圓角，右側維持圓角）
        val rightRadius = 14f * dp
        val cardBg = GradientDrawable().apply {
            setColor(Color.parseColor("#FDFAF4"))
            cornerRadii = floatArrayOf(0f, 0f, rightRadius, rightRadius, rightRadius, rightRadius, 0f, 0f)
        }
        holder.itemView.background = cardBg
        holder.itemView.foreground = object : android.graphics.drawable.Drawable() {
            override fun draw(canvas: android.graphics.Canvas) {
                val paint = android.graphics.Paint().apply { color = riskColor }
                val pad = 3f * dp
                canvas.drawRect(0f, 0f, pad, bounds.height().toFloat(), paint)
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
            setColor(Color.parseColor("#1A4A7FA5"))
        }
        holder.ivAvatar.background = avatarBg
        holder.ivAvatar.setImageResource(android.R.drawable.sym_action_email)
        holder.ivAvatar.setColorFilter(Color.parseColor("#4A7FA5"))

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
                val tagColor = when (item.level) {
                    "high" -> Color.parseColor("#A63D2F")
                    "mid" -> Color.parseColor("#C46B4A")
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

    fun filterByProvider(provider: String) {
        currentProvider = provider
        applyFilters()
    }

    fun filterByQuery(query: String) {
        currentQuery = query.trim()
        applyFilters()
    }

    private fun applyFilters() {
        filteredItems = items
            .filter { currentProvider == "全部" || it.provider == currentProvider }
            .filter {
                currentQuery.isEmpty() ||
                    it.sender.contains(currentQuery, ignoreCase = true) ||
                    it.subject.contains(currentQuery, ignoreCase = true) ||
                    it.preview.contains(currentQuery, ignoreCase = true)
            }
        notifyDataSetChanged()
    }

    fun updateItems(newItems: List<EmailAlert>) {
        items = newItems
        applyFilters()
    }

    fun getItemAt(position: Int): EmailAlert = filteredItems[position]

    fun removeItem(id: String) {
        items = items.filterNot { it.id == id }
        filteredItems = filteredItems.filterNot { it.id == id }
        notifyDataSetChanged()
    }
}
