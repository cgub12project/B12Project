package com.frauddetector.network

import android.content.Context

/**
 * 使用 SharedPreferences 管理 JWT Token。
 * 正式上線後可改為 EncryptedSharedPreferences 或 DataStore。
 */
class TokenManager(context: Context) {

    private val prefs = context.getSharedPreferences("flash_auth", Context.MODE_PRIVATE)

    var accessToken: String?
        get() = prefs.getString("access_token", null)
        set(value) = prefs.edit().putString("access_token", value).apply()

    var refreshToken: String?
        get() = prefs.getString("refresh_token", null)
        set(value) = prefs.edit().putString("refresh_token", value).apply()

    val isLoggedIn: Boolean get() = !accessToken.isNullOrEmpty()

    var userEmail: String?
        get() = prefs.getString("user_email", null)
        set(value) = prefs.edit().putString("user_email", value).apply()

    var userName: String?
        get() = prefs.getString("user_name", null)
        set(value) = prefs.edit().putString("user_name", value).apply()

    fun saveTokens(access: String, refresh: String) {
        prefs.edit()
            .putString("access_token", access)
            .putString("refresh_token", refresh)
            .apply()
    }

    fun saveUserInfo(email: String, name: String? = null) {
        prefs.edit()
            .putString("user_email", email)
            .putString("user_name", name ?: "")
            .apply()
    }

    fun clear() {
        prefs.edit().clear().apply()
    }
}
