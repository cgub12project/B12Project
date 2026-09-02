/**
 * RagModels.kt — RAG 詐騙偵測相關的請求與回應資料模型
 *
 * 所屬模組：network（網路層）
 *
 * 對應兩支端點：
 * - POST /api/v1/rag/detect：以單段訊息文字換取 AI 風險判斷結果
 * - POST /api/v1/rag/detect-conversation：以整段對話換取風險判斷 + 詐騙階段
 *   （2026-09-02 後端新增，見 [RagDetectConversationResponse]）
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
    /**
     * 校準後的詐騙機率（0.0-1.0，2026-09-02 後端新增）。
     *
     * 跟 [confidence] 不同：confidence 是「AI 對這個判斷有多確定」，安全訊息也可能有高
     * 信心值，不能直接當風險程度用（見 [com.frauddetector.service.RagDetector.computeMessageRiskScore]
     * 的實測說明）；risk_score 則是後端用評測結果擬合的校準表換算出來的機率，可以直接
     * 當「有多危險」解讀，也可以跨判定來源比較排序。
     *
     * 校準表缺漏或與目前模型不符時後端會回 null，地端模型判斷（[com.frauddetector.service.LocalModelDetector]）
     * 也沒有這個值，因此仍需保留舊的 risk_level + confidence 換算法當備援。
     */
    @SerializedName("risk_score") val riskScore: Double? = null,
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

/**
 * 對話中的一則訊息（POST /api/v1/rag/detect-conversation 的輸入單位）。
 *
 * @param sender 只接受 "them"（可疑對象）或 "me"（使用者本人）。App 的訊息來源是通知
 *   側錄與簡訊收件匣，抓得到的都是「對方傳進來的」，因此實際上全部是 "them"。
 * @param text 訊息內容，後端限制 1-4000 字。
 */
data class ConversationMessage(
    val sender: String,
    val text: String,
    @SerializedName("sent_at") val sentAt: String? = null
)

/**
 * 對話級偵測請求。
 *
 * @param messages 依時間由舊到新排列；超過後端上限時由最舊的開始被捨棄。
 * @param previousStage 這個對話上次判定的階段，由 App 自己保存後回傳
 *   （後端不儲存任何對話內容）。沒帶的話，模型只看得到最近幾十則，
 *   視窗一旦滑過「索取財物」那幾則就會誤判成階段倒退。
 */
data class RagDetectConversationRequest(
    val messages: List<ConversationMessage>,
    @SerializedName("previous_stage") val previousStage: String? = null
)

/**
 * 對話級偵測結果：既有的偵測欄位 + 詐騙階段。
 *
 * 注意偵測欄位（isScam/riskLevel/...）來自「最後一則對方訊息」，跟 App 目前把整個
 * 對話視窗串接後丟 /rag/detect 的做法涵蓋範圍不同——串接版能抓到「群組裡多人互相
 * 佐證同一套話術」這種只看最後一句看不出來的模式（已用真實案例驗證，見
 * [com.frauddetector.service.RagDetector.detectConversationRisk]）。因此 App 的風險
 * 等級仍以串接版為準，這支端點只取階段相關欄位。
 */
data class RagDetectConversationResponse(
    @SerializedName("is_scam") val isScam: Boolean,
    @SerializedName("risk_level") val riskLevel: String,
    @SerializedName("scam_type") val scamType: String? = null,
    val confidence: Double = 0.0,
    @SerializedName("risk_score") val riskScore: Double? = null,
    val reasons: List<String> = emptyList(),
    val advice: String? = null,
    val model: String? = null,
    /** 詐騙階段代碼：contact／grooming／baiting／extraction／closing；非詐騙且無 previousStage 時為 null */
    val stage: String? = null,
    /** 階段的中文名稱，可直接顯示（如「索取財物」） */
    @SerializedName("stage_label") val stageLabel: String? = null,
    @SerializedName("stage_confidence") val stageConfidence: Double? = null,
    @SerializedName("stage_reasons") val stageReasons: List<String> = emptyList(),
    /** 對方下一步最可能的行動，用來提前提醒使用者 */
    @SerializedName("next_step_warning") val nextStepWarning: String? = null,
    /**
     * 階段判定來源：LLM 模型名稱／"stage-rule"（階段模型不可用，改用關鍵詞規則與前次
     * 階段推估，信心值偏低）／"stage-unavailable"（判不出來）。
     * 2026-09-02 實測後端目前一律回 stage-rule，UI 會據此標示「推估」。
     */
    @SerializedName("stage_model") val stageModel: String? = null
)
