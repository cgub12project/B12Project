package com.frauddetector.ui.auth

import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.widget.ImageButton
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.credentials.CredentialManager
import androidx.credentials.CustomCredential
import androidx.credentials.GetCredentialRequest
import androidx.credentials.GetCredentialResponse
import androidx.credentials.exceptions.GetCredentialException
import androidx.lifecycle.lifecycleScope
import com.frauddetector.R
import com.frauddetector.network.ApiClient
import com.frauddetector.network.OAuthRequest
import com.frauddetector.network.TokenManager
import com.frauddetector.network.TokenResponse
import com.frauddetector.ui.dialog.ResultDialog
import com.frauddetector.ui.main.MainActivity
import com.google.android.libraries.identity.googleid.GetGoogleIdOption
import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential
import com.google.android.libraries.identity.googleid.GoogleIdTokenParsingException
import kotlinx.coroutines.launch
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class GooglePickerActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "GoogleSignIn"
        private const val WEB_CLIENT_ID =
            "572057865880-q1f83qokk8agnpa0olqtqssfu6m8kkdb.apps.googleusercontent.com"
    }

    private lateinit var credentialManager: CredentialManager

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_google_picker)

        findViewById<ImageButton>(R.id.btnGoogleBack).setOnClickListener { finish() }

        credentialManager = CredentialManager.create(this)

        // 直接啟動 Google Sign-In 流程
        startGoogleSignIn()
    }

    private fun startGoogleSignIn() {
        val googleIdOption = GetGoogleIdOption.Builder()
            .setFilterByAuthorizedAccounts(false)
            .setServerClientId(WEB_CLIENT_ID)
            .build()

        val request = GetCredentialRequest.Builder()
            .addCredentialOption(googleIdOption)
            .build()

        lifecycleScope.launch {
            try {
                val result = credentialManager.getCredential(
                    request = request,
                    context = this@GooglePickerActivity
                )
                handleSignInResult(result)
            } catch (e: GetCredentialException) {
                Log.e(TAG, "Google Sign-In failed", e)
                ResultDialog.newInstance(
                    false, "Google 登入失敗",
                    "無法完成 Google 登入。\n\n${e.message ?: "請稍後再試"}"
                ).show(supportFragmentManager, "error")

                // 延遲關閉，讓使用者看到錯誤訊息
                Handler(Looper.getMainLooper()).postDelayed({ finish() }, 2000)
            }
        }
    }

    private fun handleSignInResult(result: GetCredentialResponse) {
        when (val credential = result.credential) {
            is CustomCredential -> {
                if (credential.type == GoogleIdTokenCredential.TYPE_GOOGLE_ID_TOKEN_CREDENTIAL) {
                    try {
                        val googleIdTokenCredential =
                            GoogleIdTokenCredential.createFrom(credential.data)
                        val idToken = googleIdTokenCredential.idToken
                        val googleEmail = googleIdTokenCredential.id
                        val googleName = googleIdTokenCredential.displayName ?: ""

                        TokenManager(this@GooglePickerActivity).saveUserInfo(googleEmail, googleName)
                        Log.d(TAG, "Got ID token, sending to backend...")
                        sendTokenToBackend(idToken)
                    } catch (e: GoogleIdTokenParsingException) {
                        Log.e(TAG, "Invalid Google ID token", e)
                        showError("Google 驗證失敗", "無法解析 Google 憑證，請重試。")
                    }
                } else {
                    showError("登入失敗", "不支援的憑證類型。")
                }
            }
            else -> {
                showError("登入失敗", "不支援的憑證類型。")
            }
        }
    }

    private fun sendTokenToBackend(idToken: String) {
        val request = OAuthRequest(provider = "google", token = idToken)

        ApiClient.authApi.oauthLogin(request).enqueue(object : Callback<TokenResponse> {
            override fun onResponse(call: Call<TokenResponse>, response: Response<TokenResponse>) {
                if (response.isSuccessful && response.body() != null) {
                    val token = response.body()!!
                    TokenManager(this@GooglePickerActivity).saveTokens(
                        token.accessToken, token.refreshToken
                    )
                    ResultDialog.newInstance(true, "Google 登入成功", "歡迎回來！正在載入您的資料...")
                        .show(supportFragmentManager, "login_ok")

                    Handler(Looper.getMainLooper()).postDelayed({
                        startActivity(
                            Intent(this@GooglePickerActivity, MainActivity::class.java)
                                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
                        )
                    }, 1200)
                } else {
                    val msg = ApiClient.parseError(response.errorBody()?.string())
                    showError("登入失敗", msg)
                }
            }

            override fun onFailure(call: Call<TokenResponse>, t: Throwable) {
                showError("連線失敗", "無法連線至伺服器，請檢查網路後再試。\n\n${t.localizedMessage}")
            }
        })
    }

    private fun showError(title: String, message: String) {
        ResultDialog.newInstance(false, title, message)
            .show(supportFragmentManager, "error")
    }
}
