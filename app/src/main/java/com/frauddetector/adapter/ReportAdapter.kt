/**
 * ReportAdapter.kt — 社群回報記錄列表 Adapter
 *
 * 所屬模組：adapter（RecyclerView 適配器）
 *
 * 本 Adapter 負責在 [PhoneDetailActivity] 中渲染電話號碼的社群回報記錄列表。
 * 每個項目顯示：回報者名稱、回報時間、詐騙類型標籤、回報描述。
 * 詐騙類型標籤以紅色（嚴重）或橘色（警告）膠囊樣式呈現。
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
import com.frauddetector.data.CommunityReport

class ReportAdapter(
    private val items: List<CommunityReport>
) : RecyclerView.Adapter<ReportAdapter.VH>() {

    class VH(view: View) : RecyclerView.ViewHolder(view) {
        val tvUser: TextView = view.findViewById(R.id.tvReportUser)
        val tvTime: TextView = view.findViewById(R.id.tvReportTime)
        val tvType: TextView = view.findViewById(R.id.tvReportType)
        val tvDesc: TextView = view.findViewById(R.id.tvReportDesc)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val view = LayoutInflater.from(parent.context).inflate(R.layout.item_report, parent, false)
        return VH(view)
    }

    override fun onBindViewHolder(holder: VH, position: Int) {
        val item = items[position]
        val dp = holder.itemView.resources.displayMetrics.density

        holder.tvUser.text = item.user
        holder.tvTime.text = item.time
        holder.tvType.text = item.type
        holder.tvDesc.text = item.desc

        val riskColor = if (item.typeClass == "r") Color.parseColor("#A63D2F") else Color.parseColor("#C46B4A")
        val riskBg = Color.argb(25, Color.red(riskColor), Color.green(riskColor), Color.blue(riskColor))

        // Type badge
        holder.tvType.setTextColor(riskColor)
        val typeBg = GradientDrawable().apply {
            cornerRadius = 20f * dp
            setColor(riskBg)
        }
        holder.tvType.background = typeBg

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
