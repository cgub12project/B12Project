/**
 * PhoneApi.kt — 電話號碼查詢 API 介面定義
 *
 * 所屬模組：network（網路層）
 *
 * 使用方式：透過 [ApiClient.phoneApi] 取得此介面的實例。
 */
package com.frauddetector.network

import retrofit2.Call
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.Path
import retrofit2.http.Query

interface PhoneApi {

    /**
     * 查詢電話號碼資料庫：支援關鍵字搜尋、風險等級篩選與分頁。
     */
    @GET("api/v1/phones")
    fun listPhones(
        @Header("Authorization") token: String,
        @Query("search") search: String? = null,
        @Query("risk_level") riskLevel: String? = null,
        @Query("limit") limit: Int = 50,
        @Query("offset") offset: Int = 0
    ): Call<PhoneListResponse>

    /**
     * 查詢電話號碼詳情：風險資訊 + 社群回報列表。
     */
    @GET("api/v1/phones/{phone_number}")
    fun getPhoneDetail(
        @Header("Authorization") token: String,
        @Path("phone_number") phoneNumber: String
    ): Call<PhoneDetailResponse>
}
