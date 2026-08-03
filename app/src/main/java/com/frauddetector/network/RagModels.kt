/**
 * RagModels.kt — RAG 詐騙偵測相關的請求與回應資料模型
 *
 * 所屬模組：network（網路層）
 *
 * 對應 POST /api/v1/rag/detect：以訊息文字換取 AI 風險判斷結果。
 */
package com.frauddetector.network

import com.google.gson.annotations.SerializedName

data class RagDetectRequest(
    val message: String
)

data class RagDetectResponse(
    @SerializedName("is_scam") val isScam: Boolean,
    @SerializedName("risk_level") val riskLevel: String,   // "high", "mid", "safe"
    @SerializedName("scam_type") val scamType: String? = null,
    val confidence: Double = 0.0,
    val reasons: List<String> = emptyList(),
    val advice: String? = null,
    @SerializedName("similar_cases") val similarCases: List<SimilarCase> = emptyList(),
    val model: String? = null
)

data class SimilarCase(
    val content: String,
    @SerializedName("scam_type") val scamType: String,
    val similarity: Double,
    @SerializedName("is_scam") val isScam: Boolean = true
)
