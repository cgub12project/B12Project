package com.frauddetector.ui.auth

import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.Editable
import android.text.TextWatcher
import android.view.View
import android.widget.CheckBox
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.frauddetector.R
import com.frauddetector.network.ApiClient
import com.frauddetector.network.RegisterRequest
import com.frauddetector.network.TokenManager
import com.frauddetector.network.TokenResponse
import com.frauddetector.ui.dialog.ResultDialog
import com.google.android.material.button.MaterialButton
import com.google.android.material.textfield.TextInputEditText
import com.google.android.material.textfield.TextInputLayout
import android.util.Log
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class RegisterActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_register)

        val etDisplayName = findViewById<TextInputEditText>(R.id.etRegDisplayName)
        val etPassword = findViewById<TextInputEditText>(R.id.etRegPassword)
        val strengthBar = findViewById<LinearLayout>(R.id.passwordStrengthBar)
        val seg1 = findViewById<View>(R.id.pwSeg1)
        val seg2 = findViewById<View>(R.id.pwSeg2)
        val seg3 = findViewById<View>(R.id.pwSeg3)
        val tvStrength = findViewById<TextView>(R.id.tvPwStrength)

        // Password strength indicator
        etPassword.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                val pw = s?.toString() ?: ""
                if (pw.isEmpty()) {
                    strengthBar.visibility = View.GONE
                    return
                }
                strengthBar.visibility = View.VISIBLE
                val hasLen = pw.length >= 8
                val hasMix = pw.any { it.isUpperCase() } && pw.any { it.isLowerCase() }
                val hasSpecial = pw.any { !it.isLetterOrDigit() }
                val score = listOf(hasLen, hasMix, hasSpecial).count { it }

                val weakColor = 0xFFb91c3a.toInt()
                val medColor = 0xFFa16207.toInt()
                val strongColor = 0xFF166534.toInt()
                val defaultColor = 0xFFE0E0E0.toInt()

                when (score) {
                    0, 1 -> {
                        seg1.setBackgroundColor(weakColor)
                        seg2.setBackgroundColor(defaultColor)
                        seg3.setBackgroundColor(defaultColor)
                        tvStrength.text = "弱"
                    }
                    2 -> {
                        seg1.setBackgroundColor(medColor)
                        seg2.setBackgroundColor(medColor)
                        seg3.setBackgroundColor(defaultColor)
                        tvStrength.text = "中等"
                    }
                    3 -> {
                        seg1.setBackgroundColor(strongColor)
                        seg2.setBackgroundColor(strongColor)
                        seg3.setBackgroundColor(strongColor)
                        tvStrength.text = "強"
                    }
                }
            }
        })

        // Back to login
        findViewById<TextView>(R.id.tvBackToLogin).setOnClickListener {
            finish()
        }

        // Register button — 呼叫後端 API
        val btnRegister = findViewById<MaterialButton>(R.id.btnRegister)
        btnRegister.setOnClickListener {
            val displayName = etDisplayName.text.toString().trim()
            val email = findViewById<TextInputEditText>(R.id.etRegEmail).text.toString().trim()
            val pw = etPassword.text.toString()
            val confirmPw = findViewById<TextInputEditText>(R.id.etRegConfirmPassword).text.toString()
            val termsChecked = findViewById<CheckBox>(R.id.cbTerms).isChecked

            val tilName = findViewById<TextInputLayout>(R.id.tilRegDisplayName)
            val tilEmail = findViewById<TextInputLayout>(R.id.tilRegEmail)
            val tilPw = findViewById<TextInputLayout>(R.id.tilRegPassword)
            val tilConfirm = findViewById<TextInputLayout>(R.id.tilRegConfirmPassword)

            var valid = true
            tilName.error = null; tilEmail.error = null; tilPw.error = null; tilConfirm.error = null

            if (displayName.isEmpty()) {
                tilName.error = "請輸入顯示名稱"
                valid = false
            }
            if (email.isEmpty() || !android.util.Patterns.EMAIL_ADDRESS.matcher(email).matches()) {
                tilEmail.error = "請輸入有效電子信箱"
                valid = false
            }
            if (pw.length < 8) {
                tilPw.error = "密碼至少 8 個字元"
                valid = false
            }
            if (pw != confirmPw) {
                tilConfirm.error = "兩次密碼不一致"
                valid = false
            }
            if (!termsChecked) {
                Toast.makeText(this, "請同意服務條款與隱私政策", Toast.LENGTH_SHORT).show()
                valid = false
            }
            if (!valid) return@setOnClickListener

            // 禁用按鈕，顯示載入狀態
            btnRegister.isEnabled = false
            btnRegister.text = "註冊中..."

            val request = RegisterRequest(email, pw, displayName)
            Log.d("Register", "Sending register request: email=$email, displayName=$displayName")
            ApiClient.authApi.register(request).enqueue(object : Callback<TokenResponse> {
                override fun onResponse(call: Call<TokenResponse>, response: Response<TokenResponse>) {
                    Log.d("Register", "onResponse: code=${response.code()}, body=${response.body()}")
                    if (isFinishing || isDestroyed) return
                    btnRegister.isEnabled = true
                    btnRegister.text = getString(R.string.register)

                    if (response.isSuccessful) {
                        val token = response.body()
                        if (token != null) {
                            TokenManager(this@RegisterActivity).saveTokens(
                                token.accessToken, token.refreshToken
                            )
                        }
                        ResultDialog.newInstance(
                            true, "註冊成功！", "帳號已建立。\n請使用電子信箱登入。"
                        ).show(supportFragmentManager, "reg_ok")
                        Handler(Looper.getMainLooper()).postDelayed({ finish() }, 1500)
                    } else {
                        val msg = ApiClient.parseError(response.errorBody()?.string())
                        ResultDialog.newInstance(false, "註冊失敗", msg)
                            .show(supportFragmentManager, "result")
                    }
                }

                override fun onFailure(call: Call<TokenResponse>, t: Throwable) {
                    Log.e("Register", "onFailure: ${t.message}", t)
                    if (isFinishing || isDestroyed) return
                    btnRegister.isEnabled = true
                    btnRegister.text = getString(R.string.register)
                    ResultDialog.newInstance(
                        false, "連線失敗",
                        "無法連線至伺服器，請檢查網路後再試。\n\n${t.localizedMessage}"
                    ).show(supportFragmentManager, "result")
                }
            })
        }
    }
}
