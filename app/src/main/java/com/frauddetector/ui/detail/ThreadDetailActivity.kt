package com.frauddetector.ui.detail

import android.graphics.Color
import android.os.Bundle
import android.view.View
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import com.frauddetector.ui.BaseActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.frauddetector.R
import com.frauddetector.adapter.ChatBubbleAdapter
import com.frauddetector.db.AppDatabase
// import com.frauddetector.network.ApiClient // 帳號回報/帳號分數查詢暫停用，見下方相關註解
import com.frauddetector.network.RagDetectResponse
// import com.frauddetector.network.TokenManager // 同上
import com.frauddetector.service.RagDetector
// import com.frauddetector.ui.dialog.MessageReportBottomSheet // 帳號回報功能暫停用，見下方 btnReportAccount 註解
import com.google.android.material.chip.Chip
import com.google.android.material.chip.ChipGroup
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class ThreadDetailActivity : BaseActivity() {

    companion object {
        const val EXTRA_SENDER = "extra_sender"
        const val EXTRA_APP = "extra_app"
        const val EXTRA_GROUP_NAME = "extra_group_name"
    }

    private val executor = Executors.newSingleThreadExecutor()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_thread_detail)

        val sender = intent.getStringExtra(EXTRA_SENDER) ?: ""
        val app = intent.getStringExtra(EXTRA_APP)
        val groupName = intent.getStringExtra(EXTRA_GROUP_NAME) ?: ""
        val isGroup = groupName.isNotEmpty()

        if (app.isNullOrEmpty() || (sender.isEmpty() && groupName.isEmpty())) {
            Toast.makeText(this, "無法載入對話", Toast.LENGTH_SHORT).show()
            finish()
            return
        }

        // Back button
        findViewById<View>(R.id.btnBackToMessages).setOnClickListener { finish() }

        // 「回報此帳號為詐騙帳號」功能暫時停用（見 dev-notes 問題16）：
        // 後端 POST /reports/account 目前只用 (platform, 帳號顯示名稱) 判斷是否為
        // 同一個帳號，實測證實同名但不相關的帳號會被誤判成同一筆、風險分數互相污染，
        // 而 LINE 這類平台的顯示名稱本來就不保證唯一。等後端修好帳號比對邏輯
        // （或前端能拿到真正可識別身分的 external_account_id）之後再打開。
        // findViewById<View>(R.id.btnReportAccount).setOnClickListener {
        //     val accountName = groupName.ifEmpty { sender }
        //     MessageReportBottomSheet.newInstance(accountName, app, "")
        //         .show(supportFragmentManager, "report_account")
        // }
        findViewById<View>(R.id.btnReportAccount).visibility = View.GONE

        // Header info
        val displayName = groupName.ifEmpty { sender }
        findViewById<TextView>(R.id.tvThreadSender).text = displayName
        val groupInfo = if (isGroup) "$app · 群組" else "$app · 私訊"
        findViewById<TextView>(R.id.tvThreadGroup).text = groupInfo

        // Risk pill — 載入中先顯示佔位文字，AI 偵測完成後於下方更新
        val tvRiskPill = findViewById<TextView>(R.id.tvRiskPill)
        tvRiskPill.text = "分析中"
        tvRiskPill.setBackgroundResource(R.drawable.bg_risk_pill_safe)

        // Stats — placeholder until loaded
        findViewById<TextView>(R.id.tvThreadScore).text = "--"
        findViewById<TextView>(R.id.tvThreadDays).text = "-- 天"

        // RecyclerView
        val rv = findViewById<RecyclerView>(R.id.rvChatMessages)
        rv.layoutManager = LinearLayoutManager(this)

        // Load messages from DB
        executor.execute {
            val dao = AppDatabase.getInstance(this).capturedNotificationDao()
            val messages = if (isGroup) dao.getMessagesByGroup(app, groupName)
                           else dao.getMessagesByPrivateSender(sender, app)

            val msgCount = messages.size
            val daysSpan = if (messages.size >= 2) {
                val first = messages.first().timestamp
                val last = messages.last().timestamp
                val diff = TimeUnit.MILLISECONDS.toDays(last - first).toInt()
                if (diff < 1) 1 else diff
            } else 1

            // 風險等級／原因：不論群組或私訊，都用串接整個對話視窗的整體判斷
            // （能抓到互相佐證同一套話術的模式，已用真實案例驗證過比只看單一則更準）。
            // 同一個對話只要沒有新訊息進來，就直接沿用上次結果、不會重打 API
            // （見 RagDetector.detectConversationRisk 的視窗指紋快取說明）。
            val conversationKey = "$app|${if (isGroup) groupName else sender}"
            val convRisk = RagDetector.detectConversationRisk(this, conversationKey, messages)
            val conversationExplanation = convRisk
            val hasDetection = convRisk != null
            // 尚未偵測完成（或偵測失敗）不能當成「安全」——對防詐 App 是危險預設值，
            // 真正的詐騙訊息會在後端掛掉時被畫成安全的卡片。改用獨立的「未分析」狀態。
            val riskLevel = convRisk?.riskLevel ?: "unanalyzed"
            val scamType = convRisk?.scamType
            val confidence = convRisk?.confidence ?: 0.0

            // 「風險評分」欄位：一律顯示「近期對話風險評分」（risk_level+confidence 換算，
            // 即時、只反映最近視窗，見 RagDetector.computeMessageRiskScore 的說明）。
            // 原本這裡會優先顯示 fetchAccountRiskScore() 查到的「帳號風險評分」，但那個
            // 分數來自 suspect_accounts，而後端目前只用 (platform, 顯示名稱) 判斷帳號是否
            // 相同，同名不同人會被誤判成同一筆、風險分數互相污染（見 dev-notes 問題16）。
            // 在後端修好帳號比對邏輯之前，這裡先停用帳號分數、固定顯示對話分數，
            // 避免使用者看到一個可能屬於「同名但不相關的另一個帳號」的錯誤分數。
            val scoreText: String = if (hasDetection) {
                RagDetector.computeMessageRiskScore(riskLevel, confidence).toString()
            } else {
                "--"
            }
            val scoreLabelRes: Int = R.string.conversation_risk_score_label

            runOnUiThread {
                // Update stats
                findViewById<TextView>(R.id.tvThreadScore).text = scoreText
                findViewById<TextView>(R.id.tvThreadScoreLabel).setText(scoreLabelRes)
                findViewById<TextView>(R.id.tvThreadMsgs).text = "${msgCount} 則"
                findViewById<TextView>(R.id.tvThreadDays).text = "${daysSpan} 天"

                // Risk pill
                val (pillText, pillBg) = when (riskLevel) {
                    "high" -> "高危" to R.drawable.bg_risk_pill_high
                    "mid" -> "可疑" to R.drawable.bg_risk_pill_mid
                    "unanalyzed" -> "未分析" to R.drawable.bg_risk_pill_unanalyzed
                    else -> "安全" to R.drawable.bg_risk_pill_safe
                }
                tvRiskPill.text = pillText
                tvRiskPill.setBackgroundResource(pillBg)

                // 整體對話判斷按鈕：不分群組或私訊，只要成功取得判斷結果就顯示
                val btnGroupExplanation = findViewById<View>(R.id.btnGroupExplanation)
                if (conversationExplanation != null) {
                    btnGroupExplanation.visibility = View.VISIBLE
                    btnGroupExplanation.setOnClickListener {
                        showConversationExplanationDialog(conversationExplanation)
                    }
                } else {
                    btnGroupExplanation.visibility = View.GONE
                }

                // Pattern tags — 顯示來源 App，若 AI 判定有風險則加上詐騙類型標籤
                val chipGroup = findViewById<ChipGroup>(R.id.chipGroupPatterns)
                chipGroup.removeAllViews()
                val tags = mutableListOf(app)
                if (riskLevel != "safe" && !scamType.isNullOrBlank()) tags.add(scamType)
                tags.forEach { tag ->
                    val chip = Chip(this).apply {
                        text = tag
                        isClickable = false
                        textSize = 10f
                        setTextColor(Color.parseColor("#4A7FA5"))
                        chipBackgroundColor = android.content.res.ColorStateList.valueOf(
                            Color.parseColor("#1A4A7FA5")
                        )
                        chipStrokeWidth = 0f
                    }
                    chipGroup.addView(chip)
                }

                // Set adapter
                rv.adapter = ChatBubbleAdapter(messages) { msg -> showMessageExplanation(msg) }

                // Scroll to bottom (most recent)
                if (messages.isNotEmpty()) {
                    rv.scrollToPosition(messages.size - 1)
                }
            }
        }
    }

    /**
     * 顯示「整體對話判斷」彈窗：風險等級、詐騙類型、完整判定理由與防詐建議，
     * 資料直接沿用載入對話時已經呼叫過的 [RagDetector.detectConversationRisk] 結果，
     * 不會因為使用者點這顆按鈕而再多打一次 API。
     */
    private fun showConversationExplanationDialog(response: RagDetectResponse) {
        AlertDialog.Builder(this)
            .setTitle("整體對話判斷")
            .setMessage(buildExplanationMessage(response))
            .setPositiveButton("關閉", null)
            .show()
    }

    /**
     * 點單一則訊息 → 即時重新呼叫 /rag/detect（不快取，見 [RagDetector.detectLive]）
     * 取得完整判斷後彈窗顯示。等待期間顯示不可取消的 Loading 對話框。
     */
    private fun showMessageExplanation(msg: com.frauddetector.db.CapturedNotification) {
        val loadingDialog = AlertDialog.Builder(this)
            .setView(android.widget.ProgressBar(this).apply {
                setPadding(48, 48, 48, 48)
            })
            .setCancelable(false)
            .create()
        loadingDialog.show()

        executor.execute {
            val result = RagDetector.detectLive(this, msg.content)
            runOnUiThread {
                loadingDialog.dismiss()
                if (result == null) {
                    Toast.makeText(this, "分析失敗，請稍後再試", Toast.LENGTH_SHORT).show()
                    return@runOnUiThread
                }
                AlertDialog.Builder(this)
                    .setTitle("訊息分析：${msg.sender}")
                    .setMessage(buildExplanationMessage(result))
                    .setPositiveButton("關閉", null)
                    .show()
            }
        }
    }

    private fun buildExplanationMessage(response: RagDetectResponse): String {
        val riskLabel = when (response.riskLevel) {
            "high" -> "高危"
            "mid" -> "可疑"
            else -> "安全"
        }
        val reasonsText = response.reasons.joinToString("\n") { "• $it" }.ifBlank { "（無）" }
        return buildString {
            append("風險等級：$riskLabel")
            if (!response.scamType.isNullOrBlank()) append("\n詐騙類型：${response.scamType}")
            append("\n\n判定理由：\n$reasonsText")
            if (!response.advice.isNullOrBlank()) append("\n\n防詐建議：\n${response.advice}")
        }
    }

    // 帳號風險評分查詢暫時停用（見上方 scoreText 註解、dev-notes 問題16）：
    // 後端目前只用 (platform, 帳號顯示名稱) 判斷帳號是否相同，同名不同人會被
    // 誤判成同一筆帳號、風險分數互相污染，在後端修好之前不採用這個分數。
    // private fun fetchAccountRiskScore(platform: String, accountName: String): Int? {
    //     val token = TokenManager(this).accessToken
    //     if (token.isNullOrEmpty()) return null
    //     return try {
    //         val response = ApiClient.accountApi
    //             .listAccounts("Bearer $token", platform = platform, limit = 100)
    //             .execute()
    //         response.body()?.items?.firstOrNull { it.accountName == accountName }?.riskScore
    //     } catch (e: Exception) {
    //         null
    //     }
    // }
}
