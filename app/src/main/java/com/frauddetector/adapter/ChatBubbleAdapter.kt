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
import com.frauddetector.db.CapturedNotification
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class ChatBubbleAdapter(
    private val messages: List<CapturedNotification>,
    private val onMessageClick: (CapturedNotification) -> Unit
) : RecyclerView.Adapter<ChatBubbleAdapter.VH>() {

    private val sdf = SimpleDateFormat("MM/dd HH:mm", Locale.getDefault())

    class VH(view: View) : RecyclerView.ViewHolder(view) {
        val chatRow: LinearLayout = view.findViewById(R.id.chatRow)
        val phaseDivider: LinearLayout = view.findViewById(R.id.phaseDivider)
        val tvPhaseLabel: TextView = view.findViewById(R.id.tvPhaseLabel)
        val bubbleContainer: LinearLayout = view.findViewById(R.id.bubbleContainer)
        val metaRow: LinearLayout = view.findViewById(R.id.metaRow)
        val tvSenderName: TextView = view.findViewById(R.id.tvSenderName)
        val tvMsgTime: TextView = view.findViewById(R.id.tvMsgTime)
        val tvBubbleText: TextView = view.findViewById(R.id.tvBubbleText)
        val tvReasonChip: TextView = view.findViewById(R.id.tvReasonChip)
        val tvMyTime: TextView = view.findViewById(R.id.tvMyTime)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val view = LayoutInflater.from(parent.context).inflate(R.layout.item_chat_bubble, parent, false)
        return VH(view)
    }

    override fun onBindViewHolder(holder: VH, position: Int) {
        val msg = messages[position]
        val timeStr = sdf.format(Date(msg.timestamp))

        // Show date divider for first message or when date changes
        if (position == 0 || isDifferentDay(messages[position - 1].timestamp, msg.timestamp)) {
            holder.phaseDivider.visibility = View.VISIBLE
            val dateFmt = SimpleDateFormat("yyyy/MM/dd", Locale.getDefault())
            holder.tvPhaseLabel.text = dateFmt.format(Date(msg.timestamp))
            holder.tvPhaseLabel.setTextColor(Color.parseColor("#8C8480"))
        } else {
            holder.phaseDivider.visibility = View.GONE
        }

        // All captured notifications are from others ("them" style)
        holder.chatRow.gravity = Gravity.START
        holder.bubbleContainer.gravity = Gravity.START
        holder.metaRow.visibility = View.VISIBLE
        holder.tvSenderName.text = msg.sender
        holder.tvMsgTime.text = timeStr
        holder.tvMyTime.visibility = View.GONE

        holder.tvBubbleText.text = msg.content

        // Bubble background
        val dp = holder.itemView.resources.displayMetrics.density
        val bubbleBg = GradientDrawable().apply {
            setColor(Color.parseColor("#F0EDE8"))
            cornerRadii = floatArrayOf(
                4f * dp, 4f * dp,   // top-left
                14f * dp, 14f * dp, // top-right
                14f * dp, 14f * dp, // bottom-right
                14f * dp, 14f * dp  // bottom-left
            )
        }
        holder.tvBubbleText.background = bubbleBg
        holder.tvBubbleText.setTextColor(Color.parseColor("#2C2825"))
        holder.tvBubbleText.setOnClickListener { onMessageClick(msg) }

        // No AI analysis yet
        holder.tvReasonChip.visibility = View.GONE
    }

    override fun getItemCount() = messages.size

    private fun isDifferentDay(ts1: Long, ts2: Long): Boolean {
        val fmt = SimpleDateFormat("yyyyMMdd", Locale.getDefault())
        return fmt.format(Date(ts1)) != fmt.format(Date(ts2))
    }
}
