/**
 * EvidenceAdapter.kt — 證據摘要列表 Adapter
 *
 * 所屬模組：adapter（RecyclerView 適配器）
 *
 * 本 Adapter 負責在 [AccountDetailActivity] 中渲染帳號威脅檔案的證據摘要列表。
 * 每個項目顯示：證據類型（嚴重/警告）、時間標記、證據描述文字。
 * 左側邊框以紅色（高嚴重度）或橘色（中嚴重度）標示。
 */
package com.frauddetector.adapter

import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import com.frauddetector.R
import com.frauddetector.data.EvidenceItem

class EvidenceAdapter(
    private val items: List<EvidenceItem>
) : RecyclerView.Adapter<EvidenceAdapter.VH>() {

    class VH(view: View) : RecyclerView.ViewHolder(view) {
        val tvType: TextView = view.findViewById(R.id.tvEvidenceType)
        val tvTime: TextView = view.findViewById(R.id.tvEvidenceTime)
        val tvText: TextView = view.findViewById(R.id.tvEvidenceText)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val view = LayoutInflater.from(parent.context).inflate(R.layout.item_evidence, parent, false)
        return VH(view)
    }

    override fun onBindViewHolder(holder: VH, position: Int) {
        val item = items[position]
        val dp = holder.itemView.resources.displayMetrics.density

        holder.tvType.text = item.type
        holder.tvTime.text = item.time
        holder.tvText.text = item.text

        val riskColor = if (item.typeClass == "r") Color.parseColor("#A63D2F") else Color.parseColor("#C46B4A")

        holder.tvType.setTextColor(riskColor)

        // Card with left border（左側貼合不留圓角，右側維持圓角）
        val rightRadius = 12f * dp
        val cardBg = GradientDrawable().apply {
            setColor(Color.parseColor("#FDFAF4"))
            cornerRadii = floatArrayOf(0f, 0f, rightRadius, rightRadius, rightRadius, rightRadius, 0f, 0f)
            setStroke((1 * dp).toInt(), Color.parseColor("#1AC8C4C0"))
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
    }

    override fun getItemCount() = items.size
}
