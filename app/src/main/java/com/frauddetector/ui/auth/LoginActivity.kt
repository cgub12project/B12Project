package com.frauddetector.ui.auth

import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.EditText
import android.view.View
import android.widget.TextView
import com.frauddetector.ui.BaseActivity
import com.frauddetector.R
import com.frauddetector.network.ApiClient
import com.frauddetector.network.LoginRequest
import com.frauddetector.network.TokenManager
import com.frauddetector.network.TokenResponse
import com.frauddetector.ui.dialog.ResultDialog
import com.frauddetector.ui.main.MainActivity
import com.google.android.material.button.MaterialButton
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class LoginActivity : BaseActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_login)

        val etEmail = findViewById<EditText>(R.id.etEmail)
        val etPassword = findViewById<EditText>(R.id.etPassword)
        val btnLogin = findViewById<MaterialButton>(R.id.btnLogin)

        // Login button
        btnLogin.setOnClickListener {
            val email = etEmail.text.toString().trim()
            val password = etPassword.text.toString()

            if (email.isEmpty() || password.isEmpty()) {
                ResultDialog.newInstance(false, "Login failed", "Please enter email and password.")
                    .show(supportFragmentManager, "result")
                return@setOnClickListener
            }

            btnLogin.isEnabled = false
            btnLogin.text = "Signing in..."

            val request = LoginRequest(email, password, false)
            ApiClient.authApi.login(request).enqueue(object : Callback<TokenResponse> {
                override fun onResponse(call: Call<TokenResponse>, response: Response<TokenResponse>) {
                    btnLogin.isEnabled = true
                    btnLogin.text = "Sign in"

                    if (response.isSuccessful && response.body() != null) {
                        val token = response.body()!!
                        val tm = TokenManager(this@LoginActivity)
                        tm.saveTokens(token.accessToken, token.refreshToken)
                        tm.saveUserInfo(token.user?.email ?: email, token.user?.name)
                        ResultDialog.newInstance(true, "Welcome back", "Loading your data...")
                            .show(supportFragmentManager, "login_ok")
                        Handler(Looper.getMainLooper()).postDelayed({
                            startActivity(Intent(this@LoginActivity, MainActivity::class.java))
                            finish()
                        }, 1200)
                    } else {
                        val msg = ApiClient.parseError(response.errorBody()?.string())
                        ResultDialog.newInstance(false, "Login failed", msg)
                            .show(supportFragmentManager, "result")
                    }
                }

                override fun onFailure(call: Call<TokenResponse>, t: Throwable) {
                    btnLogin.isEnabled = true
                    btnLogin.text = "Sign in"
                    ResultDialog.newInstance(
                        false, "Connection failed",
                        "Cannot connect to server.\n\n${t.localizedMessage}"
                    ).show(supportFragmentManager, "result")
                }
            })
        }

        // Skip login (testing)
        findViewById<View>(R.id.btnSkipLogin).setOnClickListener {
            TokenManager(this).clear()
            startActivity(Intent(this, MainActivity::class.java))
            finish()
        }

        // Register
        findViewById<TextView>(R.id.tvGoRegister).setOnClickListener {
            startActivity(Intent(this, RegisterActivity::class.java))
        }

        // Forgot password
        findViewById<TextView>(R.id.tvForgotPassword).setOnClickListener {
            startActivity(Intent(this, ForgotPasswordActivity::class.java))
        }

        // Google OAuth
        findViewById<View>(R.id.btnGoogle).setOnClickListener {
            startActivity(Intent(this, GooglePickerActivity::class.java))
        }

        // Facebook OAuth
        findViewById<View>(R.id.btnFacebook).setOnClickListener {
            startActivity(Intent(this, FacebookPickerActivity::class.java))
        }
    }
}
