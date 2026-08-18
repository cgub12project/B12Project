/**
 * MessageAdapter.kt — 訊息警報列表 Adapter
 *
 * 所屬模組：adapter（RecyclerView 適配器）
 *
 * 本 Adapter 負責在 [MessagesFragment] 中渲染訊息警報列表。
 * 每個項目顯示：對話圖示、來源、時間、名稱、內容標籤、訊息預覽、風險標籤。
 * 2026-08-17 起整張卡依風險三級制上色（米白／塵土赤陶／深銹紅），
 * 配色統一由 [RiskCardStyle] 提供，不在這裡自行決定色碼。
 *
 * 支援兩種篩選方式：
 * - [filterByLevel]：依風險等級篩選（high/mid/safe/all）
 * - [filterByApp]：依來源平台篩選（LINE/簡訊/WhatsApp/Messenger/全部）
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
import com.frauddetector.data.AlertItem
import com.frauddetector.ui.RiskCardStyle
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
        val tvContentLabel: TextView = view.findViewById(R.id.tvItemContentLabel)
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

        // 群組直接把發話者放進內容標籤（「陳大富:」），私訊沿用通用的「訊息內容:」
        holder.tvContentLabel.text = if (item.speaker.isNotBlank()) {
            "${item.speaker}:"
        } else {
            holder.itemView.context.getString(R.string.msg_content_label)
        }

        // 整張卡依風險上色；來源平台（LINE/簡訊…）改由下方標籤呈現，
        // 不再用頭像的品牌色區分——頭像現在是全 App 統一的對話框圖示
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
