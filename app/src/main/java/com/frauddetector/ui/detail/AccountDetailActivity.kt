/**
 * AccountDetailActivity.kt — 帳號威脅檔案頁面
 *
 * 所屬模組：ui/detail（詳情模組）
 *
 * 透過 [EXTRA_ACCOUNT_ID] 接收帳號 ID，呼叫 GET /api/v1/accounts/{id}
 * 顯示風險評分、觸發規則、AI 摘要與證據摘要列表。
 */
package com.frauddetector.ui.detail

import android.graphics.Color
import android.os.Bundle
import android.view.View
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import com.frauddetector.ui.BaseActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.frauddetector.R
import com.frauddetector.adapter.EvidenceAdapter
import com.frauddetector.data.EvidenceItem
import com.frauddetector.network.ApiClient
import com.frauddetector.network.SuspectAccountDetailResponse
import com.frauddetector.network.TokenManager
// import com.frauddetector.ui.dialog.MessageReportBottomSheet // 帳號回報功能暫停用，見下方 btnBlockReport 註解
import com.google.android.material.chip.Chip
import com.google.android.material.chip.ChipGroup
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.concurrent.TimeUnit

class AccountDetailActivity : BaseActivity() {

    companion object {
        const val EXTRA_ACCOUNT_ID = "extra_account_id"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_account_detail)

        val accountId = intent.getIntExtra(EXTRA_ACCOUNT_ID, -1)
        if (accountId <= 0) {
            Toast.makeText(this, "無法載入帳號檔案", Toast.LENGTH_SHORT).show()
            finish()
            return
        }

        findViewById<View>(R.id.btnBackToThread).setOnClickListener { finish() }

        loadDetail(accountId)
    }

    private fun loadDetail(accountId: Int) {
        val token = TokenManager(this).accessToken
        if (token.isNullOrEmpty()) {
            Toast.makeText(this, "請先登入", Toast.LENGTH_SHORT).show()
            finish()
            return
        }

        ApiClient.accountApi.getAccountDetail("Bearer $token", accountId)
            .enqueue(object : Callback<SuspectAccountDetailResponse> {
                override fun onResponse(
                    call: Call<SuspectAccountDetailResponse>,
                    response: Response<SuspectAccountDetailResponse>
                ) {
                    val body = response.body()
                    if (response.isSuccessful && body != null) {
                        bindDetail(body)
                    } else {
                        val msg = ApiClient.parseError(response.errorBody()?.string())
                        Toast.makeText(this@AccountDetailActivity, "載入失敗：$msg", Toast.LENGTH_SHORT).show()
                        finish()
                    }
                }

                override fun onFailure(call: Call<SuspectAccountDetailResponse>, t: Throwable) {
                    Toast.makeText(this@AccountDetailActivity, "網路錯誤：${t.message}", Toast.LENGTH_SHORT).show()
                    finish()
                }
            })
    }

    private fun bindDetail(data: SuspectAccountDetailResponse) {
        findViewById<TextView>(R.id.tvDetName).text = data.accountName
        findViewById<TextView>(R.id.tvDetId).text =
            if (!data.externalAccountId.isNullOrBlank()) "${data.platform}: ${data.externalAccountId}"
            else data.platform

        findViewById<ProgressBar>(R.id.riskRing).progress = data.riskScore
        findViewById<TextView>(R.id.tvRingVal).text = data.riskScore.toString()
        findViewById<TextView>(R.id.tvDetMsgs).text = data.reportCount.toString()
        findViewById<TextView>(R.id.tvDetDays).text = "${daysBetween(data.createdAt, data.lastReportedAt)} 天"

        // Triggered rules chips
        val chipGroup = findViewById<ChipGroup>(R.id.chipGroupRules)
        chipGroup.removeAllViews()
        val ruleColor = if (data.riskLevel == "high") Color.parseColor("#A63D2F") else Color.parseColor("#C46B4A")
        data.triggeredRules.forEach { rule ->
            val chip = Chip(this).apply {
                text = rule
                isClickable = false
                setTextColor(ruleColor)
                chipBackgroundColor = android.content.res.ColorStateList.valueOf(
                    Color.argb(25, Color.red(ruleColor), Color.green(ruleColor), Color.blue(ruleColor))
                )
                chipStrokeWidth = 0f
            }
            chipGroup.addView(chip)
        }

        // AI summary
        val tvSummary = findViewById<TextView>(R.id.tvAiSummary)
        if (!data.aiSummary.isNullOrBlank()) {
            tvSummary.text = "AI 摘要：${data.aiSummary}"
            tvSummary.visibility = View.VISIBLE
        } else {
            tvSummary.visibility = View.GONE
        }

        // Evidence list
        val evidenceItems = data.evidenceItems.map {
            EvidenceItem(
                type = it.evidenceType,
                typeClass = if (it.severity == "high") "r" else "a",
                time = it.occurredAt?.take(10) ?: "",
                text = it.description
            )
        }
        findViewById<RecyclerView>(R.id.rvEvidence).apply {
            layoutManager = LinearLayoutManager(this@AccountDetailActivity)
            adapter = EvidenceAdapter(evidenceItems)
        }

        // Actions
        // 「回報」功能暫時停用（見 dev-notes 問題16）：後端 POST /reports/account
        // 只用 (platform, 帳號顯示名稱) 判斷是否為同一帳號，同名不同人會被誤判成
        // 同一筆、風險分數互相污染，等後端修好帳號比對邏輯之後再打開。
        // findViewById<View>(R.id.btnBlockReport).setOnClickListener {
        //     MessageReportBottomSheet.newInstance(
        //         data.accountName, data.platform, data.externalAccountId ?: ""
        //     ).show(supportFragmentManager, "report")
        // }
        findViewById<View>(R.id.btnBlockReport).visibility = View.GONE
        // 「分享」目前只是假按鈕（點了跳 Toast，沒有實際功能），先隱藏避免展示時被點到。
        // ShareWarningActivity 本身已經是完整功能，PhoneDetailActivity 有可用的串接範例，
        // 之後要接上帳號版本的分享警告時參考那邊即可。
        findViewById<View>(R.id.btnShareWarning).visibility = View.GONE
    }

    /** 計算帳號建檔到最後一次舉報之間的天數（無資料時回傳 0） */
    private fun daysBetween(createdAt: String?, lastReportedAt: String?): Int {
        if (createdAt.isNullOrBlank()) return 0
        return try {
            val sdf = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.getDefault())
            val start = sdf.parse(createdAt.take(19))?.time ?: return 0
            val end = if (!lastReportedAt.isNullOrBlank()) {
                sdf.parse(lastReportedAt.take(19))?.time ?: System.currentTimeMillis()
            } else {
                System.currentTimeMillis()
            }
            val diff = TimeUnit.MILLISECONDS.toDays(end - start).toInt()
            if (diff < 1) 1 else diff
        } catch (e: Exception) {
            0
        }
    }
}
