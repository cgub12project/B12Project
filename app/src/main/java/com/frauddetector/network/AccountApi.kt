/**
 * AccountApi.kt — 可疑帳號查詢 API 介面定義
 *
 * 所屬模組：network（網路層）
 *
 * 使用方式：透過 [ApiClient.accountApi] 取得此介面的實例。
 */
package com.frauddetector.network

import retrofit2.Call
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.Path
import retrofit2.http.Query

interface AccountApi {

    /**
     * 查詢可疑帳號列表。
     *
     * @param token JWT 存取權杖，格式為 "Bearer {access_token}"
     * @param platform 平台篩選（選填）
     * @param search 帳號名稱／ID 關鍵字搜尋（選填）
     */
    @GET("api/v1/accounts")
    fun listAccounts(
        @Header("Authorization") token: String,
        @Query("platform") platform: String? = null,
        @Query("search") search: String? = null,
        @Query("limit") limit: Int = 50,
        @Query("offset") offset: Int = 0
    ): Call<SuspectAccountListResponse>

    /**
     * 查詢帳號威脅檔案（風險分數、觸發規則、AI 摘要、證據列表）。
     */
    @GET("api/v1/accounts/{account_id}")
    fun getAccountDetail(
        @Header("Authorization") token: String,
        @Path("account_id") accountId: Int
    ): Call<SuspectAccountDetailResponse>
}
