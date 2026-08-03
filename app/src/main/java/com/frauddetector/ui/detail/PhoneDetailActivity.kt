/**
 * PhoneDetailActivity.kt — 電話號碼詳情頁面
 *
 * 所屬模組：ui/detail（詳情模組）
 *
 * 透過電話號碼呼叫 GET /api/v1/phones/{phone_number} 取得風險資訊與社群回報列表，功能包含：
 * - 號碼資訊：電話號碼、風險等級膠囊（高危/可疑/安全）
 * - 統計數據：舉報次數、最近舉報時間、詐騙類型
 * - 社群回報列表（[ReportAdapter]）
 * - 四大操作按鈕：撥號 / 封鎖 / 回報（[ReportBottomSheet]，API 串接）/ 分享
 */
package com.frauddetector.ui.detail

import android.content.ActivityNotFoundException
import android.content.Intent
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Bundle
import android.view.View
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import com.frauddetector.ui.BaseActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.frauddetector.R
import com.frauddetector.adapter.ReportAdapter
import com.frauddetector.data.CommunityReport
import com.frauddetector.network.ApiClient
import com.frauddetector.network.PhoneDetailResponse
import com.frauddetector.network.TokenManager
import com.frauddetector.service.BlockedNumbersManager
import com.frauddetector.service.TaiwanPhoneFormat
import com.frauddetector.ui.dialog.ReportBottomSheet
import com.frauddetector.ui.dialog.ResultDialog
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class PhoneDetailActivity : BaseActivity() {

    private lateinit var phoneNumber: String
    private var lastFraudType: String = "未分類"
    private var lastReportCount: String = "0"

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_phone_detail)

        val number = intent.getStringExtra("phoneNumber")
        if (number.isNullOrEmpty()) {
            finish()
            return
        }
        phoneNumber = number

        findViewById<TextView>(R.id.tvPhoneNumber).text = phoneNumber
        findViewById<TextView>(R.id.tvPhoneFormatWarning).visibility =
            if (TaiwanPhoneFormat.isAbnormal(phoneNumber)) View.VISIBLE else View.GONE
        findViewById<RecyclerView>(R.id.rvCommunityReports).layoutManager = LinearLayoutManager(this)

        findViewById<LinearLayout>(R.id.btnBackToPhoneList).setOnClickListener { finish() }

        findViewById<LinearLayout>(R.id.btnDial).setOnClickListener {
            try {
                startActivity(Intent(Intent.ACTION_DIAL, Uri.parse("tel:$phoneNumber")))
            } catch (e: ActivityNotFoundException) {
                Toast.makeText(this, "找不到撥號 App", Toast.LENGTH_SHORT).show()
            }
        }

        findViewById<LinearLayout>(R.id.btnBlock).setOnClickListener {
            val nowBlocked = BlockedNumbersManager.toggle(this, phoneNumber)
            ResultDialog.newInstance(
                true,
                if (nowBlocked) "封鎖成功" else "已取消封鎖",
                if (nowBlocked) "號碼已加入本機封鎖名單，往後不會出現在電話頁列表中。"
                else "號碼已從本機封鎖名單移除。"
            ).show(supportFragmentManager, "result")
        }

        findViewById<LinearLayout>(R.id.btnReport).setOnClickListener {
            ReportBottomSheet.newInstance(phoneNumber).show(supportFragmentManager, "report")
        }

        findViewById<LinearLayout>(R.id.btnShare).setOnClickListener {
            val shareIntent = Intent(this, ShareWarningActivity::class.java)
            shareIntent.putExtra("phoneNumber", phoneNumber)
            shareIntent.putExtra("phoneType", lastFraudType)
            shareIntent.putExtra("phoneCount", lastReportCount)
            startActivity(shareIntent)
        }

        loadDetail()
    }

    private fun loadDetail() {
        val token = TokenManager(this).accessToken
        if (token.isNullOrEmpty()) {
            Toast.makeText(this, "請先登入", Toast.LENGTH_SHORT).show()
            finish()
            return
        }

        ApiClient.phoneApi.getPhoneDetail("Bearer $token", phoneNumber)
            .enqueue(object : Callback<PhoneDetailResponse> {
                override fun onResponse(call: Call<PhoneDetailResponse>, response: Response<PhoneDetailResponse>) {
                    val body = response.body()
                    if (response.isSuccessful && body != null) {
                        bindDetail(body)
                    } else {
                        val msg = ApiClient.parseError(response.errorBody()?.string())
                        Toast.makeText(this@PhoneDetailActivity, "查無此號碼資料：$msg", Toast.LENGTH_SHORT).show()
                    }
                }

                override fun onFailure(call: Call<PhoneDetailResponse>, t: Throwable) {
                    Toast.makeText(this@PhoneDetailActivity, "網路錯誤：${t.message}", Toast.LENGTH_SHORT).show()
                }
            })
    }

    private fun bindDetail(data: PhoneDetailResponse) {
        lastFraudType = data.fraudType ?: "未分類"
        lastReportCount = data.reportCount.toString()

        val riskLabel = when (data.riskLevel) {
            "high" -> "詐騙"
            "mid" -> "可疑"
            else -> "安全"
        }
        val riskColor = when (data.riskLevel) {
            "high" -> Color.parseColor("#A63D2F")
            "mid" -> Color.parseColor("#C46B4A")
            else -> Color.parseColor("#7A9E7E")
        }
        val tvRisk = findViewById<TextView>(R.id.tvPhoneRisk)
        tvRisk.text = riskLabel
        tvRisk.setTextColor(Color.WHITE)
        tvRisk.background = GradientDrawable().apply {
            cornerRadius = 20f * resources.displayMetrics.density
            setColor(riskColor)
        }

        findViewById<TextView>(R.id.tvReportCount).text = lastReportCount
        findViewById<TextView>(R.id.tvLastReport).text = data.lastReportedAt?.take(10) ?: "—"
        findViewById<TextView>(R.id.tvFraudType).text = lastFraudType

        val reports = data.reports.map {
            CommunityReport(
                user = it.reporter,
                type = it.fraudType,
                typeClass = if (data.riskLevel == "high") "r" else "a",
                time = it.createdAt.take(10),
                desc = it.content
            )
        }
        findViewById<RecyclerView>(R.id.rvCommunityReports).adapter = ReportAdapter(reports)
    }
}
