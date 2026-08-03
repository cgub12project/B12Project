/**
 * AuthApi.kt — 認證相關 API 介面定義
 *
 * 所屬模組：network（網路層）
 *
 * 本檔案定義了使用者認證（Authentication）相關的 Retrofit API 介面，
 * 涵蓋登入、註冊、忘記密碼、OTP 驗證、重設密碼、第三方 OAuth 登入等端點。
 * 所有端點皆對應後端 FastAPI 的 /api/v1/auth/ 路徑下的路由。
 *
 * 使用方式：透過 [ApiClient.authApi] 取得此介面的實例。
 */
package com.frauddetector.network

import retrofit2.Call
import retrofit2.http.Body
import retrofit2.http.Header
import retrofit2.http.POST

/**
 * 認證 API 介面 — 定義所有與使用者身份驗證相關的 HTTP 端點。
 *
 * 所有方法皆使用 POST 請求，回傳 Retrofit 的 [Call] 物件，
 * 供呼叫端以同步（execute）或非同步（enqueue）方式執行。
 */
interface AuthApi {

    /**
     * 使用者登入。
     *
     * 以電子郵件與密碼進行身份驗證，成功後回傳 JWT Token。
     *
     * @param request [LoginRequest] 包含 email、password、rememberMe
     * @return [Call]<[TokenResponse]> 成功時回傳包含 access_token 與 refresh_token 的回應
     */
    @POST("api/v1/auth/login")
    fun login(@Body request: LoginRequest): Call<TokenResponse>

    /**
     * 使用者註冊。
     *
     * 以電子郵件、密碼與顯示名稱建立新帳號，成功後回傳 JWT Token。
     *
     * @param request [RegisterRequest] 包含 email、password、displayName
     * @return [Call]<[TokenResponse]> 成功時回傳包含 access_token 與 refresh_token 的回應
     */
    @POST("api/v1/auth/register")
    fun register(@Body request: RegisterRequest): Call<TokenResponse>

    /**
     * 忘記密碼 — 發送 OTP 驗證碼。
     *
     * 後端會發送一封包含 OTP 驗證碼的郵件至指定信箱。
     * 成功時回傳 HTTP 200（無 body），失敗時回傳錯誤訊息。
     *
     * @param request [ForgotPasswordRequest] 包含使用者的 email
     * @return [Call]<[Void]> 成功時無回應內容
     */
    @POST("api/v1/auth/forgot-password")
    fun forgotPassword(@Body request: ForgotPasswordRequest): Call<Void>

    /**
     * 驗證 OTP 驗證碼。
     *
     * 驗證使用者輸入的 OTP 是否與後端發送的一致，
     * 成功後回傳一次性 reset_token，供下一步 [resetPassword] 使用。
     *
     * @param request [VerifyOtpRequest] 包含 email 與使用者輸入的 otp
     * @return [Call]<[VerifyOtpResponse]> 成功時回傳 reset_token
     */
    @POST("api/v1/auth/verify-otp")
    fun verifyOtp(@Body request: VerifyOtpRequest): Call<VerifyOtpResponse>

    /**
     * 重設密碼。
     *
     * 在 OTP 驗證通過後，使用者可設定新密碼。
     * 需同時提供 email、OTP 與新密碼以完成重設。
     *
     * @param request [ResetPasswordRequest] 包含 email、otp、newPassword
     * @return [Call]<[Void]> 成功時無回應內容
     */
    @POST("api/v1/auth/reset-password")
    fun resetPassword(@Body request: ResetPasswordRequest): Call<Void>

    /**
     * 第三方 OAuth 登入。
     *
     * 以第三方身份提供者（如 Google、Facebook）的 Token 進行登入，
     * 後端驗證後回傳本系統的 JWT Token。
     *
     * @param request [OAuthRequest] 包含 provider（提供者名稱）與 token（第三方 Token）
     * @return [Call]<[TokenResponse]> 成功時回傳包含 access_token 與 refresh_token 的回應
     */
    @POST("api/v1/auth/oauth")
    fun oauthLogin(@Body request: OAuthRequest): Call<TokenResponse>

    /**
     * 以 refresh_token 換發新的權杖組。
     */
    @POST("api/v1/auth/refresh")
    fun refresh(@Body request: RefreshTokenRequest): Call<TokenResponse>

    /**
     * 更改密碼（需登入，驗證舊密碼後設定新密碼）。
     */
    @POST("api/v1/auth/change-password")
    fun changePassword(
        @Header("Authorization") token: String,
        @Body request: ChangePasswordRequest
    ): Call<MessageResponse>

    /**
     * 登出。JWT 為無狀態設計，僅供伺服器端記錄；用戶端仍需自行清除本地 Token。
     */
    @POST("api/v1/auth/logout")
    fun logout(@Header("Authorization") token: String): Call<MessageResponse>
}
