package com.frauddetector.ui.detail

import android.content.Intent
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.frauddetector.R
import com.frauddetector.adapter.ChatAdapter
import com.frauddetector.data.SampleData
import com.google.android.material.chip.Chip
import com.google.android.material.chip.ChipGroup

class ThreadDetailActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_thread_detail)

        val threadId = intent.getStringExtra("threadId") ?: "invest"
        val thread = SampleData.getThreads()[threadId] ?: return

        // Back
        findViewById<LinearLayout>(R.id.btnBackToMessages).setOnClickListener { finish() }

        // Header info
        findViewById<TextView>(R.id.tvThreadGroup).text =
            "${thread.app} ${if (thread.group != null) "· ${thread.group}" else "· PRIVATE"}"
        findViewById<TextView>(R.id.tvThreadSender).text = thread.sender

        // Risk pill
        val tvRiskPill = findViewById<TextView>(R.id.tvRiskPill)
        val isHigh = thread.riskLevel == "high"
        tvRiskPill.text = if (isHigh) "HIGH ${thread.riskScore}" else "SUSPECT ${thread.riskScore}"
        val pillColor = if (isHigh) Color.parseColor("#FF3B30") else Color.parseColor("#FF9500")
        tvRiskPill.setTextColor(Color.WHITE)
        val pillBg = GradientDrawable().apply {
            cornerRadius = 20f * resources.displayMetrics.density
            setColor(pillColor)
        }
        tvRiskPill.background = pillBg
        tvRiskPill.setOnClickListener {
            val intent = Intent(this, AccountDetailActivity::class.java)
            intent.putExtra("threadId", threadId)
            startActivity(intent)
        }

        // Summary stats
        val totalMsgs = thread.phases.sumOf { it.messages.size }
        findViewById<TextView>(R.id.tvThreadScore).text = thread.suspectMsgs.toString()
        findViewById<TextView>(R.id.tvThreadScore).setTextColor(Color.parseColor("#FF3B30"))
        findViewById<TextView>(R.id.tvThreadMsgs).text = "${totalMsgs} 則"
        findViewById<TextView>(R.id.tvThreadDays).text = "${thread.days} 天"
        findViewById<TextView>(R.id.tvThreadDays).setTextColor(Color.parseColor("#FF9500"))

        // Pattern tags
        val chipGroup = findViewById<ChipGroup>(R.id.chipGroupPatterns)
        chipGroup.removeAllViews()
        thread.tags.forEach { tag ->
            val chip = Chip(this).apply {
                text = tag
                textSize = 10f
                isClickable = false
                setTextColor(Color.parseColor("#FF3B30"))
                chipBackgroundColor = android.content.res.ColorStateList.valueOf(
                    Color.parseColor("#1AFF3B30")
                )
                chipStrokeWidth = 0f
            }
            chipGroup.addView(chip)
        }

        // Chat messages RecyclerView
        val rv = findViewById<RecyclerView>(R.id.rvChatMessages)
        rv.layoutManager = LinearLayoutManager(this)
        rv.adapter = ChatAdapter(thread.phases)
    }
}
