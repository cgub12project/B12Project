/**
 * ReportApi.kt — 舉報相關 API 介面定義
 *
 * 所屬模組：network（網路層）
 *
 * 本檔案定義了詐騙舉報（Report）相關的 Retrofit API 介面，
 * 提供電話號碼舉報與帳號/訊息舉報兩個端點。
 * 所有端點皆需攜帶 JWT Token 進行身份驗證（透過 Authorization header）。
 *
 * 使用方式：透過 [ApiClient.reportApi] 取得此介面的實例。
 */
package com.frauddetector.network

import retrofit2.Call
import retrofit2.http.Body
import retrofit2.http.Header
import retrofit2.http.POST
import retrofit2.http.Path

/**
 * 舉報 API 介面 — 定義所有與詐騙舉報相關的 HTTP 端點。
 *
 * 使用者在 App 中可針對可疑電話號碼或帳號提交舉報，
 * 舉報資料會透過這些端點傳送至後端進行記錄與分析。
 * 所有方法皆需傳入 Authorization header（格式為 "Bearer {token}"）。
 */
interface ReportApi {

    /**
     * 舉報可疑電話號碼。
     *
     * 針對特定電話號碼提交詐騙舉報，包含詐騙類型與舉報內容。
     * 電話號碼透過 URL 路徑參數傳遞。
     *
     * @param token JWT 存取權杖，格式為 "Bearer {access_token}"
     * @param phoneNumber 被舉報的電話號碼，作為 URL 路徑的一部分
     * @param body [PhoneReportRequest] 包含詐騙類型（fraudType）、內容（content）與描述（description）
     * @return [Call]<[Void]> 成功時回傳 HTTP 200（無回應內容）
     */
    @POST("api/v1/reports/phone/{phone_number}")
    fun reportPhone(
        @Header("Authorization") token: String,
        @Path("phone_number") phoneNumber: String,
        @Body body: PhoneReportRequest
    ): Call<Void>

    /**
     * 舉報可疑帳號/訊息。
     *
     * 針對特定社群帳號或訊息內容提交詐騙舉報，
     * 包含平台來源、帳號資訊、詐騙類型與舉報內容。
     *
     * @param token JWT 存取權杖，格式為 "Bearer {access_token}"
     * @param body [MessageReportBody] 包含詐騙類型、內容、平台、帳號名稱等資訊
     * @return [Call]<[Void]> 成功時回傳 HTTP 200（無回應內容）
     */
    @POST("api/v1/reports/account")
    fun reportAccount(
        @Header("Authorization") token: String,
        @Body body: MessageReportBody
    ): Call<Void>
}
