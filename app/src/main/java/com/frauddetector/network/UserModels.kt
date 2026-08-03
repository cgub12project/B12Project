/**
 * UserModels.kt — 使用者個人資料與設定相關的資料模型
 *
 * 所屬模組：network（網路層）
 *
 * 對應 GET/PATCH /api/v1/users/me 與 GET/PUT /api/v1/users/me/settings。
 * [UserOut] 定義於 AuthModels.kt（登入回應與此處共用同一模型）。
 */
package com.frauddetector.network

import com.google.gson.annotations.SerializedName

data class UserUpdateRequest(
    val name: String? = null,
    @SerializedName("avatar_url") val avatarUrl: String? = null
)

data class UserSettingsOut(
    @SerializedName("message_monitoring") val messageMonitoring: Boolean,
    @SerializedName("email_scanning") val emailScanning: Boolean,
    @SerializedName("call_detection") val callDetection: Boolean,
    @SerializedName("quick_login") val quickLogin: Boolean,
    @SerializedName("high_risk_alert") val highRiskAlert: Boolean,
    @SerializedName("daily_report") val dailyReport: Boolean,
    @SerializedName("updated_at") val updatedAt: String? = null
)

data class UserSettingsUpdateRequest(
    @SerializedName("message_monitoring") val messageMonitoring: Boolean? = null,
    @SerializedName("email_scanning") val emailScanning: Boolean? = null,
    @SerializedName("call_detection") val callDetection: Boolean? = null,
    @SerializedName("quick_login") val quickLogin: Boolean? = null,
    @SerializedName("high_risk_alert") val highRiskAlert: Boolean? = null,
    @SerializedName("daily_report") val dailyReport: Boolean? = null
)
