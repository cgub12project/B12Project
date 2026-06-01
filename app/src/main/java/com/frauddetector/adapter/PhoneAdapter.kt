/**
 * PhoneAdapter.kt — 電話號碼列表 Adapter
 *
 * 所屬模組：adapter（RecyclerView 適配器）
 *
 * 本 Adapter 負責在 [PhoneFragment] 中渲染電話號碼詐騙資料庫列表。
 * 每個項目顯示：電話圖示、號碼、風險等級標籤、詐騙類型、社群舉報次數。
 * 左側邊框與風險膠囊以三級制色彩編碼。
 *
 * 支援即時搜尋篩選：[filter] 方法依號碼或類型過濾列表。
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
import com.frauddetector.data.PhoneRecord

class PhoneAdapter(
    private var items: List<PhoneRecord>,
    private val onClick: (PhoneRecord) -> Unit
) : RecyclerView.Adapter<PhoneAdapter.VH>() {

    private var filteredItems = items.toList()

    class VH(view: View) : RecyclerView.ViewHolder(view) {
        val ivAvatar: ImageView = view.findViewById(R.id.ivPhoneAvatar)
        val tvNum: TextView = view.findViewById(R.id.tvPhoneNum)
        val tvType: TextView = view.findViewById(R.id.tvPhoneType)
        val tvReport: TextView = view.findViewById(R.id.tvPhoneReport)
        val tvBadge: TextView = view.findViewById(R.id.tvPhoneBadge)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val view = LayoutInflater.from(parent.context).inflate(R.layout.item_phone, parent, false)
        return VH(view)
    }

    override fun onBindViewHolder(holder: VH, position: Int) {
        val item = filteredItems[position]
        val dp = holder.itemView.resources.displayMetrics.density

        holder.tvNum.text = item.number
        holder.tvType.text = "${item.riskLabel} · ${item.type}"
        holder.tvReport.text = "社群舉報 ${item.count} 次 · 最近 ${item.lastReport}"

        val riskColor = when (item.riskLevel) {
            "high" -> Color.parseColor("#FF3B30")
            "mid" -> Color.parseColor("#FF9500")
            else -> Color.parseColor("#34C759")
        }

        // Left border
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

        // Avatar background
        val avatarBg = GradientDrawable().apply {
            shape = GradientDrawable.RECTANGLE
            cornerRadius = 12f * dp
            setColor(Color.argb(25, Color.red(riskColor), Color.green(riskColor), Color.blue(riskColor)))
        }
        holder.ivAvatar.background = avatarBg
        holder.ivAvatar.setColorFilter(riskColor)

        // Risk badge
        holder.tvBadge.text = item.riskLabel
        holder.tvBadge.setTextColor(Color.WHITE)
        val badgeBg = GradientDrawable().apply {
            cornerRadius = 20f * dp
            setColor(riskColor)
        }
        holder.tvBadge.background = badgeBg

        holder.itemView.setOnClickListener { onClick(item) }
    }

    override fun getItemCount() = filteredItems.size

    fun filter(query: String) {
        filteredItems = if (query.isBlank()) items
        else items.filter { it.number.contains(query) || it.type.contains(query) }
        notifyDataSetChanged()
    }
}
