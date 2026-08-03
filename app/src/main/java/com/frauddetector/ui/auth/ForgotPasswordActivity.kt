package com.frauddetector.ui.auth

import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.TextView
import android.widget.ViewFlipper
import com.frauddetector.ui.BaseActivity
import com.frauddetector.R
import com.frauddetector.network.ApiClient
import com.frauddetector.network.ForgotPasswordRequest
import com.frauddetector.network.ResetPasswordRequest
import com.frauddetector.network.VerifyOtpRequest
import com.frauddetector.network.VerifyOtpResponse
import com.frauddetector.ui.dialog.ResultDialog
import com.google.android.material.button.MaterialButton
import com.google.android.material.textfield.TextInputEditText
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class ForgotPasswordActivity : BaseActivity() {

    private lateinit var flipper: ViewFlipper
    private var resetEmail: String = ""
    private var resetToken: String = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_forgot_password)

        flipper = findViewById(R.id.resetFlipper)

        val btnSendOtp = findViewById<MaterialButton>(R.id.btnSendOtp)
        val btnVerifyOtp = findViewById<MaterialButton>(R.id.btnVerifyOtp)
        val btnConfirmReset = findViewById<MaterialButton>(R.id.btnConfirmReset)

        // Step 1: Send OTP
        btnSendOtp.setOnClickListener {
            val email = try {
                findViewById<TextInputEditText>(R.id.etResetEmail).text.toString().trim()
            } catch (_: Exception) { "" }

            if (email.isEmpty() || !android.util.Patterns.EMAIL_ADDRESS.matcher(email).matches()) {
                ResultDialog.newInstance(false, "Invalid format", "Please enter a valid email address.")
                    .show(supportFragmentManager, "error")
                return@setOnClickListener
            }

            resetEmail = email
            btnSendOtp.isEnabled = false
            btnSendOtp.text = "Sending..."

            ApiClient.authApi.forgotPassword(ForgotPasswordRequest(email))
                .enqueue(object : Callback<Void> {
                    override fun onResponse(call: Call<Void>, response: Response<Void>) {
                        btnSendOtp.isEnabled = true
                        btnSendOtp.text = "Send verification code"

                        if (response.isSuccessful || response.code() == 202) {
                            val masked = maskEmail(email)
                            val tvResend = findViewById<TextView>(R.id.tvOtpResend)
                            tvResend.text = "Sent to $masked\nPlease check your email"
                            tvResend.visibility = android.view.View.VISIBLE
                            flipper.displayedChild = 1
                        } else {
                            val msg = ApiClient.parseError(response.errorBody()?.string())
                            ResultDialog.newInstance(false, "Failed", msg)
                                .show(supportFragmentManager, "error")
                        }
                    }

                    override fun onFailure(call: Call<Void>, t: Throwable) {
                        btnSendOtp.isEnabled = true
                        btnSendOtp.text = "Send verification code"
                        ResultDialog.newInstance(false, "Connection failed",
                            "Cannot connect to server.").show(supportFragmentManager, "error")
                    }
                })
        }

        findViewById<MaterialButton>(R.id.btnBackStep1).setOnClickListener { finish() }

        // Step 2: Verify OTP (single field)
        btnVerifyOtp.setOnClickListener {
            val otp = try {
                findViewById<TextInputEditText>(R.id.etOtpCode).text.toString().trim()
            } catch (_: Exception) { "" }

            if (otp.length != 6) {
                ResultDialog.newInstance(false, "Invalid code", "Please enter the 6-digit verification code.")
                    .show(supportFragmentManager, "error")
                return@setOnClickListener
            }

            btnVerifyOtp.isEnabled = false
            btnVerifyOtp.text = "Verifying..."

            ApiClient.authApi.verifyOtp(VerifyOtpRequest(resetEmail, otp))
                .enqueue(object : Callback<VerifyOtpResponse> {
                    override fun onResponse(call: Call<VerifyOtpResponse>, response: Response<VerifyOtpResponse>) {
                        btnVerifyOtp.isEnabled = true
                        btnVerifyOtp.text = "Verify"

                        val token = response.body()?.resetToken
                        if (response.isSuccessful && !token.isNullOrEmpty()) {
                            resetToken = token
                            flipper.displayedChild = 2
                        } else {
                            val msg = ApiClient.parseError(response.errorBody()?.string())
                            ResultDialog.newInstance(false, "Verification failed", msg)
                                .show(supportFragmentManager, "error")
                        }
                    }

                    override fun onFailure(call: Call<VerifyOtpResponse>, t: Throwable) {
                        btnVerifyOtp.isEnabled = true
                        btnVerifyOtp.text = "Verify"
                        ResultDialog.newInstance(false, "Connection failed",
                            "Cannot connect to server.").show(supportFragmentManager, "error")
                    }
                })
        }

        findViewById<MaterialButton>(R.id.btnBackStep2).setOnClickListener {
            flipper.displayedChild = 0
        }

        // Step 3: Confirm Reset
        btnConfirmReset.setOnClickListener {
            val newPw = try {
                findViewById<TextInputEditText>(R.id.etNewPassword).text.toString()
            } catch (_: Exception) { "" }
            val confirmPw = try {
                findViewById<TextInputEditText>(R.id.etConfirmNewPassword).text.toString()
            } catch (_: Exception) { "" }

            if (newPw.length < 8) {
                ResultDialog.newInstance(false, "Too short", "Password must be at least 8 characters.")
                    .show(supportFragmentManager, "error")
                return@setOnClickListener
            }
            if (newPw != confirmPw) {
                ResultDialog.newInstance(false, "Mismatch", "Passwords do not match.")
                    .show(supportFragmentManager, "error")
                return@setOnClickListener
            }

            btnConfirmReset.isEnabled = false
            btnConfirmReset.text = "Resetting..."

            ApiClient.authApi.resetPassword(ResetPasswordRequest(resetToken, newPw))
                .enqueue(object : Callback<Void> {
                    override fun onResponse(call: Call<Void>, response: Response<Void>) {
                        btnConfirmReset.isEnabled = true
                        btnConfirmReset.text = "Reset"

                        if (response.isSuccessful) {
                            ResultDialog.newInstance(true, "Password reset", "Your password has been updated. Please sign in.")
                                .show(supportFragmentManager, "success")
                            Handler(Looper.getMainLooper()).postDelayed({ finish() }, 1500)
                        } else {
                            val msg = ApiClient.parseError(response.errorBody()?.string())
                            ResultDialog.newInstance(false, "Reset failed", msg)
                                .show(supportFragmentManager, "error")
                        }
                    }

                    override fun onFailure(call: Call<Void>, t: Throwable) {
                        btnConfirmReset.isEnabled = true
                        btnConfirmReset.text = "Reset"
                        ResultDialog.newInstance(false, "Connection failed",
                            "Cannot connect to server.").show(supportFragmentManager, "error")
                    }
                })
        }

        findViewById<MaterialButton>(R.id.btnBackStep3).setOnClickListener {
            flipper.displayedChild = 1
        }
    }

    private fun maskEmail(email: String): String {
        val at = email.indexOf('@')
        if (at <= 1) return email
        return email[0] + "***" + email.substring(at)
    }
}
