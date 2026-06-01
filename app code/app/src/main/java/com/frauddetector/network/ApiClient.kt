package com.frauddetector.network

import com.google.gson.Gson
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

/**
 * Retrofit 單例。
 * 所有 API 介面透過此處取得，方便日後統一加入 Token Interceptor。
 */
object ApiClient {

    val gson: Gson = Gson()

    private val okHttp: OkHttpClient by lazy {
        val logging = HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BODY
        }
        OkHttpClient.Builder()
            .addInterceptor(logging)
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(15, TimeUnit.SECONDS)
            .writeTimeout(15, TimeUnit.SECONDS)
            .build()
    }

    private val retrofit: Retrofit by lazy {
        Retrofit.Builder()
            .baseUrl(ApiConfig.BASE_URL)
            .client(okHttp)
            .addConverterFactory(GsonConverterFactory.create(gson))
            .build()
    }

    val authApi: AuthApi by lazy { retrofit.create(AuthApi::class.java) }
    val reportApi: ReportApi by lazy { retrofit.create(ReportApi::class.java) }

    /**
     * 從 Retrofit errorBody 解析錯誤訊息。
     * FastAPI 回傳 {"detail": "..."} 或 {"detail": [{...}]}
     */
    fun parseError(errorBody: String?): String {
        if (errorBody.isNullOrBlank()) return "未知錯誤"
        return try {
            val err = gson.fromJson(errorBody, ErrorDetail::class.java)
            err.detail ?: "未知錯誤"
        } catch (_: Exception) {
            // detail 是陣列的情況（422 validation error）
            try {
                val map = gson.fromJson(errorBody, Map::class.java)
                val detail = map["detail"]
                if (detail is List<*>) {
                    detail.filterIsInstance<Map<*, *>>()
                        .joinToString("\n") { it["msg"]?.toString() ?: "" }
                        .ifBlank { "請求格式錯誤" }
                } else {
                    detail?.toString() ?: "未知錯誤"
                }
            } catch (_: Exception) {
                "伺服器回傳錯誤"
            }
        }
    }
}
