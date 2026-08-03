package com.frauddetector.ui.main

import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.ImageButton
import android.widget.Toast
import androidx.fragment.app.Fragment
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.frauddetector.R
import com.frauddetector.adapter.EmailAdapter
import com.frauddetector.data.EmailAlert
import com.frauddetector.db.AppDatabase
import com.frauddetector.db.CapturedNotification
import com.frauddetector.service.RagDetector
import com.frauddetector.ui.SwipeToDeleteHelper
import com.google.android.material.chip.Chip
import com.google.android.material.chip.ChipGroup
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors

class EmailFragment : Fragment() {

    private lateinit var adapter: EmailAdapter
    private val executor = Executors.newSingleThreadExecutor()

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View? {
        return inflater.inflate(R.layout.fragment_email, container, false)
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        val rv = view.findViewById<RecyclerView>(R.id.rvEmails)
        adapter = EmailAdapter(emptyList()) { email ->
            Toast.makeText(requireContext(), "郵件：${email.subject}", Toast.LENGTH_SHORT).show()
        }
        rv.layoutManager = LinearLayoutManager(requireContext())
        rv.adapter = adapter

        // 左滑刪除：滑到底跳確認對話框，確認才真的刪除本機擷取的郵件紀錄（可能是廣告郵件佔用列表）
        SwipeToDeleteHelper.attach(
            context = requireContext(),
            recyclerView = rv,
            getLabel = { position -> adapter.getItemAt(position).sender },
            onConfirmedDelete = { position -> deleteEmail(adapter.getItemAt(position)) },
            onCanceled = { position -> adapter.notifyItemChanged(position) }
        )

        loadEmails()

        // 搜尋圖示 → 展開/收合搜尋框
        val searchBox = view.findViewById<View>(R.id.emailSearchBox)
        val etSearch = view.findViewById<EditText>(R.id.etEmailSearch)
        view.findViewById<ImageButton>(R.id.btnEmailSearch).setOnClickListener {
            if (searchBox.visibility == View.VISIBLE) {
                searchBox.visibility = View.GONE
                etSearch.setText("")
            } else {
                searchBox.visibility = View.VISIBLE
            }
        }
        etSearch.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun afterTextChanged(s: Editable?) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {
                adapter.filterByQuery(s?.toString() ?: "")
            }
        })

        // Provider chip filter — 動態生成，在 loadEmails() 後建立
    }

    /** 根據實際資料動態產生郵件供應商篩選 Chips */
    private fun buildDynamicChips(items: List<EmailAlert>) {
        val chipGroup = view?.findViewById<ChipGroup>(R.id.chipGroupProvider) ?: return
        chipGroup.removeAllViews()

        val chipAll = Chip(requireContext()).apply {
            text = "全部"
            isCheckable = true
            isChecked = true
        }
        chipGroup.addView(chipAll)

        val providers = items.map { it.provider }.distinct().sorted()
        providers.forEach { provider ->
            val chip = Chip(requireContext()).apply {
                text = provider
                isCheckable = true
            }
            chipGroup.addView(chip)
        }

        chipGroup.setOnCheckedStateChangeListener { _, checkedIds ->
            if (checkedIds.isEmpty() || checkedIds.first() == chipAll.id) {
                adapter.filterByProvider("全部")
            } else {
                val selectedChip = chipGroup.findViewById<Chip>(checkedIds.first())
                adapter.filterByProvider(selectedChip?.text?.toString() ?: "全部")
            }
        }
    }

    private fun loadEmails() {
        // 先取用 applicationContext（理由同 MessagesFragment）：Fragment 若在背景任務跑完前
        // 就 detach，requireContext() 會拋例外把整個背景執行緒帶崩，進而讓 App 閃退。
        val ctx = context?.applicationContext ?: return
        executor.execute {
            val db = AppDatabase.getInstance(ctx)
            val dao = db.capturedNotificationDao()

            // 取得每個 sender 的最新一筆郵件
            val grouped = dao.getLatestEmailPerSender()

            // Pass 1：先用目前已快取的風險等級立刻顯示列表，不等待 AI 偵測
            publishItems(grouped)

            // Pass 2：背景逐一偵測尚未快取風險的郵件，偵測完再重新整理一次畫面
            var anyNewlyDetected = false
            val detected = grouped.map { notif ->
                if (notif.riskLevel == null) {
                    anyNewlyDetected = true
                    RagDetector.detectAndCache(ctx, notif)
                } else {
                    notif
                }
            }
            if (anyNewlyDetected) {
                publishItems(detected)
            }
        }
    }

    /**
     * 左滑刪除確認後執行：從本機 DB 刪掉這個寄件人的所有擷取郵件，並立即從列表移除。
     * 只刪本機擷取紀錄，不影響真正的 Gmail/Outlook 信箱。
     */
    private fun deleteEmail(email: EmailAlert) {
        val ctx = requireContext().applicationContext
        val parts = email.id.removePrefix("grp_").split("_", limit = 2)
        if (parts.size == 2) {
            val (app, sender) = parts
            executor.execute {
                AppDatabase.getInstance(ctx).capturedNotificationDao().deleteEmailConversation(sender, app)
            }
        }
        adapter.removeItem(email.id)
        Toast.makeText(requireContext(), "已刪除「${email.sender}」的郵件紀錄", Toast.LENGTH_SHORT).show()
    }

    private fun publishItems(grouped: List<CapturedNotification>) {
        val items = grouped.map { it.toGroupedEmailAlert() }
        activity?.runOnUiThread {
            adapter.updateItems(items)
            buildDynamicChips(items)
        }
    }
}

private fun CapturedNotification.toGroupedEmailAlert(): EmailAlert {
    val sdf = SimpleDateFormat("MM/dd HH:mm", Locale.getDefault())
    val timeStr = sdf.format(Date(timestamp))
    val level = riskLevel ?: "safe"
    val tags = mutableListOf(app)
    if (level != "safe" && !scamType.isNullOrBlank()) tags.add(scamType)

    return EmailAlert(
        id = "grp_${app}_${sender}",
        sender = sender,
        subject = content.take(60),
        preview = content,
        time = timeStr,
        level = level,       // 由 /rag/detect 判斷後快取的風險等級
        provider = app,   // "Gmail" or "Outlook"
        tags = tags
    )
}
