package com.frauddetector.db

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * 電話清單查詢結果的本機快取。
 *
 * 連網查詢（不含搜尋關鍵字的完整清單）成功時整批寫入，
 * 供下次查詢失敗（無網路／逾時）時退回顯示，避免完全無資料可看。
 */
@Entity(tableName = "cached_phones")
data class CachedPhone(
    @PrimaryKey val phoneNumber: String,
    val riskLevel: String,
    val fraudType: String?,
    val reportCount: Int,
    val lastReportedAt: String?,
    /** 這筆資料寫入快取的時間（epoch millis），用於畫面上顯示「最後更新於 X 分鐘前」 */
    val cachedAt: Long
)
