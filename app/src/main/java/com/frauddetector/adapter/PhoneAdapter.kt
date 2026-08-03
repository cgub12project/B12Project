/**
 * PhoneAdapter.kt — 電話號碼列表 Adapter
 *
 * 所屬模組：adapter（RecyclerView 適配器）
 *
 * 本 Adapter 負責在 [PhoneFragment] 中渲染電話號碼詐騙資料庫列表。
 * 每個項目顯示：號碼、風險等級與詐騙類型、社群舉報次數。
 *
 * 點擊項目本身會就地展開一個操作面板（封鎖／回報／撥號／更多），
 * 同時間只會有一筆展開（手風琴式），點「更多」才會導向 [PhoneDetailActivity]。
 *
 * 支援即時搜尋篩選：[filter] 方法依號碼或類型過濾列表。
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
import com.frauddetector.data.PhoneRecord
import com.frauddetector.service.TaiwanPhoneFormat

class PhoneAdapter(
    private var items: List<PhoneRecord>,
    private val onMore: (PhoneRecord) -> Unit,
    private val onBlock: (PhoneRecord) -> Unit,
    private val onReport: (PhoneRecord) -> Unit,
    private val onDial: (PhoneRecord) -> Unit
) : RecyclerView.Adapter<PhoneAdapter.VH>() {

    private var filteredItems = items.toList()
    private var expandedId: String? = null

    class VH(view: View) : RecyclerView.ViewHolder(view) {
        val tvNum: TextView = view.findViewById(R.id.tvPhoneNum)
        val tvType: TextView = view.findViewById(R.id.tvPhoneType)
        val tvReport: TextView = view.findViewById(R.id.tvPhoneReport)
        val tvFormatWarning: TextView = view.findViewById(R.id.tvPhoneFormatWarning)
        val row: View = view.findViewById(R.id.phoneRow)
        val expandPanel: View = view.findViewById(R.id.expandPanel)
        val btnBlock: View = view.findViewById(R.id.btnPhoneBlock)
        val btnReport: View = view.findViewById(R.id.btnPhoneReport)
        val btnDial: View = view.findViewById(R.id.btnPhoneDial)
        val btnMore: View = view.findViewById(R.id.btnPhoneMore)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val view = LayoutInflater.from(parent.context).inflate(R.layout.item_phone, parent, false)
        return VH(view)
    }

    override fun onBindViewHolder(holder: VH, position: Int) {
        val item = filteredItems[position]
        val dp = holder.itemView.resources.displayMetrics.density

        holder.tvNum.text = formatPhoneDisplay(item.number)
        holder.tvType.text = "${item.riskLabel} · ${item.type}"
        holder.tvReport.text = "社群舉報 ${item.count} 次 · 最近 ${item.lastReport}"

        val riskColor = when (item.riskLevel) {
            "high" -> Color.parseColor("#A63D2F")
            "mid" -> Color.parseColor("#C46B4A")
            else -> Color.parseColor("#7A9E7E")
        }
        holder.tvType.setTextColor(riskColor)

        // 非常規台灣電話格式提示（跟風險等級/社群舉報無關，純號碼格式規則比對）
        holder.tvFormatWarning.visibility =
            if (TaiwanPhoneFormat.isAbnormal(item.number)) View.VISIBLE else View.GONE

        holder.itemView.background = GradientDrawable().apply {
            setColor(Color.parseColor("#FDFAF4"))
            cornerRadius = 14f * dp
            setStroke((1 * dp).toInt(), Color.parseColor("#1AC8C4C0"))
        }

        // Expand-in-place action panel（手風琴式，同時只展開一筆）
        val isExpanded = item.id == expandedId
        holder.expandPanel.visibility = if (isExpanded) View.VISIBLE else View.GONE
        holder.row.setOnClickListener {
            expandedId = if (isExpanded) null else item.id
            notifyDataSetChanged()
        }

        holder.btnBlock.setOnClickListener { onBlock(item) }
        holder.btnReport.setOnClickListener { onReport(item) }
        holder.btnDial.setOnClickListener { onDial(item) }
        holder.btnMore.setOnClickListener { onMore(item) }
    }

    override fun getItemCount() = filteredItems.size

    fun filter(query: String) {
        filteredItems = if (query.isBlank()) items
        else items.filter { it.number.contains(query) || it.type.contains(query) }
        notifyDataSetChanged()
    }

    fun updateItems(newItems: List<PhoneRecord>) {
        items = newItems
        filteredItems = items.toList()
        notifyDataSetChanged()
    }

    fun removeItem(id: String) {
        items = items.filterNot { it.id == id }
        filteredItems = filteredItems.filterNot { it.id == id }
        notifyDataSetChanged()
    }
}

/**
 * 電話號碼顯示分組，用細空格（U+2009）分隔（不是一般空格，只留一點呼吸空間，
 * 不會整格空出來）：
 * - 手機／付費服務號碼（09 或 0800/0809 開頭，共 10 碼）：4-3-3，例如 0912 345 678
 * - 其他國內號碼（0 開頭，8-10 碼，市話）：簡化成「前 2 碼＋其餘每 4 碼一組」，
 *   例如 02 2345 6789——不是精確對照每個縣市的真實區碼長度（例如 037 苗栗其實是
 *   3 碼區碼），只是為了讓數字看起來有規律好讀，不影響實際撥打/儲存的號碼。
 * - +886 國際格式或其他一律視為國外的號碼：原樣顯示，不強行分組（各國格式差異太大）
 */
private fun formatPhoneDisplay(number: String): String {
    val thinSpace = " "
    val digits = number.filter { it.isDigit() }

    val isMobileOrService = digits.length == 10 &&
        (digits.startsWith("09") || digits.startsWith("0800") || digits.startsWith("0809"))
    if (isMobileOrService) {
        return "${digits.substring(0, 4)}$thinSpace${digits.substring(4, 7)}$thinSpace${digits.substring(7, 10)}"
    }

    val isLikelyLandline = digits.length in 8..10 && digits.startsWith("0") && !number.trim().startsWith("+")
    if (isLikelyLandline) {
        val area = digits.substring(0, 2)
        val rest = digits.substring(2).chunked(4).joinToString(thinSpace)
        return "$area$thinSpace$rest"
    }

    return number
}
