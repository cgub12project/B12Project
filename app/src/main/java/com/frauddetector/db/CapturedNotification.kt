package com.frauddetector.db

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(
    tableName = "captured_notifications",
    indices = [Index(value = ["notificationKey"], unique = true)]
)
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
    /**
     * 來源通知的識別碼（[android.service.notification.StatusBarNotification.getKey]，或摘要通知
     * 拆解時額外加上行號後綴），用來防止同一則通知被更新/重發時重複插入——同一支手機上
     * Gmail 常會針對同一封信重貼通知（例如標成已讀、內容補完），沒有這個欄位的話每次都會
     * 被當成全新的一筆插入。允許 null：開發者測試資料（[com.frauddetector.ui.main.SettingsFragment]
     * 的種子資料）不是真的通知，沒有這個值；SQLite 的 unique index 允許多筆 null 共存，不影響。
     */
    val notificationKey: String? = null,
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
