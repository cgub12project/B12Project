/**
 * ChatAdapter.kt — 階段式聊天氣泡列表 Adapter
 *
 * 所屬模組：adapter（RecyclerView 適配器）
 *
 * 本 Adapter 負責在 [ThreadDetailActivity] 中渲染對話詳情的聊天記錄。
 * 採用「展平」策略：將 [ChatPhase] 列表轉換為混合類型的 [ChatRow] 列表，
 * 包含兩種項目類型：
 * - [ChatRow.PhaseDivider]：階段分隔線（如「建立信任期」→「引導匯款」），
 *   以紅色（高危）或橘色（可疑）標示
 * - [ChatRow.Message]：個別聊天訊息氣泡，支援：
 *   - 自己/對方的左右對齊排列
 *   - AI 風險標記（高危紅色邊框、可疑橘色邊框）
 *   - 風險原因標籤（如「假獲利保證」「製造緊迫感」）
 */
package com.frauddetector.adapter

import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import com.frauddetector.R
import com.frauddetector.data.ChatMessage
import com.frauddetector.data.ChatPhase

/**
 * 將 ChatPhase 列表展平為 adapter 可用的 row 列表。
 * 每個 phase 會先插入一個 divider row，再接該 phase 的所有 messages。
 */
/**
 * 聊天列表的密封類別，代表兩種項目類型。
 * 將 ChatPhase 列表「展平」為 Adapter 可直接使用的線性列表。
 */
sealed class ChatRow {
    /** 階段分隔線項目（顯示階段名稱與顏色標記） */
    data class PhaseDivider(val phase: ChatPhase) : ChatRow()
    /** 聊天訊息氣泡項目 */
    data class Message(val msg: ChatMessage) : ChatRow()
}

/**
 * 階段式聊天 Adapter。
 * 接收 [ChatPhase] 列表，展平為 [ChatRow] 列表後供 RecyclerView 使用。
 *
 * @param phases 聊天階段列表，每個階段包含該階段的所有訊息
 */
class ChatAdapter(phases: List<ChatPhase>) : RecyclerView.Adapter<ChatAdapter.VH>() {

    /** 展平後的聊天列表：每個 phase 先放一個分隔線，再放該階段的所有訊息 */
    private val rows: List<ChatRow> = phases.flatMap { phase ->
        listOf(ChatRow.PhaseDivider(phase)) + phase.messages.map { ChatRow.Message(it) }
    }

    class VH(view: View) : RecyclerView.ViewHolder(view) {
        val phaseDivider: LinearLayout = view.findViewById(R.id.phaseDivider)
        val tvPhaseLabel: TextView = view.findViewById(R.id.tvPhaseLabel)
        val bubbleContainer: LinearLayout = view.findViewById(R.id.bubbleContainer)
        val metaRow: LinearLayout = view.findViewById(R.id.metaRow)
        val tvSenderName: TextView = view.findViewById(R.id.tvSenderName)
        val tvMsgTime: TextView = view.findViewById(R.id.tvMsgTime)
        val tvBubbleText: TextView = view.findViewById(R.id.tvBubbleText)
        val tvReasonChip: TextView = view.findViewById(R.id.tvReasonChip)
        val tvMyTime: TextView = view.findViewById(R.id.tvMyTime)
        val chatRow: LinearLayout = view.findViewById(R.id.chatRow)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val view = LayoutInflater.from(parent.context).inflate(R.layout.item_chat_bubble, parent, false)
        return VH(view)
    }

    override fun onBindViewHolder(holder: VH, position: Int) {
        val dp = holder.itemView.resources.displayMetrics.density
        val row = rows[position]

        when (row) {
            is ChatRow.PhaseDivider -> {
                holder.phaseDivider.visibility = View.VISIBLE
                holder.bubbleContainer.visibility = View.GONE

                val phase = row.phase
                holder.tvPhaseLabel.text = phase.label
                val (textColor, bgColor) = when (phase.phaseClass) {
                    "r" -> Color.parseColor("#FF3B30") to Color.parseColor("#1AFF3B30")
                    "a" -> Color.parseColor("#FF9500") to Color.parseColor("#1AFF9500")
                    else -> Color.parseColor("#2196F3") to Color.parseColor("#1A2196F3")
                }
                holder.tvPhaseLabel.setTextColor(textColor)
                val labelBg = GradientDrawable().apply {
                    cornerRadius = 20f * dp
                    setColor(bgColor)
                }
                holder.tvPhaseLabel.background = labelBg
            }
            is ChatRow.Message -> {
                holder.phaseDivider.visibility = View.GONE
                holder.bubbleContainer.visibility = View.VISIBLE

                val msg = row.msg
                val isMe = msg.who == "me"

                // Alignment
                holder.chatRow.gravity = if (isMe) Gravity.END else Gravity.START
                val lp = holder.bubbleContainer.layoutParams as LinearLayout.LayoutParams
                lp.gravity = if (isMe) Gravity.END else Gravity.START
                holder.bubbleContainer.layoutParams = lp

                // Meta row
                if (isMe) {
                    holder.metaRow.visibility = View.GONE
                    holder.tvMyTime.visibility = View.VISIBLE
                    holder.tvMyTime.text = msg.time
                    val myTimeLp = holder.tvMyTime.layoutParams as LinearLayout.LayoutParams
                    myTimeLp.gravity = Gravity.END
                    holder.tvMyTime.layoutParams = myTimeLp
                } else {
                    holder.metaRow.visibility = View.VISIBLE
                    holder.tvSenderName.text = msg.name
                    holder.tvMsgTime.text = msg.time
                    holder.tvMyTime.visibility = View.GONE
                }

                // Bubble text
                holder.tvBubbleText.text = msg.text

                // Bubble style
                val radius = 16f * dp
                val smallRadius = 4f * dp
                val bubbleBg = GradientDrawable()

                if (isMe) {
                    bubbleBg.cornerRadii = floatArrayOf(
                        radius, radius, smallRadius, smallRadius,
                        radius, radius, radius, radius
                    )
                    bubbleBg.setColor(Color.parseColor("#2196F3"))
                    holder.tvBubbleText.setTextColor(Color.WHITE)
                } else {
                    bubbleBg.cornerRadii = floatArrayOf(
                        smallRadius, smallRadius, radius, radius,
                        radius, radius, radius, radius
                    )
                    when (msg.flag) {
                        "high" -> {
                            bubbleBg.setColor(Color.parseColor("#0FFF3B30"))
                            bubbleBg.setStroke((1 * dp).toInt(), Color.parseColor("#40FF3B30"))
                        }
                        "mid" -> {
                            bubbleBg.setColor(Color.parseColor("#0FFF9500"))
                            bubbleBg.setStroke((1 * dp).toInt(), Color.parseColor("#40FF9500"))
                        }
                        else -> {
                            bubbleBg.setColor(Color.WHITE)
                            bubbleBg.setStroke((1 * dp).toInt(), Color.parseColor("#1A3C3C43"))
                        }
                    }
                    holder.tvBubbleText.setTextColor(Color.parseColor("#1C1C1E"))
                }
                holder.tvBubbleText.background = bubbleBg

                // Reason chip
                if (msg.reason != null) {
                    holder.tvReasonChip.visibility = View.VISIBLE
                    holder.tvReasonChip.text = msg.reason
                    val (chipText, chipBg) = when (msg.reasonClass) {
                        "r" -> Color.parseColor("#FF3B30") to Color.parseColor("#1AFF3B30")
                        else -> Color.parseColor("#FF9500") to Color.parseColor("#1AFF9500")
                    }
                    holder.tvReasonChip.setTextColor(chipText)
                    val chipDrawable = GradientDrawable().apply {
                        cornerRadius = 20f * dp
                        setColor(chipBg)
                    }
                    holder.tvReasonChip.background = chipDrawable
                } else {
                    holder.tvReasonChip.visibility = View.GONE
                }
            }
        }
    }

    override fun getItemCount() = rows.size
}
