package com.frauddetector.ui.main

import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageButton
import android.widget.TextView
import android.widget.Toast
import androidx.fragment.app.Fragment
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.frauddetector.R
import com.frauddetector.adapter.MessageAdapter
import com.frauddetector.data.SampleData
import com.frauddetector.ui.detail.ThreadDetailActivity
import com.google.android.material.chip.ChipGroup

class MessagesFragment : Fragment() {

    private lateinit var adapter: MessageAdapter
    private var currentLevel = "all"

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View? {
        return inflater.inflate(R.layout.fragment_messages, container, false)
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        val items = SampleData.getAlertItems()
        val tvHigh = view.findViewById<TextView>(R.id.tvHighCount)
        val tvMid = view.findViewById<TextView>(R.id.tvMidCount)
        val tvSafe = view.findViewById<TextView>(R.id.tvSafeCount)

        // 更新統計數字
        tvHigh.text = items.count { it.level == "high" }.toString()
        tvMid.text = items.count { it.level == "mid" }.toString()
        tvSafe.text = items.count { it.level == "safe" }.toString()

        // RecyclerView
        val rv = view.findViewById<RecyclerView>(R.id.rvMessages)
        adapter = MessageAdapter(items) { item ->
            if (item.threadId.isNotEmpty()) {
                val intent = Intent(requireContext(), ThreadDetailActivity::class.java)
                intent.putExtra("threadId", item.threadId)
                startActivity(intent)
            } else {
                Toast.makeText(requireContext(), "此訊息為安全對話", Toast.LENGTH_SHORT).show()
            }
        }
        rv.layoutManager = LinearLayoutManager(requireContext())
        rv.adapter = adapter

        // Mark all read
        view.findViewById<ImageButton>(R.id.btnMarkAllRead).setOnClickListener {
            tvHigh.text = "0"
            tvMid.text = "0"
            tvSafe.text = "0"
            Toast.makeText(requireContext(), "ALL MARKED READ", Toast.LENGTH_SHORT).show()
        }

        // Intelligence Summary stat clicks (filter by level)
        view.findViewById<View>(R.id.statHigh).setOnClickListener {
            toggleLevelFilter("high", it)
        }
        view.findViewById<View>(R.id.statMid).setOnClickListener {
            toggleLevelFilter("mid", it)
        }
        view.findViewById<View>(R.id.statSafe).setOnClickListener {
            toggleLevelFilter("safe", it)
        }

        // Chip filter (by app type)
        view.findViewById<ChipGroup>(R.id.chipGroupFilter).setOnCheckedStateChangeListener { _, checkedIds ->
            val chipText = when {
                checkedIds.isEmpty() -> "全部"
                checkedIds.first() == R.id.chipAll -> "全部"
                checkedIds.first() == R.id.chipLine -> "LINE"
                checkedIds.first() == R.id.chipSms -> "簡訊"
                checkedIds.first() == R.id.chipWhatsApp -> "WhatsApp"
                checkedIds.first() == R.id.chipMessenger -> "Messenger"
                else -> "全部"
            }
            adapter.filterByApp(chipText)
        }
    }

    private fun toggleLevelFilter(level: String, clickedView: View) {
        currentLevel = if (currentLevel == level) "all" else level
        adapter.filterByLevel(currentLevel)

        // 視覺反饋
        val statHigh = view?.findViewById<View>(R.id.statHigh)
        val statMid = view?.findViewById<View>(R.id.statMid)
        val statSafe = view?.findViewById<View>(R.id.statSafe)
        listOf(statHigh, statMid, statSafe).forEach { it?.setBackgroundColor(Color.TRANSPARENT) }

        if (currentLevel != "all") {
            val bgColor = when (currentLevel) {
                "high" -> Color.parseColor("#1AFF3B30")
                "mid" -> Color.parseColor("#1AFF9500")
                else -> Color.parseColor("#1A34C759")
            }
            clickedView.setBackgroundColor(bgColor)
        }
    }
}
