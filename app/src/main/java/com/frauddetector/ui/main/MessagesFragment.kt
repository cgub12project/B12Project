/**
 * MessagesFragment.kt — 訊息警報頁籤
 *
 * 所屬模組：ui/main（主畫面模組）
 *
 * 本 Fragment 為底部導航「訊息」頁籤的主要內容，功能包含：
 * - 顯示 Intelligence Summary 統計摘要（高危/可疑/安全各別計數）
 * - 以 RecyclerView 列表展示所有訊息警報（含色彩編碼邊框與風險標籤）
 * - 雙重篩選機制：
 *   1. 依風險等級篩選（點擊統計卡片：高危/可疑/安全）
 *   2. 依來源平台篩選（Chip 選擇：全部/LINE/簡訊/WhatsApp/Messenger）
 * - 全部已讀按鈕（重置統計計數）
 * - 點擊警報項目導航至 [ThreadDetailActivity] 對話詳情頁
 *
 * 資料來源為 [SampleData]，待後端就緒後可替換為 API 呼叫。
 */
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

/**
 * 訊息警報 Fragment，顯示詐騙訊息列表並提供雙重篩選功能。
 */
class MessagesFragment : Fragment() {

    /** 訊息列表 RecyclerView 的 Adapter */
    private lateinit var adapter: MessageAdapter
    /** 目前選中的風險等級篩選條件（"all" 表示不篩選） */
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

    /**
     * 切換風險等級篩選。
     * 點擊相同等級時取消篩選（恢復顯示全部），點擊不同等級則套用新篩選。
     * 同時更新統計卡片的背景色作為視覺反饋。
     *
     * @param level 被點擊的風險等級（"high"/"mid"/"safe"）
     * @param clickedView 被點擊的統計卡片 View
     */
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
