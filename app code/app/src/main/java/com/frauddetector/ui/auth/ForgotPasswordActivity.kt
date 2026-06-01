package com.frauddetector.ui.auth

import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.Editable
import android.text.TextWatcher
import android.widget.EditText
import android.widget.TextView
import android.widget.ViewFlipper
import androidx.appcompat.app.AppCompatActivity
import com.frauddetector.R
import com.frauddetector.network.ApiClient
import com.frauddetector.network.ForgotPasswordRequest
import com.frauddetector.network.ResetPasswordRequest
import com.frauddetector.network.VerifyOtpRequest
import com.frauddetector.ui.dialog.ResultDialog
import com.google.android.material.button.MaterialButton
import com.google.android.material.textfield.TextInputEditText
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class ForgotPasswordActivity : AppCompatActivity() {

    private lateinit var flipper: ViewFlipper
    private var resetEmail: String = ""
    private var verifiedOtp: String = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_forgot_password)

        flipper = findViewById(R.id.resetFlipper)

        val btnSendOtp = findViewById<MaterialButton>(R.id.btnSendOtp)
        val btnVerifyOtp = findViewById<MaterialButton>(R.id.btnVerifyOtp)
        val btnConfirmReset = findViewById<MaterialButton>(R.id.btnConfirmReset)

        // OTP 欄位列表
        val otpFields = listOf<EditText>(
            findViewById(R.id.otp1), findViewById(R.id.otp2), findViewById(R.id.otp3),
            findViewById(R.id.otp4), findViewById(R.id.otp5), findViewById(R.id.otp6)
        )

        // OTP 自動跳下一格
        otpFields.forEachIndexed { i, et ->
            et.addTextChangedListener(object : TextWatcher {
                override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
                override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
                override fun afterTextChanged(s: Editable?) {
                    if (s?.length == 1 && i < otpFields.size - 1) {
                        otpFields[i + 1].requestFocus()
                    }
                }
            })
        }

        // ── Step 1: Send OTP ──
        btnSendOtp.setOnClickListener {
            val email = try {
                findViewById<TextInputEditText>(R.id.etResetEmail).text.toString().trim()
            } catch (_: Exception) { "" }

            if (email.isEmpty() || !android.util.Patterns.EMAIL_ADDRESS.matcher(email).matches()) {
                ResultDialog.newInstance(false, "格式錯誤", "請輸入有效的電子信箱地址。")
                    .show(supportFragmentManager, "error")
                return@setOnClickListener
            }

            resetEmail = email
            btnSendOtp.isEnabled = false
            btnSendOtp.text = "發送中..."

            ApiClient.authApi.forgotPassword(ForgotPasswordRequest(email))
                .enqueue(object : Callback<Void> {
                    override fun onResponse(call: Call<Void>, response: Response<Void>) {
                        btnSendOtp.isEnabled = true
                        btnSendOtp.text = getString(R.string.send_otp)

                        if (response.isSuccessful || response.code() == 202) {
                            // 更新提示文字，顯示遮蔽後的信箱
                            val masked = maskEmail(email)
                            findViewById<TextView>(R.id.tvOtpResend).text =
                                "已發送至 $masked\n請查看您的電子信箱"
                            flipper.displayedChild = 1
                        } else {
                            val msg = ApiClient.parseError(response.errorBody()?.string())
                            ResultDialog.newInstance(false, "發送失敗", msg)
                                .show(supportFragmentManager, "error")
                        }
                    }

                    override fun onFailure(call: Call<Void>, t: Throwable) {
                        btnSendOtp.isEnabled = true
                        btnSendOtp.text = getString(R.string.send_otp)
                        ResultDialog.newInstance(
                            false, "連線失敗",
                            "無法連線至伺服器，請檢查網路後再試。"
                        ).show(supportFragmentManager, "error")
                    }
                })
        }

        // Step 1: Back to login
        findViewById<MaterialButton>(R.id.btnBackStep1).setOnClickListener { finish() }

        // ── Step 2: Verify OTP ──
        btnVerifyOtp.setOnClickListener {
            val otp = otpFields.joinToString("") { it.text.toString() }
            if (otp.length != 6) {
                ResultDialog.newInstance(false, "驗證碼錯誤", "請輸入完整的 6 位數驗證碼。")
                    .show(supportFragmentManager, "error")
                return@setOnClickListener
            }

            btnVerifyOtp.isEnabled = false
            btnVerifyOtp.text = "驗證中..."

            ApiClient.authApi.verifyOtp(VerifyOtpRequest(resetEmail, otp))
                .enqueue(object : Callback<Void> {
                    override fun onResponse(call: Call<Void>, response: Response<Void>) {
                        btnVerifyOtp.isEnabled = true
                        btnVerifyOtp.text = getString(R.string.verify_otp)

                        if (response.isSuccessful) {
                            verifiedOtp = otp
                            flipper.displayedChild = 2
                        } else {
                            val msg = ApiClient.parseError(response.errorBody()?.string())
                            ResultDialog.newInstance(false, "驗證失敗", msg)
                                .show(supportFragmentManager, "error")
                        }
                    }

                    override fun onFailure(call: Call<Void>, t: Throwable) {
                        btnVerifyOtp.isEnabled = true
                        btnVerifyOtp.text = getString(R.string.verify_otp)
                        ResultDialog.newInstance(
                            false, "連線失敗",
                            "無法連線至伺服器，請檢查網路後再試。"
                        ).show(supportFragmentManager, "error")
                    }
                })
        }

        // Step 2: Back
        findViewById<MaterialButton>(R.id.btnBackStep2).setOnClickListener {
            flipper.displayedChild = 0
        }

        // ── Step 3: Confirm Reset ──
        btnConfirmReset.setOnClickListener {
            val newPw = try {
                findViewById<TextInputEditText>(R.id.etNewPassword).text.toString()
            } catch (_: Exception) { "" }
            val confirmPw = try {
                findViewById<TextInputEditText>(R.id.etConfirmNewPassword).text.toString()
            } catch (_: Exception) { "" }

            if (newPw.length < 8) {
                ResultDialog.newInstance(false, "密碼太短", "密碼至少需要 8 個字元。")
                    .show(supportFragmentManager, "error")
                return@setOnClickListener
            }
            if (newPw != confirmPw) {
                ResultDialog.newInstance(false, "密碼不一致", "兩次輸入的密碼不相符，請重新確認。")
                    .show(supportFragmentManager, "error")
                return@setOnClickListener
            }

            btnConfirmReset.isEnabled = false
            btnConfirmReset.text = "更新中..."

            ApiClient.authApi.resetPassword(ResetPasswordRequest(resetEmail, verifiedOtp, newPw))
                .enqueue(object : Callback<Void> {
                    override fun onResponse(call: Call<Void>, response: Response<Void>) {
                        btnConfirmReset.isEnabled = true
                        btnConfirmReset.text = getString(R.string.confirm_reset)

                        if (response.isSuccessful) {
                            ResultDialog.newInstance(true, "密碼已重設", "您的密碼已成功更新，請使用新密碼登入。")
                                .show(supportFragmentManager, "success")
                            Handler(Looper.getMainLooper()).postDelayed({ finish() }, 1500)
                        } else {
                            val msg = ApiClient.parseError(response.errorBody()?.string())
                            ResultDialog.newInstance(false, "重設失敗", msg)
                                .show(supportFragmentManager, "error")
                        }
                    }

                    override fun onFailure(call: Call<Void>, t: Throwable) {
                        btnConfirmReset.isEnabled = true
                        btnConfirmReset.text = getString(R.string.confirm_reset)
                        ResultDialog.newInstance(
                            false, "連線失敗",
                            "無法連線至伺服器，請檢查網路後再試。"
                        ).show(supportFragmentManager, "error")
                    }
                })
        }

        // Step 3: Back
        findViewById<MaterialButton>(R.id.btnBackStep3).setOnClickListener {
            flipper.displayedChild = 1
        }
    }

    /** 遮蔽電子信箱：john@example.com → j***@example.com */
    private fun maskEmail(email: String): String {
        val at = email.indexOf('@')
        if (at <= 1) return email
        return email[0] + "***" + email.substring(at)
    }
}
