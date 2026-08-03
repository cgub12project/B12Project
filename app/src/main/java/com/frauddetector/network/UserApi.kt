/**
 * UserApi.kt — 使用者個人資料與設定 API 介面定義
 *
 * 所屬模組：network（網路層）
 *
 * 使用方式：透過 [ApiClient.userApi] 取得此介面的實例。
 */
package com.frauddetector.network

import retrofit2.Call
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.PATCH
import retrofit2.http.PUT

interface UserApi {

    @GET("api/v1/users/me")
    fun getMe(@Header("Authorization") token: String): Call<UserOut>

    @PATCH("api/v1/users/me")
    fun updateMe(
        @Header("Authorization") token: String,
        @Body body: UserUpdateRequest
    ): Call<UserOut>

    @GET("api/v1/users/me/settings")
    fun getSettings(@Header("Authorization") token: String): Call<UserSettingsOut>

    @PUT("api/v1/users/me/settings")
    fun updateSettings(
        @Header("Authorization") token: String,
        @Body body: UserSettingsUpdateRequest
    ): Call<UserSettingsOut>
}
