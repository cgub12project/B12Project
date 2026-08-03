/**
 * TokenManager.kt — JWT Token 與使用者資訊管理器
 *
 * 所屬模組：network（網路層）
 *
 * 本類別負責管理使用者的認證狀態，包括：
 * - JWT access_token 與 refresh_token 的儲存與讀取
 * - 使用者基本資訊（Email、名稱）的本地持久化
 * - 登入狀態判斷
 * - 登出時的資料清除
 *
 * 儲存方式採用 Android SharedPreferences，資料以 key-value 形式
 * 存放於 "flash_auth" 命名空間中。正式上線後建議改用
 * EncryptedSharedPreferences 或 Jetpack DataStore 以提升安全性。
 */
package com.frauddetector.network

import android.content.Context

/**
 * JWT Token 管理器。
 *
 * 透過 [SharedPreferences] 持久化儲存認證相關資料，
 * 提供屬性存取器（getter/setter）方便各模組讀寫 Token。
 *
 * @param context Android Context，用於取得 SharedPreferences 實例
 */
class TokenManager(context: Context) {

    /** SharedPreferences 實例，命名空間為 "flash_auth"，僅本 App 可存取 */
    private val prefs = context.getSharedPreferences("flash_auth", Context.MODE_PRIVATE)

    /** JWT 存取令牌（access_token），用於 API 請求的 Bearer 認證標頭 */
    var accessToken: String?
        get() = prefs.getString("access_token", null)
        set(value) = prefs.edit().putString("access_token", value).apply()

    /** JWT 刷新令牌（refresh_token），用於在 access_token 過期後取得新的令牌 */
    var refreshToken: String?
        get() = prefs.getString("refresh_token", null)
        set(value) = prefs.edit().putString("refresh_token", value).apply()

    /** 判斷使用者是否已登入：當 accessToken 存在且非空時視為已登入 */
    val isLoggedIn: Boolean get() = !accessToken.isNullOrEmpty()

    /** 使用者電子信箱，登入成功後儲存，供設定頁面等畫面顯示 */
    var userEmail: String?
        get() = prefs.getString("user_email", null)
        set(value) = prefs.edit().putString("user_email", value).apply()

    /** 使用者顯示名稱，註冊或 OAuth 登入時取得 */
    var userName: String?
        get() = prefs.getString("user_name", null)
        set(value) = prefs.edit().putString("user_name", value).apply()

    /**
     * 快速登入（生物辨識）是否啟用 — 本地快取，與後端 user_settings.quick_login 同步。
     * SplashActivity 用此值判斷是否需要在進入主畫面前跳出生物辨識驗證。
     */
    var quickLoginEnabled: Boolean
        get() = prefs.getBoolean("quick_login_enabled", false)
        set(value) = prefs.edit().putBoolean("quick_login_enabled", value).apply()

    /**
     * 一次性儲存 access_token 與 refresh_token。
     * 登入成功或 Token 刷新後呼叫此方法。
     *
     * @param access JWT 存取令牌
     * @param refresh JWT 刷新令牌
     */
    fun saveTokens(access: String, refresh: String) {
        prefs.edit()
            .putString("access_token", access)
            .putString("refresh_token", refresh)
            .apply()
    }

    /**
     * 儲存使用者基本資訊。
     *
     * @param email 使用者電子信箱
     * @param name 使用者顯示名稱（可選，預設為空字串）
     */
    fun saveUserInfo(email: String, name: String? = null) {
        prefs.edit()
            .putString("user_email", email)
            .putString("user_name", name ?: "")
            .apply()
    }

    /**
     * 清除所有認證資料（登出時呼叫）。
     * 執行後 [isLoggedIn] 將回傳 false。
     */
    fun clear() {
        prefs.edit().clear().apply()
    }
}
