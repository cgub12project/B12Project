/**
 * SplashActivity.kt — App 啟動畫面（Splash Screen）
 *
 * 所屬模組：ui/auth（認證模組）
 *
 * 顯示品牌 Logo 與載入進度條動畫後，依登入狀態決定去向：
 * - 未登入 → [LoginActivity]
 * - 已登入 + 快速登入(生物辨識)已啟用 + 裝置支援 → 顯示 [com.frauddetector.ui.dialog.QuickLoginBottomSheet]，
 *   驗證成功才進入 [com.frauddetector.ui.main.MainActivity]，失敗/取消則回登入頁
 * - 已登入但未啟用快速登入 → 直接進入 [com.frauddetector.ui.main.MainActivity]
 */
package com.frauddetector.ui.auth

import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.ProgressBar
import com.frauddetector.ui.BaseActivity
import androidx.biometric.BiometricManager
import com.frauddetector.R
import com.frauddetector.network.TokenManager
import com.frauddetector.ui.dialog.QuickLoginBottomSheet
import com.frauddetector.ui.main.MainActivity

class SplashActivity : BaseActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_splash)

        val progressBar = findViewById<ProgressBar>(R.id.splashProgress)
        progressBar.max = 100

        val handler = Handler(Looper.getMainLooper())
        var progress = 0
        val runnable = object : Runnable {
            override fun run() {
                progress += 5
                progressBar.progress = progress
                if (progress < 100) {
                    handler.postDelayed(this, 50)
                } else {
                    proceed()
                }
            }
        }
        handler.postDelayed(runnable, 500)
    }

    private fun proceed() {
        val tokenManager = TokenManager(this)
        if (!tokenManager.isLoggedIn) {
            goToLogin()
            return
        }

        val biometricAvailable = BiometricManager.from(this)
            .canAuthenticate(BiometricManager.Authenticators.BIOMETRIC_WEAK) == BiometricManager.BIOMETRIC_SUCCESS

        if (tokenManager.quickLoginEnabled && biometricAvailable) {
            val sheet = QuickLoginBottomSheet().apply {
                isCancelable = false
                onResult = { success -> if (success) goToMain() else goToLogin() }
            }
            sheet.show(supportFragmentManager, "quick_login")
        } else {
            goToMain()
        }
    }

    private fun goToMain() {
        startActivity(Intent(this, MainActivity::class.java))
        finish()
    }

    private fun goToLogin() {
        startActivity(Intent(this, LoginActivity::class.java))
        finish()
    }
}
