/**
 * MailAccountsActivity.kt — 已連接信箱管理頁面
 *
 * 所屬模組：ui/detail（詳情模組）
 *
 * 顯示目前已連接的 Gmail/Outlook 信箱（[MailApi.listMailAccounts]），可以新增連接
 * （開瀏覽器導到後端提供的授權網址，授權完成後端會轉址回 `flashapp://mail-callback`，
 * 見 [com.frauddetector.ui.auth.MailOAuthCallbackActivity]）或中斷既有連接。
 */
package com.frauddetector.ui.detail

import android.content.Intent
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import android.widget.Toast
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.frauddetector.R
import com.frauddetector.network.ApiClient
import com.frauddetector.network.MailAccountOut
import com.frauddetector.network.MailAccountsResponse
import com.frauddetector.network.MailConnectResponse
import com.frauddetector.network.MailDisconnectResponse
import com.frauddetector.network.TokenManager
import com.frauddetector.ui.BaseActivity
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class MailAccountsActivity : BaseActivity() {

    private lateinit var adapter: MailAccountAdapter

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_mail_accounts)

        findViewById<View>(R.id.btnBack).setOnClickListener { finish() }

        adapter = MailAccountAdapter { account -> disconnectAccount(account) }
        findViewById<RecyclerView>(R.id.rvMailAccounts).apply {
            layoutManager = LinearLayoutManager(this@MailAccountsActivity)
            adapter = this@MailAccountsActivity.adapter
        }

        findViewById<View>(R.id.btnConnectGmail).setOnClickListener { connect("gmail") }
        findViewById<View>(R.id.btnConnectOutlook).setOnClickListener { connect("outlook") }
    }

    /** 從瀏覽器授權完成、或中斷連接跳回來後，畫面回到前景時重新整理一次清單 */
    override fun onResume() {
        super.onResume()
        refresh()
    }

    private fun connect(provider: String) {
        val token = TokenManager(this).accessToken
        if (token.isNullOrEmpty()) {
            Toast.makeText(this, "請先登入", Toast.LENGTH_SHORT).show()
            return
        }
        ApiClient.mailApi.connectMailbox("Bearer $token", provider)
            .enqueue(object : Callback<MailConnectResponse> {
                override fun onResponse(call: Call<MailConnectResponse>, response: Response<MailConnectResponse>) {
                    val url = response.body()?.authorizeUrl
                    if (response.isSuccessful && !url.isNullOrEmpty()) {
                        startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                    } else {
                        Toast.makeText(
                            this@MailAccountsActivity,
                            "取得授權網址失敗：${ApiClient.parseError(response.errorBody()?.string())}",
                            Toast.LENGTH_SHORT
                        ).show()
                    }
                }

                override fun onFailure(call: Call<MailConnectResponse>, t: Throwable) {
                    Toast.makeText(this@MailAccountsActivity, "網路錯誤：${t.message}", Toast.LENGTH_SHORT).show()
                }
            })
    }

    private fun refresh() {
        val token = TokenManager(this).accessToken ?: return
        ApiClient.mailApi.listMailAccounts("Bearer $token")
            .enqueue(object : Callback<MailAccountsResponse> {
                override fun onResponse(call: Call<MailAccountsResponse>, response: Response<MailAccountsResponse>) {
                    if (!response.isSuccessful) return
                    val items = response.body()?.items ?: emptyList()
                    adapter.updateItems(items)
                    findViewById<TextView>(R.id.tvEmpty).visibility = if (items.isEmpty()) View.VISIBLE else View.GONE
                }

                override fun onFailure(call: Call<MailAccountsResponse>, t: Throwable) {
                    Toast.makeText(this@MailAccountsActivity, "查詢已連接信箱失敗：${t.message}", Toast.LENGTH_SHORT).show()
                }
            })
    }

    private fun disconnectAccount(account: MailAccountOut) {
        val token = TokenManager(this).accessToken ?: return
        ApiClient.mailApi.disconnectMailAccount("Bearer $token", account.id)
            .enqueue(object : Callback<MailDisconnectResponse> {
                override fun onResponse(call: Call<MailDisconnectResponse>, response: Response<MailDisconnectResponse>) {
                    if (response.isSuccessful) {
                        Toast.makeText(this@MailAccountsActivity, "已中斷連接：${account.emailAddress}", Toast.LENGTH_SHORT).show()
                        refresh()
                    } else {
                        Toast.makeText(this@MailAccountsActivity, "中斷連接失敗", Toast.LENGTH_SHORT).show()
                    }
                }

                override fun onFailure(call: Call<MailDisconnectResponse>, t: Throwable) {
                    Toast.makeText(this@MailAccountsActivity, "網路錯誤：${t.message}", Toast.LENGTH_SHORT).show()
                }
            })
    }
}

private class MailAccountAdapter(
    private val onDisconnect: (MailAccountOut) -> Unit
) : RecyclerView.Adapter<MailAccountAdapter.VH>() {

    private var items: List<MailAccountOut> = emptyList()

    class VH(view: View) : RecyclerView.ViewHolder(view) {
        val tvEmail: TextView = view.findViewById(R.id.tvMailAccountEmail)
        val tvStatus: TextView = view.findViewById(R.id.tvMailAccountStatus)
        val tvDisconnect: TextView = view.findViewById(R.id.tvMailAccountDisconnect)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val view = LayoutInflater.from(parent.context).inflate(R.layout.item_mail_account, parent, false)
        return VH(view)
    }

    override fun onBindViewHolder(holder: VH, position: Int) {
        val item = items[position]
        val dp = holder.itemView.resources.displayMetrics.density
        val providerLabel = if (item.provider == "gmail") "Gmail" else "Outlook"

        holder.tvEmail.text = item.emailAddress
        holder.tvStatus.text = when {
            !item.isActive -> "$providerLabel · 授權已失效，請重新連接"
            item.lastSyncError != null -> "$providerLabel · 上次同步失敗：${item.lastSyncError}"
            item.lastSyncedAt != null -> "$providerLabel · 上次同步：${item.lastSyncedAt.take(16).replace("T", " ")}"
            else -> "$providerLabel · 尚未同步過"
        }

        holder.itemView.background = GradientDrawable().apply {
            setColor(Color.parseColor("#FDFAF4"))
            cornerRadius = 14f * dp
            setStroke((1 * dp).toInt(), Color.parseColor("#1AC8C4C0"))
        }
        holder.tvDisconnect.setOnClickListener { onDisconnect(item) }
    }

    override fun getItemCount() = items.size

    fun updateItems(newItems: List<MailAccountOut>) {
        items = newItems
        notifyDataSetChanged()
    }
}
