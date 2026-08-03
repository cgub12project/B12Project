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
    /** 使用者的顯示名稱；對應後端欄位 name */
    @SerializedName("name") val displayName: String
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
 * 使用 [VerifyOtpResponse.resetToken]（一次性權杖）設定新密碼，不再需要 email/otp。
 */
data class ResetPasswordRequest(
    /** verify-otp 取得的一次性重設權杖；對應後端欄位 reset_token */
    @SerializedName("reset_token") val resetToken: String,
    /** 使用者設定的新密碼；對應後端欄位 new_password */
    @SerializedName("new_password") val newPassword: String
)

/**
 * OAuth 登入請求 — 對應 POST /api/v1/auth/oauth 的請求 body。
 *
 * 後端會以 idToken（Google）或 accessToken（Facebook）向第三方驗證並取得使用者資料，
 * 客戶端不再需要自行提供 email / name / provider_user_id。
 */
data class OAuthRequest(
    /** 第三方身份提供者名稱："google" 或 "facebook" */
    val provider: String,
    /** Google ID Token（provider = "google" 時使用） */
    @SerializedName("id_token") val idToken: String? = null,
    /** Facebook Access Token（provider = "facebook" 時使用） */
    @SerializedName("access_token") val accessToken: String? = null
)

/**
 * 換發權杖請求 — 對應 POST /api/v1/auth/refresh 的請求 body。
 */
data class RefreshTokenRequest(
    @SerializedName("refresh_token") val refreshToken: String
)

/**
 * 更改密碼請求 — 對應 POST /api/v1/auth/change-password 的請求 body（需登入）。
 */
data class ChangePasswordRequest(
    @SerializedName("old_password") val oldPassword: String,
    @SerializedName("new_password") val newPassword: String
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
    @SerializedName("token_type") val tokenType: String,
    /** access_token 的有效秒數；對應後端欄位 expires_in */
    @SerializedName("expires_in") val expiresIn: Int = 0,
    /** 登入成功的使用者資料（後端權威來源，取代客戶端自行拼湊的 email/name） */
    val user: UserOut? = null
)

/**
 * 使用者資料 — 對應後端 UserOut，登入/註冊/OAuth 成功回應中的 user 欄位，
 * 也是 GET /api/v1/users/me 的回應格式。
 */
data class UserOut(
    val id: Int,
    val email: String,
    val name: String,
    @SerializedName("avatar_url") val avatarUrl: String? = null,
    @SerializedName("email_verified") val emailVerified: Boolean = false,
    @SerializedName("created_at") val createdAt: String? = null
)

/**
 * OTP 驗證回應 — 對應 POST /api/v1/auth/verify-otp 的回應 body。
 *
 * 驗證成功後回傳一次性 [resetToken]，用於下一步 [ResetPasswordRequest]。
 */
data class VerifyOtpResponse(
    val success: Boolean = true,
    val message: String? = null,
    /** 一次性重設密碼權杖；對應後端欄位 reset_token */
    @SerializedName("reset_token") val resetToken: String
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

/**
 * 通用訊息回應 — forgot-password / reset-password / change-password / logout 共用。
 */
data class MessageResponse(
    val success: Boolean = true,
    val message: String? = null
)
