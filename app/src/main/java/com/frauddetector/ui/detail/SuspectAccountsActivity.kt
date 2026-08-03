/**
 * SuspectAccountsActivity.kt — 可疑帳號列表頁面
 *
 * 所屬模組：ui/detail（詳情模組）
 *
 * 呼叫 GET /api/v1/accounts 顯示可疑帳號列表，點擊項目進入 [AccountDetailActivity] 查看完整威脅檔案。
 * 目前作為 Demo 用的入口點（帳號威脅檔案原本靠訊息串連動導航進入，
 * 但本機通知擷取的訊息與後端 suspect_accounts 沒有現成的關聯，
 * 因此改由本頁直接列出已建檔的可疑帳號）。
 */
package com.frauddetector.ui.detail

import android.content.Intent
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import com.frauddetector.ui.BaseActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.frauddetector.R
import com.frauddetector.network.ApiClient
import com.frauddetector.network.SuspectAccountListResponse
import com.frauddetector.network.SuspectAccountOut
import com.frauddetector.network.TokenManager
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class SuspectAccountsActivity : BaseActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_suspect_accounts)

        findViewById<View>(R.id.btnBack).setOnClickListener { finish() }
        findViewById<RecyclerView>(R.id.rvAccounts).layoutManager = LinearLayoutManager(this)

        loadAccounts()
    }

    private fun loadAccounts() {
        val token = TokenManager(this).accessToken
        if (token.isNullOrEmpty()) {
            showEmpty("請先登入")
            return
        }

        ApiClient.accountApi.listAccounts("Bearer $token")
            .enqueue(object : Callback<SuspectAccountListResponse> {
                override fun onResponse(
                    call: Call<SuspectAccountListResponse>,
                    response: Response<SuspectAccountListResponse>
                ) {
                    if (response.isSuccessful) {
                        val items = response.body()?.items ?: emptyList()
                        if (items.isEmpty()) {
                            showEmpty("尚無可疑帳號紀錄（先透過訊息詳情或回報功能建立一筆帳號回報）")
                        } else {
                            findViewById<TextView>(R.id.tvEmpty).visibility = View.GONE
                            findViewById<RecyclerView>(R.id.rvAccounts).adapter =
                                SuspectAccountAdapter(items) { account ->
                                    startActivity(
                                        Intent(this@SuspectAccountsActivity, AccountDetailActivity::class.java)
                                            .putExtra(AccountDetailActivity.EXTRA_ACCOUNT_ID, account.id)
                                    )
                                }
                        }
                    } else {
                        showEmpty("載入失敗：${ApiClient.parseError(response.errorBody()?.string())}")
                    }
                }

                override fun onFailure(call: Call<SuspectAccountListResponse>, t: Throwable) {
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

private class SuspectAccountAdapter(
    private val items: List<SuspectAccountOut>,
    private val onClick: (SuspectAccountOut) -> Unit
) : RecyclerView.Adapter<SuspectAccountAdapter.VH>() {

    class VH(view: View) : RecyclerView.ViewHolder(view) {
        val tvUser: TextView = view.findViewById(R.id.tvReportUser)
        val tvTime: TextView = view.findViewById(R.id.tvReportTime)
        val tvType: TextView = view.findViewById(R.id.tvReportType)
        val tvDesc: TextView = view.findViewById(R.id.tvReportDesc)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val view = LayoutInflater.from(parent.context).inflate(R.layout.item_report, parent, false)
        return VH(view)
    }

    override fun onBindViewHolder(holder: VH, position: Int) {
        val item = items[position]
        val dp = holder.itemView.resources.displayMetrics.density

        val cardBg = GradientDrawable().apply {
            setColor(Color.parseColor("#FDFAF4"))
            cornerRadius = 12f * dp
            setStroke((1 * dp).toInt(), Color.parseColor("#1AC8C4C0"))
        }
        holder.itemView.background = cardBg

        holder.tvUser.text = "${item.platform} · ${item.accountName}"
        holder.tvTime.text = "回報 ${item.reportCount} 次"

        val riskColor = when (item.riskLevel) {
            "high" -> Color.parseColor("#A63D2F")
            "mid" -> Color.parseColor("#C46B4A")
            else -> Color.parseColor("#7A9E7E")
        }
        holder.tvType.text = "風險分 ${item.riskScore}"
        holder.tvType.setTextColor(riskColor)
        holder.tvType.background = GradientDrawable().apply {
            cornerRadius = 4f * dp
            setColor(Color.argb(25, Color.red(riskColor), Color.green(riskColor), Color.blue(riskColor)))
        }

        holder.tvDesc.text = item.externalAccountId?.let { "帳號 ID：$it" } ?: "點擊查看完整威脅檔案"

        holder.itemView.setOnClickListener { onClick(item) }
    }

    override fun getItemCount() = items.size
}
