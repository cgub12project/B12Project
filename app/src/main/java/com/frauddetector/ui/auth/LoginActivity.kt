/**
 * LoginActivity.kt — 使用者登入頁面
 *
 * 所屬模組：ui/auth（認證模組）
 *
 * 本 Activity 提供多種登入方式：
 * 1. Email + 密碼登入（呼叫後端 /api/v1/auth/login API）
 * 2. Google 第三方登入（導向 [GooglePickerActivity]）
 * 3. Facebook 第三方登入（導向 [FacebookPickerActivity]）
 *
 * 登入成功後，JWT Token 會透過 [TokenManager] 儲存至 SharedPreferences，
 * 並導航至 [MainActivity] 主畫面。
 *
 * 另提供「保持登入」開關、「忘記密碼」連結、「立即註冊」連結等輔助功能。
 */
package com.frauddetector.ui.auth

import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.EditText
import android.view.View
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.frauddetector.R
import com.frauddetector.network.ApiClient
import com.frauddetector.network.LoginRequest
import com.frauddetector.network.TokenManager
import com.frauddetector.network.TokenResponse
import com.frauddetector.ui.dialog.ResultDialog
import com.frauddetector.ui.main.MainActivity
import com.google.android.material.button.MaterialButton
import com.google.android.material.switchmaterial.SwitchMaterial
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

/**
 * 登入頁面 Activity。
 *
 * 支援 Email/密碼登入（API 串接）及 Google/Facebook OAuth 入口，
 * 並提供忘記密碼、註冊帳號等導航功能。
 */
class LoginActivity : AppCompatActivity() {

    /**
     * 初始化登入頁面 UI 元件與事件監聽器。
     * 綁定登入按鈕、OAuth 按鈕、忘記密碼/註冊連結的點擊事件。
     */
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_login)

        // 取得 UI 元件參照
        val etEmail = findViewById<EditText>(R.id.etEmail)
        val etPassword = findViewById<EditText>(R.id.etPassword)
        val btnLogin = findViewById<MaterialButton>(R.id.btnLogin)
        val switchKeep = findViewById<SwitchMaterial>(R.id.switchKeepLogin)  // 保持登入開關
        val layoutOAuthHint = findViewById<View>(R.id.layoutOAuthHint)       // OAuth 提示區塊（登入失敗後顯示）
        val tvOAuthHintAction = findViewById<TextView>(R.id.tvOAuthHintAction)

        // OAuth 提示：點擊後導向忘記密碼頁（引導用戶設定密碼）
        tvOAuthHintAction.setOnClickListener {
            startActivity(Intent(this, ForgotPasswordActivity::class.java))
        }

        // ── 登入按鈕 — 呼叫後端 /api/v1/auth/login API ──
        btnLogin.setOnClickListener {
            val email = etEmail.text.toString().trim()
            val password = etPassword.text.toString()

            // 前端驗證：確保 Email 與密碼均已填寫
            if (email.isEmpty() || password.isEmpty()) {
                ResultDialog.newInstance(false, "登入失敗", "請輸入電子信箱與密碼後再試。")
                    .show(supportFragmentManager, "result")
                return@setOnClickListener
            }

            // 禁用按鈕防止重複點擊，並顯示載入狀態
            btnLogin.isEnabled = false
            btnLogin.text = "登入中..."

            // 建立登入請求並透過 Retrofit 非同步呼叫 API
            val request = LoginRequest(email, password, switchKeep.isChecked)
            ApiClient.authApi.login(request).enqueue(object : Callback<TokenResponse> {
                override fun onResponse(call: Call<TokenResponse>, response: Response<TokenResponse>) {
                    // 恢復按鈕狀態
                    btnLogin.isEnabled = true
                    btnLogin.text = getString(R.string.login)

                    if (response.isSuccessful && response.body() != null) {
                        // 登入成功：儲存 JWT Token 與使用者資訊
                        val token = response.body()!!
                        TokenManager(this@LoginActivity).saveTokens(
                            token.accessToken, token.refreshToken
                        )
                        TokenManager(this@LoginActivity).saveUserInfo(email)
                        // 顯示成功對話框，延遲 1.2 秒後跳轉至主畫面
                        ResultDialog.newInstance(true, "登入成功", "歡迎回來！正在載入您的資料...")
                            .show(supportFragmentManager, "login_ok")
                        Handler(Looper.getMainLooper()).postDelayed({
                            startActivity(Intent(this@LoginActivity, MainActivity::class.java))
                            finish()
                        }, 1200)
                    } else {
                        // 登入失敗：解析並顯示錯誤訊息，同時顯示 OAuth 提示
                        val msg = ApiClient.parseError(response.errorBody()?.string())
                        ResultDialog.newInstance(false, "登入失敗", msg)
                            .show(supportFragmentManager, "result")
                        layoutOAuthHint.visibility = View.VISIBLE
                    }
                }

                override fun onFailure(call: Call<TokenResponse>, t: Throwable) {
                    // 網路連線失敗處理
                    btnLogin.isEnabled = true
                    btnLogin.text = getString(R.string.login)
                    ResultDialog.newInstance(
                        false, "連線失敗",
                        "無法連線至伺服器，請檢查網路後再試。\n\n${t.localizedMessage}"
                    ).show(supportFragmentManager, "result")
                }
            })
        }

        // 導航至註冊頁面
        findViewById<TextView>(R.id.tvGoRegister).setOnClickListener {
            startActivity(Intent(this, RegisterActivity::class.java))
        }

        // 導航至忘記密碼頁面
        findViewById<TextView>(R.id.tvForgotPassword).setOnClickListener {
            startActivity(Intent(this, ForgotPasswordActivity::class.java))
        }

        // Google OAuth 登入入口
        findViewById<View>(R.id.btnGoogle).setOnClickListener {
            startActivity(Intent(this, GooglePickerActivity::class.java))
        }

        // Facebook OAuth 登入入口
        findViewById<View>(R.id.btnFacebook).setOnClickListener {
            startActivity(Intent(this, FacebookPickerActivity::class.java))
        }
    }
}
