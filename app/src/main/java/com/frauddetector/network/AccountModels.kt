/**
 * AccountModels.kt — 可疑帳號查詢相關的回應資料模型
 *
 * 所屬模組：network（網路層）
 *
 * 對應 GET /api/v1/accounts 與 GET /api/v1/accounts/{account_id}。
 */
package com.frauddetector.network

import com.google.gson.annotations.SerializedName

data class SuspectAccountOut(
    val id: Int,
    val platform: String,
    @SerializedName("account_name") val accountName: String,
    @SerializedName("external_account_id") val externalAccountId: String? = null,
    @SerializedName("risk_score") val riskScore: Int,
    @SerializedName("risk_level") val riskLevel: String,
    @SerializedName("report_count") val reportCount: Int,
    @SerializedName("last_reported_at") val lastReportedAt: String? = null
)

data class SuspectAccountListResponse(
    val total: Int,
    val items: List<SuspectAccountOut>
)

data class SuspectAccountDetailResponse(
    val id: Int,
    val platform: String,
    @SerializedName("account_name") val accountName: String,
    @SerializedName("external_account_id") val externalAccountId: String? = null,
    @SerializedName("risk_score") val riskScore: Int,
    @SerializedName("risk_level") val riskLevel: String,
    @SerializedName("report_count") val reportCount: Int,
    @SerializedName("triggered_rules") val triggeredRules: List<String> = emptyList(),
    @SerializedName("ai_summary") val aiSummary: String? = null,
    @SerializedName("last_reported_at") val lastReportedAt: String? = null,
    @SerializedName("created_at") val createdAt: String? = null,
    @SerializedName("evidence_items") val evidenceItems: List<EvidenceItemOut> = emptyList()
)

data class EvidenceItemOut(
    val id: Int,
    @SerializedName("evidence_type") val evidenceType: String,
    val severity: String,   // "high"/"mid" 或後端定義的嚴重度字串
    val description: String,
    @SerializedName("occurred_at") val occurredAt: String? = null
)
