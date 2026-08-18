package com.frauddetector.ui.main

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import androidx.room.InvalidationTracker
import com.frauddetector.R
import com.frauddetector.adapter.MessageAdapter
import com.frauddetector.data.AlertItem
import com.frauddetector.db.AppDatabase
import com.frauddetector.db.CapturedNotification
import com.frauddetector.service.RagDetector
import com.frauddetector.service.SmsHelper
import com.frauddetector.ui.SwipeToDeleteHelper
import com.frauddetector.ui.detail.ThreadDetailActivity
import com.google.android.material.chip.Chip
import com.google.android.material.chip.ChipGroup
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors

class MessagesFragment : Fragment() {

    private lateinit var adapter: MessageAdapter
    private var currentLevel = "all"
    private var currentPlatformFilter = "全部"
    private val executor = Executors.newSingleThreadExecutor()

    // 即時刷新：captured_notifications 表只要有任何寫入（背景通知擷取、簡訊匯入、AI 風險快取
    // 寫回等）就會在主執行緒收到這個回呼。用 debounce 避免短時間內連續好幾則通知造成連續重刷。
    private val refreshHandler = Handler(Looper.getMainLooper())
    private var pendingRefresh: Runnable? = null
    private val dbObserver = object : InvalidationTracker.Observer("captured_notifications") {
        override fun onInvalidated(tables: Set<String>) {
            pendingRefresh?.let { refreshHandler.removeCallbacks(it) }
            val r = Runnable { loadData() }
            pendingRefresh = r
            refreshHandler.postDelayed(r, 400)
        }
    }

    override fun onResume() {
        super.onResume()
        val ctx = context?.applicationContext ?: return
        AppDatabase.getInstance(ctx).invalidationTracker.addObserver(dbObserver)
    }

    override fun onPause() {
        super.onPause()
        pendingRefresh?.let { refreshHandler.removeCallbacks(it) }
        val ctx = context?.applicationContext ?: return
        AppDatabase.getInstance(ctx).invalidationTracker.removeObserver(dbObserver)
    }

    private val requestSmsPermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { _ ->
        // 不管有沒有授權都載入資料（沒有簡訊權限就只顯示通知擷取的）
        loadData()
    }

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View? {
        return inflater.inflate(R.layout.fragment_messages, container, false)
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        val rv = view.findViewById<RecyclerView>(R.id.rvMessages)
        rv.layoutManager = LinearLayoutManager(requireContext())
        adapter = MessageAdapter(emptyList()) { item ->
            // Parse app and conversationKey (groupName for 群組, sender for 私訊) from the item id: "grp_{app}_{conversationKey}"
            val parts = item.id.removePrefix("grp_").split("_", limit = 2)
            if (parts.size == 2) {
                val (app, conversationKey) = parts
                val isGroup = item.tags.contains("群組")
                val intent = Intent(requireContext(), ThreadDetailActivity::class.java).apply {
                    putExtra(ThreadDetailActivity.EXTRA_APP, app)
                    putExtra(ThreadDetailActivity.EXTRA_SENDER, if (isGroup) "" else conversationKey)
                    putExtra(ThreadDetailActivity.EXTRA_GROUP_NAME, if (isGroup) conversationKey else "")
                }
                startActivity(intent)
            }
        }
        rv.adapter = adapter

        // 左滑刪除：滑到底跳確認對話框，確認才真的刪除本機訊息紀錄（可能是廣告或無關雜訊佔用列表）
        SwipeToDeleteHelper.attach(
            context = requireContext(),
            recyclerView = rv,
            getLabel = { position -> adapter.getItemAt(position).name },
            onConfirmedDelete = { position -> deleteConversation(adapter.getItemAt(position)) },
            onCanceled = { position -> adapter.notifyItemChanged(position) }
        )

        // 檢查 SMS 權限 → 匯入歷史簡訊 → 載入資料
        checkSmsAndLoad()

        // Level filter
        view.findViewById<View>(R.id.statHigh).setOnClickListener { toggleLevelFilter("high", it) }
        view.findViewById<View>(R.id.statMid).setOnClickListener { toggleLevelFilter("mid", it) }
        view.findViewById<View>(R.id.statSafe).setOnClickListener { toggleLevelFilter("safe", it) }

        // App chip filter — 動態生成，在 loadData() 後建立

    }

    private fun checkSmsAndLoad() {
        if (ContextCompat.checkSelfPermission(requireContext(), Manifest.permission.READ_SMS)
            != PackageManager.PERMISSION_GRANTED
        ) {
            requestSmsPermission.launch(Manifest.permission.READ_SMS)
        } else {
            loadData()
        }
    }

    private fun loadData() {
        // 在背景執行緒開始前先取用 applicationContext——Fragment 若中途 detach（切換分頁），
        // requireContext() 會丟 IllegalStateException 讓整個背景執行緒崩潰整個 App；
        // applicationContext 的生命週期跟著整個行程，不會有這個問題。
        val ctx = context?.applicationContext ?: return
        executor.execute {
            val db = AppDatabase.getInstance(ctx)
            val dao = db.capturedNotificationDao()

            // 若尚未匯入簡訊歷史 且 有 SMS 權限 → 匯入
            if (dao.getSmsHistoryCount() == 0 && hasSmsPermission(ctx)) {
                val smsHistory = SmsHelper.getInboxMessages(ctx, 200)
                if (smsHistory.isNotEmpty()) {
                    dao.insertAll(smsHistory)
                }
            }

            // 取得每個「對話」的最新一筆訊息（群組用 groupName、私訊用 sender 分組）
            val grouped = dao.getLatestMessagePerConversation()

            // Pass 1：先用目前已快取的風險等級（未偵測過的先當作 safe）立刻顯示列表，
            // 不等待 AI 偵測——避免對話數一多，逐筆同步打 /rag/detect 卡住整個列表不出現
            publishItems(grouped, dao)

            // Pass 2：背景重新計算每個對話的風險。不論群組或私訊，都把對話視窗內的訊息
            // 串接成一段話一次問 AI 整體風險（能抓到「互相佐證同一套話術」這種只看單句
            // 看不出來的模式，已用真實案例驗證過比逐則分析取最高風險更準）。同一個對話
            // 只要沒有新訊息就直接沿用上次結果，不會重打 API（見 detectConversationRisk 的
            // 視窗指紋快取說明）。
            val enriched = grouped.map { representative ->
                val isGroup = representative.groupName.isNotEmpty()
                val allMessages = if (isGroup) {
                    dao.getMessagesByGroup(representative.app, representative.groupName)
                } else {
                    dao.getMessagesByPrivateSender(representative.sender, representative.app)
                }
                val conversationKey = "${representative.app}|${if (isGroup) representative.groupName else representative.sender}"
                val convRisk = RagDetector.detectConversationRisk(ctx, conversationKey, allMessages)
                if (convRisk != null) {
                    representative.copy(
                        riskLevel = convRisk.riskLevel,
                        scamType = convRisk.scamType,
                        aiReason = convRisk.reasons.firstOrNull(),
                        confidence = convRisk.confidence
                    )
                } else {
                    representative
                }
            }
            publishItems(enriched, dao)
        }
    }

    /** 將分組後的通知列表映射為 AlertItem 並更新畫面（可能被呼叫兩次：立即顯示 + AI 偵測完成後更新風險顏色） */
    private fun publishItems(grouped: List<CapturedNotification>, dao: com.frauddetector.db.CapturedNotificationDao) {
        val items = if (grouped.isNotEmpty()) {
            grouped.map { it.toGroupedAlertItem(dao) }
                .sortedWith(compareBy<AlertItem> { platformOrder(it.app) }.thenByDescending { it.time })
        } else emptyList()

        activity?.runOnUiThread {
            adapter.updateItems(items)
            updateStats(items)
            buildDynamicChips(items)
        }
    }

    /**
     * 左滑刪除確認後執行：從本機 DB 刪掉這個對話的所有擷取訊息，並立即從列表移除。
     * 只刪本機擷取紀錄，不影響原本 App（LINE／簡訊等）裡的真實訊息。
     */
    private fun deleteConversation(item: AlertItem) {
        val ctx = requireContext().applicationContext
        val parts = item.id.removePrefix("grp_").split("_", limit = 2)
        if (parts.size == 2) {
            val (app, conversationKey) = parts
            val isGroup = item.tags.contains("群組")
            executor.execute {
                val dao = AppDatabase.getInstance(ctx).capturedNotificationDao()
                if (isGroup) dao.deleteGroupConversation(app, conversationKey)
                else dao.deletePrivateConversation(conversationKey, app)
            }
        }
        adapter.removeItem(item.id)
        updateStats(adapter.getAllItems())
        Toast.makeText(requireContext(), "已刪除「${item.name}」的對話紀錄", Toast.LENGTH_SHORT).show()
    }

    private fun hasSmsPermission(ctx: android.content.Context): Boolean {
        return ContextCompat.checkSelfPermission(ctx, Manifest.permission.READ_SMS) ==
                PackageManager.PERMISSION_GRANTED
    }

    private fun updateStats(items: List<AlertItem>) {
        view?.let { v ->
            v.findViewById<TextView>(R.id.tvHighCount).text = items.count { it.level == "high" }.toString()
            v.findViewById<TextView>(R.id.tvMidCount).text = items.count { it.level == "mid" }.toString()
            v.findViewById<TextView>(R.id.tvSafeCount).text = items.count { it.level == "safe" }.toString()

            val unanalyzedCount = items.count { it.level == "unanalyzed" }
            val hint = v.findViewById<TextView>(R.id.tvUnanalyzedHint)
            if (unanalyzedCount > 0) {
                hint.text = "$unanalyzedCount 則尚未完成分析，暫不計入安全數量"
                hint.visibility = View.VISIBLE
            } else {
                hint.visibility = View.GONE
            }
        }
    }

    private fun platformOrder(app: String): Int = when (app) {
        "LINE" -> 0; "簡訊" -> 1; "WhatsApp" -> 2; "Messenger" -> 3; else -> 4
    }

    /** 根據實際資料動態產生平台篩選 Chips */
    private fun buildDynamicChips(items: List<AlertItem>) {
        val chipGroup = view?.findViewById<ChipGroup>(R.id.chipGroupFilter) ?: return
        chipGroup.removeAllViews()

        // 「全部」chip 永遠在最前面
        val chipAll = Chip(requireContext()).apply {
            text = "全部"
            isCheckable = true
            isChecked = currentPlatformFilter == "全部"
        }
        chipGroup.addView(chipAll)

        // 依實際資料中有的平台動態新增（即時刷新會重建整個 ChipGroup，
        // 用 currentPlatformFilter 還原原本選取的 chip，不然使用者選的篩選會被重置回「全部」）
        val platforms = items.map { it.app }.distinct().sortedBy { platformOrder(it) }
        platforms.forEach { platform ->
            val chip = Chip(requireContext()).apply {
                text = platform
                isCheckable = true
                isChecked = platform == currentPlatformFilter
            }
            chipGroup.addView(chip)
        }

        chipGroup.setOnCheckedStateChangeListener { _, checkedIds ->
            currentPlatformFilter = if (checkedIds.isEmpty() || checkedIds.first() == chipAll.id) {
                "全部"
            } else {
                val selectedChip = chipGroup.findViewById<Chip>(checkedIds.first())
                selectedChip?.text?.toString() ?: "全部"
            }
            adapter.filterByApp(currentPlatformFilter)
        }
    }

    private fun toggleLevelFilter(level: String, clickedView: View) {
        currentLevel = if (currentLevel == level) "all" else level
        adapter.filterByLevel(currentLevel)

        val statHigh = view?.findViewById<View>(R.id.statHigh)
        val statMid = view?.findViewById<View>(R.id.statMid)
        val statSafe = view?.findViewById<View>(R.id.statSafe)
        listOf(statHigh, statMid, statSafe).forEach { it?.setBackgroundColor(Color.TRANSPARENT) }

        if (currentLevel != "all") {
            val bgColor = when (currentLevel) {
                "high" -> Color.parseColor("#1AA63D2F")
                "mid" -> Color.parseColor("#1AC46B4A")
                else -> Color.parseColor("#1A7A9E7E")
            }
            clickedView.setBackgroundColor(bgColor)
        }
    }
}

/** 將 DB 中的對話最新訊息轉換為 AlertItem（帶訊息數量統計） */
private fun CapturedNotification.toGroupedAlertItem(
    dao: com.frauddetector.db.CapturedNotificationDao
): AlertItem {
    val sdf = SimpleDateFormat("MM/dd HH:mm", Locale.getDefault())
    val timeStr = sdf.format(Date(timestamp))

    // 對話 key：群組用 groupName，私訊用 sender（跟 DAO 的分組邏輯一致）
    val conversationKey = if (groupName.isNotEmpty()) groupName else sender
    val msgCount = if (groupName.isNotEmpty())
        dao.getMessageCountByGroup(app, groupName)
    else
        dao.getMessageCountByPrivateSender(sender, app)

    // 組合顯示名稱：如果有群組名就顯示「群組名稱」，否則顯示 sender
    val displayName = if (groupName.isNotEmpty()) groupName else sender

    // source 行顯示：平台 · 群組/私訊 · N 則訊息
    // （最新發言者不放這裡，改由卡片的內容標籤直接顯示成「陳大富:」，見 AlertItem.speaker）
    val chatType = if (groupName.isNotEmpty()) "群組" else "私訊"
    val sourceText = "$app · $chatType · ${msgCount}則訊息"

    // 還沒分析完（或分析失敗）不能當「安全」——後端一掛，真的詐騙訊息會被畫成安全的米白卡，
    // 對防詐 App 是危險預設值。改用獨立的「未分析」灰卡，不計入安全數量。
    val level = riskLevel ?: "unanalyzed"
    // 詐騙類型刻意不放進列表卡的標籤（2026-08-17 UI 決定）：卡片本身的顏色已經表達
    // 風險高低，類型是點進對話詳情才需要的細節，放在列表上只會讓卡片變吵。
    // 詳情頁仍會顯示（見 ThreadDetailActivity 的 tags 與 詐騙類型 欄位）。
    // 平台／私訊-群組標籤同理移除（2026-08-18）：sourceText 開頭已經寫「LINE · 群組 · N則訊息」，
    // 標籤重複顯示同一件事，且標籤底色跟卡片風險色放在一起顯得突兀。
    val tags = emptyList<String>()

    return AlertItem(
        id = "grp_${app}_${conversationKey}",
        name = displayName,
        source = sourceText,
        message = content,    // 最新一則訊息作為預覽
        time = timeStr,
        level = level,        // 由 /rag/detect 判斷後快取的風險等級
        app = app,
        tags = tags,
        threadId = "",
        speaker = if (groupName.isNotEmpty()) sender else ""
    )
}
