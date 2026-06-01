package com.frauddetector.network

import com.google.gson.annotations.SerializedName

// ── Request ──────────────────────────────────────────

data class LoginRequest(
    val email: String,
    val password: String,
    @SerializedName("remember_me") val rememberMe: Boolean = false
)

data class RegisterRequest(
    val email: String,
    val password: String,
    @SerializedName("display_name") val displayName: String
)

data class ForgotPasswordRequest(
    val email: String
)

data class VerifyOtpRequest(
    val email: String,
    val otp: String
)

data class ResetPasswordRequest(
    val email: String,
    val otp: String,
    @SerializedName("new_password") val newPassword: String
)

data class OAuthRequest(
    val provider: String,
    val token: String
)

// ── Response ─────────────────────────────────────────

data class TokenResponse(
    @SerializedName("access_token") val accessToken: String,
    @SerializedName("refresh_token") val refreshToken: String,
    @SerializedName("token_type") val tokenType: String
)

/**
 * FastAPI 預設的錯誤格式。
 * detail 可能是 String 或 Array，這裡只處理 String 的情況。
 */
data class ErrorDetail(
    val detail: String?
)
