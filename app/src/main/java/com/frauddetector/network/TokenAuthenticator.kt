/**
 * TokenAuthenticator.kt — Access Token 過期自動刷新
 *
 * 所屬模組：network（網路層）
 *
 * 當任一 API 回傳 401 時，OkHttp 會呼叫 [authenticate]。
 * 這裡以 refresh_token 換發新的 access_token，成功後用新 Token 重試原請求；
 * 失敗（refresh_token 也過期/無效）則清除本地 Token，讓使用者回到登入頁重新登入。
 *
 * 注意：內部換發權杖使用獨立的 [OkHttpClient]（不掛載本 Authenticator），
 * 避免 refresh 端點本身失敗時觸發遞迴刷新。
 */
package com.frauddetector.network

import android.content.Context
import android.util.Log
import okhttp3.Authenticator
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.Route
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.concurrent.TimeUnit

class TokenAuthenticator(private val context: Context) : Authenticator {

    private val plainClient by lazy {
        OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(10, TimeUnit.SECONDS)
            .build()
    }

    override fun authenticate(route: Route?, response: Response): Request? {
        // refresh 端點本身失敗時不要再嘗試刷新，避免無窮遞迴
        if (response.request.url.encodedPath.endsWith("/auth/refresh")) return null
        if (responseCount(response) >= 2) return null

        val tokenManager = TokenManager(context)
        val refreshToken = tokenManager.refreshToken
        if (refreshToken.isNullOrEmpty()) return null

        return try {
            val json = ApiClient.gson.toJson(RefreshTokenRequest(refreshToken))
            val req = Request.Builder()
                .url(ApiConfig.BASE_URL + "api/v1/auth/refresh")
                .post(json.toRequestBody("application/json".toMediaType()))
                .build()

            plainClient.newCall(req).execute().use { refreshResponse ->
                if (!refreshResponse.isSuccessful) {
                    if (refreshResponse.code == 401) tokenManager.clear()
                    return null
                }
                val body = refreshResponse.body?.string() ?: return null
                val newTokens = ApiClient.gson.fromJson(body, TokenResponse::class.java)
                tokenManager.saveTokens(newTokens.accessToken, newTokens.refreshToken)

                response.request.newBuilder()
                    .header("Authorization", "Bearer ${newTokens.accessToken}")
                    .build()
            }
        } catch (e: Exception) {
            Log.e("TokenAuthenticator", "Token refresh failed", e)
            null
        }
    }

    private fun responseCount(response: Response): Int {
        var count = 1
        var prior = response.priorResponse
        while (prior != null) {
            count++
            prior = prior.priorResponse
        }
        return count
    }
}
