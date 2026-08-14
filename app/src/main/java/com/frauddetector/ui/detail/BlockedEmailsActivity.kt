/**
 * BlockedEmailsActivity.kt — 封鎖信箱清單頁面
 *
 * 所屬模組：ui/detail（詳情模組）
 *
 * 顯示目前封鎖的郵件寄件人，整合兩種封鎖：
 * - 本機封鎖（[BlockedEmailsManager]）：純本地清單，只影響「郵件」分頁是否顯示，不動到真實信箱。
 * - 真封鎖（後端 `block-sender` API）：對已連接信箱（Gmail/Outlook）建立真的過濾規則，
 *   對方的信真的進不了收件匣，見 [EmailFragment.blockSenderOnBackend]。
 *
 * 兩種封鎖來源不同、且不一定同時存在同一筆——同一個寄件人可能只本機隱藏、只真封鎖（例如
 * 之前用 API 直接呼叫、沒有走 App 封鎖按鈕產生的紀錄），或兩者都有。合併顯示以「乾淨的
 * email 地址」為 key（[extractEmailAddress]），本機清單裡非 email 格式的顯示名稱
 * （通知擷取項目常見）沒有真封鎖對應資料，只會顯示本機隱藏。
 */
package com.frauddetector.ui.detail

import android.graphics.Color
import android.graphics.drawable.GradientDrawable
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
import com.frauddetector.network.TokenManager
import com.frauddetector.service.BlockedEmailsManager
import com.frauddetector.ui.BaseActivity
import java.io.IOException
import java.util.concurrent.Executors

/** 合併後的單筆列表資料：同一個寄件人可能同時有本機封鎖跟真封鎖，兩者各自獨立解除 */
private data class BlockedEmailRow(
    val label: String,
    val localSender: String?,
    val realAccountId: Int?,
    val realSenderAddress: String?
) {
    val isLocalBlocked get() = localSender != null
    val isRealBlocked get() = realAccountId != null && realSenderAddress != null
}

class BlockedEmailsActivity : BaseActivity() {

    private lateinit var adapter: BlockedEmailAdapter
    private val executor = Executors.newSingleThreadExecutor()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_blocked_emails)

        findViewById<View>(R.id.btnBack).setOnClickListener { finish() }

        adapter = BlockedEmailAdapter { row -> unblock(row) }
        findViewById<RecyclerView>(R.id.rvBlockedEmails).apply {
            layoutManager = LinearLayoutManager(this@BlockedEmailsActivity)
            adapter = this@BlockedEmailsActivity.adapter
        }

        refresh()
    }

    /**
     * Pass 1：本機清單同步、立即可用，先顯示。
     * Pass 2：背景查詢所有已連接信箱的真封鎖清單，查完再合併更新一次畫面。
     * 真封鎖查詢失敗（沒登入/沒連接信箱/網路異常）不影響本機清單先顯示的結果，靜默降級。
     */
    private fun refresh() {
        val localSenders = BlockedEmailsManager.getAll(this).sorted()
        val localRows = localSenders.map { sender ->
            BlockedEmailRow(label = sender, localSender = sender, realAccountId = null, realSenderAddress = null)
        }
        publishRows(localRows)

        val token = TokenManager(this).accessToken ?: return
        executor.execute {
            try {
                val accounts = ApiClient.mailApi.listMailAccounts("Bearer $token").execute().body()?.items ?: emptyList()
                val realEntries = mutableListOf<Pair<Int, String>>() // accountId to senderAddress
                for (account in accounts) {
                    val blocked = ApiClient.mailApi.getBlockedSenders("Bearer $token", account.id).execute().body()
                    blocked?.items?.forEach { realEntries.add(account.id to it.senderAddress) }
                }
                val merged = mergeRows(localSenders, realEntries)
                runOnUiThread { publishRows(merged) }
            } catch (e: IOException) {
                // 真封鎖清單查詢失敗，維持只顯示本機清單
            }
        }
    }

    private fun mergeRows(localSenders: List<String>, realEntries: List<Pair<Int, String>>): List<BlockedEmailRow> {
        // 若同一 email 被多個帳號各自封鎖，僅保留最後一筆 account_id 做解封用
        val realByAddress: Map<String, Int> = realEntries.associate { (accountId, address) -> address to accountId }
        val matchedAddresses = mutableSetOf<String>()
        val rows = localSenders.map { sender ->
            val address = extractEmailAddress(sender)
            val accountId = realByAddress[address]
            if (accountId != null) matchedAddresses.add(address)
            BlockedEmailRow(
                label = sender,
                localSender = sender,
                realAccountId = accountId,
                realSenderAddress = if (accountId != null) address else null
            )
        }
        val realOnlyRows = realEntries
            .filter { (_, address) -> address !in matchedAddresses }
            .distinctBy { it.second }
            .map { (accountId, address) ->
                BlockedEmailRow(label = address, localSender = null, realAccountId = accountId, realSenderAddress = address)
            }
        return (rows + realOnlyRows).sortedBy { it.label }
    }

    private fun extractEmailAddress(raw: String): String {
        val match = Regex("<([^>]+)>").find(raw)
        return match?.groupValues?.get(1) ?: raw
    }

    private fun publishRows(rows: List<BlockedEmailRow>) {
        adapter.updateItems(rows)
        findViewById<TextView>(R.id.tvEmpty).visibility = if (rows.isEmpty()) View.VISIBLE else View.GONE
    }

    /** 本機封鎖跟真封鎖各自獨立解除；兩者都有的話兩邊都解，任一邊失敗不影響另一邊已經解除的結果 */
    private fun unblock(row: BlockedEmailRow) {
        if (row.isLocalBlocked) {
            BlockedEmailsManager.toggle(this, row.localSender!!)
        }
        if (row.isRealBlocked) {
            val token = TokenManager(this).accessToken
            if (token.isNullOrEmpty()) {
                Toast.makeText(this, "本機已解封，但需要登入才能解除 Gmail 端封鎖", Toast.LENGTH_LONG).show()
                refresh()
                return
            }
            executor.execute {
                try {
                    val response = ApiClient.mailApi.unblockSender(
                        "Bearer $token", row.realAccountId!!, row.realSenderAddress!!
                    ).execute()
                    runOnUiThread {
                        if (response.isSuccessful) {
                            Toast.makeText(this, "已解除 Gmail 端封鎖：${row.realSenderAddress}", Toast.LENGTH_SHORT).show()
                        } else {
                            val err = ApiClient.parseError(response.errorBody()?.string())
                            Toast.makeText(this, "Gmail 端解封失敗：$err", Toast.LENGTH_LONG).show()
                        }
                        refresh()
                    }
                } catch (e: IOException) {
                    runOnUiThread {
                        Toast.makeText(this, "網路異常，Gmail 端解封未完成", Toast.LENGTH_SHORT).show()
                        refresh()
                    }
                }
            }
        } else {
            refresh()
        }
    }
}

private class BlockedEmailAdapter(
    private val onUnblock: (BlockedEmailRow) -> Unit
) : RecyclerView.Adapter<BlockedEmailAdapter.VH>() {

    private var items: List<BlockedEmailRow> = emptyList()

    class VH(view: View) : RecyclerView.ViewHolder(view) {
        val tvSender: TextView = view.findViewById(R.id.tvBlockedEmail)
        val tvStatus: TextView = view.findViewById(R.id.tvBlockedEmailStatus)
        val tvUnblock: TextView = view.findViewById(R.id.tvUnblock)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val view = LayoutInflater.from(parent.context).inflate(R.layout.item_blocked_email, parent, false)
        return VH(view)
    }

    override fun onBindViewHolder(holder: VH, position: Int) {
        val row = items[position]
        val dp = holder.itemView.resources.displayMetrics.density

        holder.tvSender.text = row.label
        holder.tvStatus.text = when {
            row.isLocalBlocked && row.isRealBlocked -> "本機隱藏 + Gmail 已封鎖"
            row.isRealBlocked -> "Gmail 已封鎖（對方的信進不了收件匣）"
            else -> "僅本機隱藏（郵件分頁看不到，對方仍寄得進來）"
        }
        holder.itemView.background = GradientDrawable().apply {
            setColor(Color.parseColor("#FDFAF4"))
            cornerRadius = 14f * dp
            setStroke((1 * dp).toInt(), Color.parseColor("#1AC8C4C0"))
        }
        holder.tvUnblock.setOnClickListener { onUnblock(row) }
    }

    override fun getItemCount() = items.size

    fun updateItems(newItems: List<BlockedEmailRow>) {
        items = newItems
        notifyDataSetChanged()
    }
}
