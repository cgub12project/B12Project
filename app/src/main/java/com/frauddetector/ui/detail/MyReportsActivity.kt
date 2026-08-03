package com.frauddetector.ui.detail

import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import android.widget.Toast
import com.frauddetector.ui.BaseActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.frauddetector.R
import com.frauddetector.network.ApiClient
import com.frauddetector.network.MyReportItem
import com.frauddetector.network.MyReportsResponse
import com.frauddetector.network.TokenManager
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class MyReportsActivity : BaseActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_my_reports)

        findViewById<View>(R.id.btnBack).setOnClickListener { finish() }

        val rv = findViewById<RecyclerView>(R.id.rvReports)
        rv.layoutManager = LinearLayoutManager(this)

        loadReports()
    }

    private fun loadReports() {
        val token = TokenManager(this).accessToken
        if (token.isNullOrEmpty()) {
            showEmpty("請先登入")
            return
        }

        ApiClient.reportApi.getMyReports("Bearer $token")
            .enqueue(object : Callback<MyReportsResponse> {
                override fun onResponse(
                    call: Call<MyReportsResponse>,
                    response: Response<MyReportsResponse>
                ) {
                    if (response.isSuccessful) {
                        val reports = response.body()?.items ?: emptyList()
                        if (reports.isEmpty()) {
                            showEmpty("尚無回報紀錄")
                        } else {
                            findViewById<TextView>(R.id.tvEmpty).visibility = View.GONE
                            findViewById<RecyclerView>(R.id.rvReports).adapter =
                                MyReportsAdapter(reports)
                        }
                    } else {
                        val errMsg = ApiClient.parseError(response.errorBody()?.string())
                        showEmpty("載入失敗：$errMsg")
                    }
                }

                override fun onFailure(call: Call<MyReportsResponse>, t: Throwable) {
                    showEmpty("網路錯誤：${t.message}")
                }
            })
    }

    private fun showEmpty(msg: String) {
        findViewById<TextView>(R.id.tvEmpty).apply {
            text = msg
            visibility = View.VISIBLE
        }
    }
}

class MyReportsAdapter(
    private val items: List<MyReportItem>
) : RecyclerView.Adapter<MyReportsAdapter.VH>() {

    class VH(view: View) : RecyclerView.ViewHolder(view) {
        val tvUser: TextView = view.findViewById(R.id.tvReportUser)
        val tvTime: TextView = view.findViewById(R.id.tvReportTime)
        val tvType: TextView = view.findViewById(R.id.tvReportType)
        val tvDesc: TextView = view.findViewById(R.id.tvReportDesc)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_report, parent, false)
        return VH(view)
    }

    override fun onBindViewHolder(holder: VH, position: Int) {
        val item = items[position]
        val dp = holder.itemView.resources.displayMetrics.density

        // Card background
        val cardBg = GradientDrawable().apply {
            setColor(Color.parseColor("#FDFAF4"))
            cornerRadius = 12f * dp
            setStroke((1 * dp).toInt(), Color.parseColor("#1AC8C4C0"))
        }
        holder.itemView.background = cardBg

        // Target info — "[種類] 目標"
        val kindLabel = when (item.kind) {
            "phone" -> "電話回報"
            "account" -> "帳號回報"
            "full" -> "完整回報"
            else -> item.kind
        }
        holder.tvUser.text = "[$kindLabel] ${item.target}"

        // Time (附狀態，非 pending 時顯示)
        holder.tvTime.text = item.createdAt.take(10) +
            if (item.status.isNotEmpty() && item.status != "pending") " · ${item.status}" else ""

        // Type badge
        holder.tvType.text = item.fraudType
        val typeBg = GradientDrawable().apply {
            cornerRadius = 4f * dp
            setColor(Color.parseColor("#1AA63D2F"))
        }
        holder.tvType.background = typeBg
        holder.tvType.setTextColor(Color.parseColor("#A63D2F"))

        // Description（含案件編號）
        holder.tvDesc.text = buildString {
            append(item.content.ifEmpty { "無描述" })
            if (!item.caseNumber.isNullOrEmpty()) {
                append("\n案件編號：${item.caseNumber}")
            }
        }
    }

    override fun getItemCount() = items.size
}
