/**
 * MailMessageDetailActivity.kt — 已連接信箱真實郵件的詳情頁
 *
 * 所屬模組：ui/detail（詳情模組）
 *
 * 顯示 [MailMessageItem] 已有的所有欄位：風險判定結果（來自資料庫）+ 主旨／寄件者／
 * 預覽片段（後端當次即時向 Gmail API／Graph API 取回，見 MailMessageItem 的說明）。
 *
 * App 本身不會、也不儲存信件全文（見給後端的架構提案文件裡的隱私考量），要看完整內容
 * 只能靠「開啟原信」按鈕連到 Gmail／Outlook 官方頁面——這個深連結網址是照 Gmail／Outlook
 * web 已知的網址格式組出來的，還沒有實機驗證過在各種裝置/是否安裝對應 App 的情況下
 * 都能正確跳轉，如果打不開麻煩回報，再依實測結果調整。
 */
package com.frauddetector.ui.detail

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.View
import android.widget.TextView
import android.widget.Toast
import com.frauddetector.R
import com.frauddetector.network.MailMessageItem
import com.frauddetector.service.RagDetector
import com.frauddetector.ui.BaseActivity
import com.google.android.material.button.MaterialButton
import java.text.SimpleDateFormat
import java.time.Instant
import java.util.Date
import java.util.Locale

class MailMessageDetailActivity : BaseActivity() {

    companion object {
        const val EXTRA_MAIL_ITEM = "mail_item"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_mail_message_detail)

        findViewById<View>(R.id.btnBack).setOnClickListener { finish() }

        @Suppress("DEPRECATION")
        val item = intent.getSerializableExtra(EXTRA_MAIL_ITEM) as? MailMessageItem
        if (item == null) {
            Toast.makeText(this, "找不到這封信的資料", Toast.LENGTH_SHORT).show()
            finish()
            return
        }

        val providerLabel = if (item.provider == "gmail") "Gmail" else "Outlook"
        val riskLabel = when (item.riskLevel) {
            "high" -> "高風險"
            "mid" -> "可疑"
            else -> "安全"
        }
        val riskColor = when (item.riskLevel) {
            "high" -> "#A63D2F"
            "mid" -> "#C46B4A"
            else -> "#7A9E7E"
        }

        findViewById<TextView>(R.id.tvRiskBadge).apply {
            text = "$riskLabel${item.scamType?.let { " · $it" } ?: ""}"
            setBackgroundColor(android.graphics.Color.parseColor(riskColor))
        }
        findViewById<TextView>(R.id.tvSubject).text = item.subject ?: "(無法取得主旨)"
        findViewById<TextView>(R.id.tvSender).text = "寄件者：${item.sender ?: "(無法取得寄件者)"}"

        val receivedStr = try {
            SimpleDateFormat("yyyy/MM/dd HH:mm", Locale.getDefault()).format(Date(Instant.parse(item.receivedAt).toEpochMilli()))
        } catch (e: Exception) {
            item.receivedAt
        }
        findViewById<TextView>(R.id.tvMeta).text = "$providerLabel · ${item.accountEmail} · $receivedStr"

        findViewById<TextView>(R.id.tvRiskScore).text =
            RagDetector.computeMessageRiskScore(item.riskLevel, item.confidence).toString()

        findViewById<TextView>(R.id.tvReasons).text = if (item.reasons.isNotEmpty()) {
            item.reasons.joinToString("\n") { "• $it" }
        } else {
            "（沒有額外的判定理由）"
        }

        if (!item.advice.isNullOrBlank()) {
            findViewById<View>(R.id.tvAdviceLabel).visibility = View.VISIBLE
            findViewById<TextView>(R.id.tvAdvice).apply {
                visibility = View.VISIBLE
                text = item.advice
            }
        }

        findViewById<TextView>(R.id.tvPreview).text = item.preview
            ?: if (!item.previewAvailable) "內容暫時無法取得（授權可能已失效，請至設定重新連接）" else "（無預覽內容）"

        findViewById<MaterialButton>(R.id.btnOpenOriginal).setOnClickListener {
            openOriginal(item)
        }
    }

    /**
     * 嘗試用 Gmail／Outlook 官方的 web 深連結網址開啟原信。這兩個網址格式是照公開文件/
     * 已知慣例組的，不保證所有裝置或帳號狀態都適用——打不開的話至少會正常跳出「找不到可
     * 開啟的 App」，不會讓整個 App 崩潰。
     */
    private fun openOriginal(item: MailMessageItem) {
        val url = if (item.provider == "gmail") {
            "https://mail.google.com/mail/u/0/#all/${item.messageId}"
        } else {
            "https://outlook.office.com/mail/deeplink/read/${item.messageId}"
        }
        try {
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
        } catch (e: Exception) {
            Toast.makeText(this, "無法開啟原信，請自行到信箱 App 查看", Toast.LENGTH_SHORT).show()
        }
    }
}
