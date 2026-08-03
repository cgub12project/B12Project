package com.frauddetector.ui.auth

import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.ImageButton
import android.widget.TextView
import com.frauddetector.ui.BaseActivity
import com.facebook.CallbackManager
import com.facebook.FacebookCallback
import com.facebook.FacebookException
import com.facebook.GraphRequest
import com.facebook.login.LoginManager
import com.facebook.login.LoginResult
import com.frauddetector.R
import com.frauddetector.network.ApiClient
import com.frauddetector.network.OAuthRequest
import com.frauddetector.network.TokenManager
import com.frauddetector.network.TokenResponse
import com.frauddetector.ui.dialog.ResultDialog
import com.frauddetector.ui.main.MainActivity
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class FacebookPickerActivity : BaseActivity() {

    private lateinit var callbackManager: CallbackManager

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_facebook_picker)

        findViewById<ImageButton>(R.id.btnFbBack).setOnClickListener { finish() }

        callbackManager = CallbackManager.Factory.create()

        LoginManager.getInstance().registerCallback(callbackManager,
            object : FacebookCallback<LoginResult> {
                override fun onSuccess(result: LoginResult) {
                    fetchFbUserAndLogin(result)
                }

                override fun onCancel() {
                    showError("已取消", "Facebook 登入已取消。")
                }

                override fun onError(error: FacebookException) {
                    showError("Facebook 錯誤", error.localizedMessage ?: "登入時發生未知錯誤")
                }
            }
        )

        // 自動觸發 Facebook Login
        LoginManager.getInstance().logInWithReadPermissions(
            this, listOf("public_profile", "email")
        )
    }

    @Deprecated("Required for Facebook SDK callback")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        callbackManager.onActivityResult(requestCode, resultCode, data)
    }

    private fun fetchFbUserAndLogin(loginResult: LoginResult) {
        val accessToken = loginResult.accessToken

        val request = GraphRequest.newMeRequest(accessToken) { jsonObject, _ ->
            if (jsonObject == null) {
                showError("資料取得失敗", "無法取得 Facebook 使用者資訊。")
                return@newMeRequest
            }

            val email = jsonObject.optString("email")

            if (email.isNullOrBlank()) {
                showError("缺少 Email", "您的 Facebook 帳號未綁定電子信箱，無法使用此方式登入。")
                LoginManager.getInstance().logOut()
                return@newMeRequest
            }

            sendOAuthToBackend(fbAccessToken = accessToken.token)
        }
        val params = Bundle()
        params.putString("fields", "id,name,email")
        request.parameters = params
        request.executeAsync()
    }

    private fun sendOAuthToBackend(fbAccessToken: String) {
        val oauthRequest = OAuthRequest(provider = "facebook", accessToken = fbAccessToken)

        ApiClient.authApi.oauthLogin(oauthRequest).enqueue(object : Callback<TokenResponse> {
            override fun onResponse(call: Call<TokenResponse>, response: Response<TokenResponse>) {
                if (response.isSuccessful && response.body() != null) {
                    val token = response.body()!!
                    val tm = TokenManager(this@FacebookPickerActivity)
                    tm.saveTokens(token.accessToken, token.refreshToken)
                    token.user?.let { tm.saveUserInfo(it.email, it.name) }

                    val displayLabel = token.user?.name ?: token.user?.email ?: "Facebook"
                    ResultDialog.newInstance(true, "Facebook 登入成功", "已使用 $displayLabel 的帳號登入。")
                        .show(supportFragmentManager, "login_ok")
                    Handler(Looper.getMainLooper()).postDelayed({
                        startActivity(
                            Intent(this@FacebookPickerActivity, MainActivity::class.java)
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
        if (!isFinishing) {
            ResultDialog.newInstance(false, title, message)
                .show(supportFragmentManager, "fb_error")
        }
    }
}
