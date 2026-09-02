/**
 * EmailAdapter.kt — 郵件警報列表 Adapter
 *
 * 所屬模組：adapter（RecyclerView 適配器）
 *
 * 本 Adapter 負責在 [EmailFragment] 中渲染可疑郵件警報列表。
 * 每個項目顯示：郵件圖示、寄件人、主旨、郵件預覽、風險標籤。
 *
 * 2026-08-17 改版：卡片版面與配色跟訊息分頁統一（見 [RiskCardStyle]），
 * 且**主旨放在名稱那一行、寄件人退到上面的來源行**——郵件是靠主旨辨識的，
 * 寄件人常常是一長串偽冒地址。主旨過長一律省略號、不換行。
 *
 * 點擊項目本身會就地展開一個操作面板：封鎖這個寄件人（所有項目都有）、
 * 查看完整內容／回報此寄件人為詐騙（只有透過信箱連接讀到的真實郵件才有，見 [onOpenDetail]／
 * [onReport]——真實 email 地址本身就是唯一識別碼，沒有社群帳號回報那種同名誤合併風險）。
 * 同時間只會有一筆展開（手風琴式），跟 [PhoneAdapter] 的互動模式一致。
 *
 * 支援兩種篩選，同時生效（見 [applyFilters]）：[filterByQuery]（寄件者／主旨／內文關鍵字）
 * 與 [filterByLevel]（風險等級）。供應商（Gmail／Outlook）篩選已於 2026-09-02 移除。
 */
package com.frauddetector.adapter

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.TextView
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.RecyclerView
import com.frauddetector.R
import com.frauddetector.data.EmailAlert
import com.frauddetector.ui.RiskCardStyle
import com.frauddetector.ui.RiskFilterChips
import com.google.android.material.chip.ChipGroup

class EmailAdapter(
    private var items: List<EmailAlert>,
    private val onBlock: (EmailAlert) -> Unit,
    private val onOpenDetail: (EmailAlert) -> Unit,
    private val onReport: (EmailAlert) -> Unit
) : RecyclerView.Adapter<EmailAdapter.VH>() {

    private var filteredItems = items.toList()
    private var currentQuery = ""
    private var currentLevel = RiskFilterChips.LEVEL_ALL
    private var expandedId: String? = null

    class VH(view: View) : RecyclerView.ViewHolder(view) {
        val ivAvatar: ImageView = view.findViewById(R.id.ivAvatar)
        val tvName: TextView = view.findViewById(R.id.tvItemName)
        val tvTime: TextView = view.findViewById(R.id.tvItemTime)
        val tvSource: TextView = view.findViewById(R.id.tvItemSource)
        val tvContentLabel: TextView = view.findViewById(R.id.tvItemContentLabel)
        val tvMsg: TextView = view.findViewById(R.id.tvItemMsg)
        val chipGroup: ChipGroup = view.findViewById(R.id.chipGroupTags)
        val row: View = view.findViewById(R.id.emailRow)
        val expandPanel: View = view.findViewById(R.id.expandPanel)
        val btnBlock: View = view.findViewById(R.id.btnEmailBlock)
        val btnDetail: View = view.findViewById(R.id.btnEmailDetail)
        val btnReport: View = view.findViewById(R.id.btnEmailReport)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val view = LayoutInflater.from(parent.context).inflate(R.layout.item_email, parent, false)
        return VH(view)
    }

    override fun onBindViewHolder(holder: VH, position: Int) {
        val item = filteredItems[position]

        // 名稱那一行放主旨、來源那一行放寄件人（跟訊息分頁的「名稱＝對話名、來源＝平台」對齊）
        holder.tvName.text = item.subject
        holder.tvTime.text = item.time
        holder.tvSource.text = item.sender
        holder.tvMsg.text = item.preview

        // Expand-in-place action panel（手風琴式，同時只展開一筆，封鎖/回報這個寄件人）
        val isExpanded = item.id == expandedId
        holder.expandPanel.visibility = if (isExpanded) View.VISIBLE else View.GONE
        holder.row.setOnClickListener {
            expandedId = if (isExpanded) null else item.id
            notifyDataSetChanged()
        }
        holder.btnBlock.setOnClickListener { onBlock(item) }

        // 只有透過信箱連接讀到的真實郵件（id 以 "mail_" 開頭）才能看完整內容／回報，
        // 通知擷取的項目沒有這個資料來源（且 sender 只是顯示名稱、不是唯一 email），按鈕隱藏
        val isRealMail = item.id.startsWith("mail_")
        holder.btnDetail.visibility = if (isRealMail) View.VISIBLE else View.GONE
        holder.btnDetail.setOnClickListener { onOpenDetail(item) }
        holder.btnReport.visibility = if (isRealMail) View.VISIBLE else View.GONE
        holder.btnReport.setOnClickListener { onReport(item) }

        // 整張卡依風險上色。展開的操作面板在卡片外層，跟著同一張卡的底色走。
        val palette = RiskCardStyle.of(item.level)
        RiskCardStyle.applyCard(holder.itemView, palette)
        RiskCardStyle.applyAvatar(holder.ivAvatar, palette)
        RiskCardStyle.applyText(
            palette,
            title = holder.tvName,
            source = holder.tvSource,
            time = holder.tvTime,
            contentLabel = holder.tvContentLabel,
            body = holder.tvMsg
        )
        RiskCardStyle.applyChips(holder.chipGroup, palette, item.tags)
    }

    override fun getItemCount() = filteredItems.size

    fun filterByQuery(query: String) {
        currentQuery = query.trim()
        applyFilters()
    }

    /** @param level [RiskFilterChips.LEVEL_ALL] 或 "high"/"mid"/"safe" */
    fun filterByLevel(level: String) {
        currentLevel = level
        applyFilters()
    }

    /**
     * 即時刷新（見 EmailFragment 的 InvalidationTracker 觀察者）可能頻繁呼叫到這裡，
     * 用 notifyDataSetChanged() 會讓整個列表閃爍、捲動位置跳掉，改用 DiffUtil 只更新真正變化的項目。
     */
    private fun applyFilters() {
        val newItems = items
            .filter { currentLevel == RiskFilterChips.LEVEL_ALL || it.level == currentLevel }
            .filter {
                currentQuery.isEmpty() ||
                    it.sender.contains(currentQuery, ignoreCase = true) ||
                    it.subject.contains(currentQuery, ignoreCase = true) ||
                    it.preview.contains(currentQuery, ignoreCase = true)
            }
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
