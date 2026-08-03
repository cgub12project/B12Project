package com.frauddetector.db

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "captured_notifications")
data class CapturedNotification(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    /** 來源 App 顯示名稱: "LINE", "WhatsApp", "Messenger", "簡訊", "Gmail", "Outlook" */
    val app: String,
    /** 發送者名稱或號碼 */
    val sender: String,
    /** 訊息或郵件內容 */
    val content: String,
    /** 通知時間 (epoch millis) */
    val timestamp: Long,
    /** 分類: "message" or "email" */
    val type: String,
    /** 來源 package name (e.g. com.linecorp.LINE) */
    val packageName: String = "",
    /** 群組名稱（如 LINE 群組），私訊為空字串 */
    val groupName: String = "",
    /** 是否已讀 */
    val isRead: Boolean = false,
    /** AI 風險等級快取："high"/"mid"/"safe"；null 代表尚未偵測 */
    val riskLevel: String? = null,
    /** AI 判斷的詐騙類型快取（如 "投資詐騙"），無風險時為 null */
    val scamType: String? = null,
    /** AI 判定理由快取（取第一條 reason），無風險時為 null */
    val aiReason: String? = null,
    /** AI 判定信心值快取（0.0–1.0），對話詳情頁「風險評分」欄位以此換算成 0-100 分顯示；null 代表尚未偵測 */
    val confidence: Double? = null
)
