package com.frauddetector.network

import retrofit2.Call
import retrofit2.http.Body
import retrofit2.http.POST

interface AuthApi {

    @POST("api/v1/auth/login")
    fun login(@Body request: LoginRequest): Call<TokenResponse>

    @POST("api/v1/auth/register")
    fun register(@Body request: RegisterRequest): Call<TokenResponse>

    @POST("api/v1/auth/forgot-password")
    fun forgotPassword(@Body request: ForgotPasswordRequest): Call<Void>

    @POST("api/v1/auth/verify-otp")
    fun verifyOtp(@Body request: VerifyOtpRequest): Call<Void>

    @POST("api/v1/auth/reset-password")
    fun resetPassword(@Body request: ResetPasswordRequest): Call<Void>

    @POST("api/v1/auth/oauth")
    fun oauthLogin(@Body request: OAuthRequest): Call<TokenResponse>
}
