/**
 * PhoneModels.kt — 電話號碼查詢相關的回應資料模型
 *
 * 所屬模組：network（網路層）
 *
 * 對應 GET /api/v1/phones 與 GET /api/v1/phones/{phone_number}。
 */
package com.frauddetector.network

import com.google.gson.annotations.SerializedName

data class PhoneOut(
    val id: Int,
    @SerializedName("phone_number") val phoneNumber: String,
    @SerializedName("risk_level") val riskLevel: String,
    @SerializedName("fraud_type") val fraudType: String? = null,
    @SerializedName("report_count") val reportCount: Int,
    @SerializedName("last_reported_at") val lastReportedAt: String? = null
)

data class PhoneListResponse(
    val total: Int,
    val items: List<PhoneOut>
)

data class PhoneDetailResponse(
    val id: Int,
    @SerializedName("phone_number") val phoneNumber: String,
    @SerializedName("risk_level") val riskLevel: String,
    @SerializedName("fraud_type") val fraudType: String? = null,
    @SerializedName("report_count") val reportCount: Int,
    @SerializedName("last_reported_at") val lastReportedAt: String? = null,
    @SerializedName("created_at") val createdAt: String? = null,
    val reports: List<PhoneCommunityReportOut> = emptyList()
)

data class PhoneCommunityReportOut(
    val id: Int,
    @SerializedName("fraud_type") val fraudType: String,
    val content: String,
    val reporter: String,
    @SerializedName("created_at") val createdAt: String
)
