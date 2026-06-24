/**
 * AuthModels.kt — 認證相關的請求與回應資料模型
 *
 * 所屬模組：network（網路層）
 *
 * 本檔案定義了所有與使用者認證（Authentication）API 交互時
 * 使用的請求（Request）與回應（Response）資料模型。
 * 這些模型會透過 Gson 進行 JSON 序列化/反序列化，
 * 並搭配 [SerializedName] 註解對應後端 FastAPI 的 snake_case 命名。
 *
 * 包含：
 * - 請求模型：[LoginRequest]、[RegisterRequest]、[ForgotPasswordRequest]、
 *   [VerifyOtpRequest]、[ResetPasswordRequest]、[OAuthRequest]
 * - 回應模型：[TokenResponse]、[ErrorDetail]
 */
package com.frauddetector.network

import com.google.gson.annotations.SerializedName

// ══════════════════════════════════════════════════════════
// Request（請求模型）
// ══════════════════════════════════════════════════════════

/**
 * 登入請求 — 對應 POST /api/v1/auth/login 的請求 body。
 */
data class LoginRequest(
    /** 使用者的電子郵件地址 */
    val email: String,
    /** 使用者的密碼 */
    val password: String,
    /** 是否記住登入狀態，預設為 false；對應後端欄位 remember_me */
    @SerializedName("remember_me") val rememberMe: Boolean = false
)

/**
 * 註冊請求 — 對應 POST /api/v1/auth/register 的請求 body。
 */
data class RegisterRequest(
    /** 新使用者的電子郵件地址 */
    val email: String,
    /** 新使用者的密碼 */
    val password: String,
    /** 使用者的顯示名稱；對應後端欄位 display_name */
    @SerializedName("display_name") val displayName: String
)

/**
 * 忘記密碼請求 — 對應 POST /api/v1/auth/forgot-password 的請求 body。
 *
 * 後端收到此請求後會發送 OTP 驗證碼至指定的 email。
 */
data class ForgotPasswordRequest(
    /** 需要重設密碼的電子郵件地址 */
    val email: String
)

/**
 * OTP 驗證請求 — 對應 POST /api/v1/auth/verify-otp 的請求 body。
 *
 * 用於驗證使用者輸入的 OTP 驗證碼是否正確。
 */
data class VerifyOtpRequest(
    /** 使用者的電子郵件地址 */
    val email: String,
    /** 使用者輸入的 OTP 驗證碼（通常為 6 位數字） */
    val otp: String
)

/**
 * 重設密碼請求 — 對應 POST /api/v1/auth/reset-password 的請求 body。
 *
 * 在 OTP 驗證通過後，使用者可透過此請求設定新密碼。
 */
data class ResetPasswordRequest(
    /** 使用者的電子郵件地址 */
    val email: String,
    /** 已通過驗證的 OTP 驗證碼 */
    val otp: String,
    /** 使用者設定的新密碼；對應後端欄位 new_password */
    @SerializedName("new_password") val newPassword: String
)

/**
 * OAuth 登入請求 — 對應 POST /api/v1/auth/oauth 的請求 body。
 *
 * 用於第三方身份提供者（Google、Facebook 等）的登入流程。
 */
data class OAuthRequest(
    /** 第三方身份提供者名稱："google" 或 "facebook" */
    val provider: String,
    /** 第三方平台的使用者唯一 ID */
    @SerializedName("provider_user_id") val providerUserId: String,
    /** 使用者的 email */
    val email: String,
    /** 使用者的顯示名稱（選填） */
    @SerializedName("display_name") val displayName: String? = null,
    /** 使用者的大頭照 URL（選填） */
    @SerializedName("avatar_url") val avatarUrl: String? = null,
    /** 第三方平台的 Access Token / ID Token（選填，供後端驗證） */
    @SerializedName("access_token") val accessToken: String? = null
)

// ══════════════════════════════════════════════════════════
// Response（回應模型）
// ══════════════════════════════════════════════════════════

/**
 * Token 回應 — 登入或註冊成功後，後端回傳的 JWT Token 資料。
 *
 * 包含用於身份驗證的 access_token 與用於刷新的 refresh_token。
 * 使用者後續的 API 請求需在 Authorization header 中帶入 access_token。
 */
data class TokenResponse(
    /** JWT 存取權杖，用於後續 API 請求的身份驗證；對應後端欄位 access_token */
    @SerializedName("access_token") val accessToken: String,
    /** JWT 刷新權杖，用於在 access_token 過期後取得新的 Token；對應後端欄位 refresh_token */
    @SerializedName("refresh_token") val refreshToken: String,
    /** Token 類型，通常為 "bearer"；對應後端欄位 token_type */
    @SerializedName("token_type") val tokenType: String
)

/**
 * 錯誤詳情 — FastAPI 預設的錯誤回應格式。
 *
 * FastAPI 在發生錯誤時會回傳 `{"detail": "..."}` 格式的 JSON。
 * 注意：detail 欄位可能是 String 或 Array（HTTP 422 驗證錯誤時為陣列），
 * 此模型只處理 String 的情況；陣列情況由 [ApiClient.parseError] 另行處理。
 */
data class ErrorDetail(
    /** 錯誤訊息文字；若為驗證錯誤（422）則此欄位可能為 null */
    val detail: String?
)
