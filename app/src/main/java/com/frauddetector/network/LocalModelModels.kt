/**
 * LocalModelModels.kt — 地端模型下載相關的資料模型
 *
 * 所屬模組：network（網路層）
 *
 * 對應 GET /api/v1/local-model/manifest（2026-09-02 後端依
 * dev-notes/後端協助_地端模型私有下載部署需求.txt 實作完成）。
 */
package com.frauddetector.network

import com.google.gson.annotations.SerializedName

/**
 * 地端模型的版本資訊與短效簽章下載網址。
 *
 * [downloadUrl] 本身已內含授權簽章，下載時不需要（也不應該）再帶 Authorization 標頭；
 * 簽章預設 24 小時到期，過期後重新呼叫 manifest 換一組即可，已下載的部分可以續傳。
 */
data class LocalModelManifest(
    /** 模型版本，例："4.1" */
    val version: String,
    /** 模型檔名，App 存檔時沿用 */
    @SerializedName("file_name") val fileName: String,
    /** 模型檔大小（bytes），用來顯示下載量與檢查儲存空間 */
    @SerializedName("size_bytes") val sizeBytes: Long,
    /** 模型檔的 SHA-256，下載完成後必須核對通過才能啟用地端模式 */
    val sha256: String,
    @SerializedName("download_url") val downloadUrl: String,
    /** 下載網址到期時間（UTC ISO 字串） */
    @SerializedName("expires_at") val expiresAt: String
)
