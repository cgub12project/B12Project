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

class LoginActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_login)

        val etEmail = findViewById<EditText>(R.id.etEmail)
        val etPassword = findViewById<EditText>(R.id.etPassword)
        val btnLogin = findViewById<MaterialButton>(R.id.btnLogin)
        val switchKeep = findViewById<SwitchMaterial>(R.id.switchKeepLogin)
        val layoutOAuthHint = findViewById<View>(R.id.layoutOAuthHint)
        val tvOAuthHintAction = findViewById<TextView>(R.id.tvOAuthHintAction)

        tvOAuthHintAction.setOnClickListener {
            startActivity(Intent(this, ForgotPasswordActivity::class.java))
        }

        // ── Login button — 呼叫後端 API ──
        btnLogin.setOnClickListener {
            val email = etEmail.text.toString().trim()
            val password = etPassword.text.toString()

            if (email.isEmpty() || password.isEmpty()) {
                ResultDialog.newInstance(false, "登入失敗", "請輸入電子信箱與密碼後再試。")
                    .show(supportFragmentManager, "result")
                return@setOnClickListener
            }

            // 禁用按鈕，顯示載入狀態
            btnLogin.isEnabled = false
            btnLogin.text = "登入中..."

            val request = LoginRequest(email, password, switchKeep.isChecked)
            ApiClient.authApi.login(request).enqueue(object : Callback<TokenResponse> {
                override fun onResponse(call: Call<TokenResponse>, response: Response<TokenResponse>) {
                    btnLogin.isEnabled = true
                    btnLogin.text = getString(R.string.login)

                    if (response.isSuccessful && response.body() != null) {
                        val token = response.body()!!
                        TokenManager(this@LoginActivity).saveTokens(
                            token.accessToken, token.refreshToken
                        )
                        TokenManager(this@LoginActivity).saveUserInfo(email)
                        ResultDialog.newInstance(true, "登入成功", "歡迎回來！正在載入您的資料...")
                            .show(supportFragmentManager, "login_ok")
                        Handler(Looper.getMainLooper()).postDelayed({
                            startActivity(Intent(this@LoginActivity, MainActivity::class.java))
                            finish()
                        }, 1200)
                    } else {
                        val msg = ApiClient.parseError(response.errorBody()?.string())
                        ResultDialog.newInstance(false, "登入失敗", msg)
                            .show(supportFragmentManager, "result")
                        layoutOAuthHint.visibility = View.VISIBLE
                    }
                }

                override fun onFailure(call: Call<TokenResponse>, t: Throwable) {
                    btnLogin.isEnabled = true
                    btnLogin.text = getString(R.string.login)
                    ResultDialog.newInstance(
                        false, "連線失敗",
                        "無法連線至伺服器，請檢查網路後再試。\n\n${t.localizedMessage}"
                    ).show(supportFragmentManager, "result")
                }
            })
        }

        // Go to Register
        findViewById<TextView>(R.id.tvGoRegister).setOnClickListener {
            startActivity(Intent(this, RegisterActivity::class.java))
        }

        // Forgot Password
        findViewById<TextView>(R.id.tvForgotPassword).setOnClickListener {
            startActivity(Intent(this, ForgotPasswordActivity::class.java))
        }

        // Google Login
        findViewById<View>(R.id.btnGoogle).setOnClickListener {
            startActivity(Intent(this, GooglePickerActivity::class.java))
        }

        // Facebook Login
        findViewById<View>(R.id.btnFacebook).setOnClickListener {
            startActivity(Intent(this, FacebookPickerActivity::class.java))
        }
    }
}
