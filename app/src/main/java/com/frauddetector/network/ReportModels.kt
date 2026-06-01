/**
 * ReportModels.kt — 舉報相關的請求資料模型
 *
 * 所屬模組：network（網路層）
 *
 * 本檔案定義了詐騙舉報 API 所需的請求（Request）資料模型，
 * 包含電話號碼舉報（[PhoneReportRequest]）與帳號/訊息舉報（[MessageReportBody]）。
 * 這些模型會透過 Gson 進行 JSON 序列化，
 * 並搭配 [SerializedName] 註解對應後端 FastAPI 的 snake_case 命名。
 */
package com.frauddetector.network

import com.google.gson.annotations.SerializedName

/**
 * 電話號碼舉報請求 — 對應 POST /api/v1/reports/phone/{phone_number} 的請求 body。
 *
 * 使用者針對可疑電話號碼提交舉報時所需的資料。
 */
data class PhoneReportRequest(
    /** 詐騙類型，例如 "假冒政府機關"、"假冒銀行客服"、"投資詐騙" 等；對應後端欄位 fraud_type */
    @SerializedName("fraud_type") val fraudType: String,
    /** 舉報的具體內容描述，例如詐騙對話的關鍵訊息 */
    val content: String,
    /** 補充描述（選填），提供更多舉報相關的細節說明；預設為 null */
    val description: String? = null
)

/**
 * 帳號/訊息舉報請求 — 對應 POST /api/v1/reports/account 的請求 body。
 *
 * 使用者針對可疑社群帳號或訊息內容提交舉報時所需的資料，
 * 相較於電話舉報，額外包含平台來源與帳號識別資訊。
 */
data class MessageReportBody(
    /** 詐騙類型，例如 "投資詐騙"、"交友詐騙"、"釣魚連結" 等；對應後端欄位 fraud_type */
    @SerializedName("fraud_type") val fraudType: String,
    /** 舉報的具體內容描述，例如可疑訊息的文字內容 */
    val content: String,
    /** 訊息來源平台，例如 "LINE"、"WhatsApp"、"Messenger"、"簡訊" */
    val platform: String,
    /** 被舉報的帳號顯示名稱；對應後端欄位 account_name */
    @SerializedName("account_name") val accountName: String,
    /** 被舉報的帳號 ID（選填），例如 LINE ID 或用戶名稱；對應後端欄位 account_id；預設為 null */
    @SerializedName("account_id") val accountId: String? = null,
    /** 補充描述（選填），提供更多舉報相關的細節說明；預設為 null */
    val description: String? = null
)
