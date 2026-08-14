/**
 * MailModels.kt — Gmail/Outlook 信箱連接與已分析信件的回應資料模型
 *
 * 所屬模組：network（網路層）
 *
 * 對應 /api/v1/mail 開頭的系列端點。
 */
package com.frauddetector.network

import com.google.gson.annotations.SerializedName
import java.io.Serializable

data class MailConnectResponse(
    val provider: String,
    @SerializedName("authorize_url") val authorizeUrl: String,
    @SerializedName("expires_in_minutes") val expiresInMinutes: Int
)

data class MailAccountOut(
    val id: Int,
    val provider: String,
    @SerializedName("email_address") val emailAddress: String,
    @SerializedName("is_active") val isActive: Boolean,
    @SerializedName("connected_at") val connectedAt: String,
    @SerializedName("last_synced_at") val lastSyncedAt: String? = null,
    @SerializedName("last_sync_error") val lastSyncError: String? = null
)

data class MailAccountsResponse(
    val total: Int,
    val items: List<MailAccountOut>
)

data class MailDisconnectResponse(
    val message: String,
    @SerializedName("deleted_analyses") val deletedAnalyses: Int
)

data class MailMessageItem(
    val id: Int,
    val provider: String,
    @SerializedName("message_id") val messageId: String,
    @SerializedName("received_at") val receivedAt: String,
    @SerializedName("account_email") val accountEmail: String,
    val subject: String? = null,
    val sender: String? = null,
    val preview: String? = null,
    @SerializedName("preview_available") val previewAvailable: Boolean,
    @SerializedName("is_scam") val isScam: Boolean,
    @SerializedName("risk_level") val riskLevel: String,
    @SerializedName("scam_type") val scamType: String? = null,
    val confidence: Double,
    val reasons: List<String> = emptyList(),
    val advice: String? = null,
    val model: String,
    @SerializedName("analyzed_at") val analyzedAt: String
) : Serializable

data class MailMessagesResponse(
    val total: Int,
    val items: List<MailMessageItem>
)

data class MailSyncAccountResult(
    @SerializedName("account_id") val accountId: Int,
    val provider: String,
    @SerializedName("email_address") val emailAddress: String,
    val fetched: Int,
    val analyzed: Int,
    val skipped: Int,
    val error: String? = null
)

data class MailSyncResponse(
    @SerializedName("synced_at") val syncedAt: String,
    val accounts: List<MailSyncAccountResult>
)

/** 郵件真封鎖請求 — 對應 POST /api/v1/mail/accounts/{account_id}/block-sender 的請求 body。 */
data class MailBlockSenderRequest(val sender: String)

/** 封鎖/解除封鎖寄件人的回應（block-sender 與 DELETE blocked-senders/{sender} 共用） */
data class MailBlockSenderResponse(
    val success: Boolean = true,
    val message: String? = null,
    @SerializedName("sender_address") val senderAddress: String? = null
)

data class MailBlockedSenderItem(
    val id: Int,
    @SerializedName("sender_address") val senderAddress: String,
    @SerializedName("provider_filter_id") val providerFilterId: String? = null,
    @SerializedName("created_at") val createdAt: String
)

data class MailBlockedSendersResponse(
    val total: Int,
    val items: List<MailBlockedSenderItem>
)

/**
 * 已連接信箱的真實郵件完整內容 — 對應 GET /api/v1/mail/messages/{analysis_id}/content。
 * 後端明確表示這支端點是設計給「回報詐騙郵件」用的（見 reportText 欄位已經幫忙組好
 * 「寄件者：...\n主旨：...\n\n內文」格式），不是給一般瀏覽用——一般查看完整信件
 * 走隱私考量更好的「開啟原信」深連結跳到 Gmail 網頁版，見 MailMessageDetailActivity。
 */
data class MailMessageContent(
    val id: Int,
    val provider: String,
    @SerializedName("message_id") val messageId: String,
    @SerializedName("account_id") val accountId: Int,
    @SerializedName("account_email") val accountEmail: String,
    @SerializedName("received_at") val receivedAt: String,
    val subject: String? = null,
    val sender: String? = null,
    val body: String? = null,
    @SerializedName("body_truncated") val bodyTruncated: Boolean = false,
    @SerializedName("report_text") val reportText: String,
    @SerializedName("is_scam") val isScam: Boolean,
    @SerializedName("risk_level") val riskLevel: String,
    @SerializedName("scam_type") val scamType: String? = null
)
