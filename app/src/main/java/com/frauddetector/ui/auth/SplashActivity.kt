/**
 * SplashActivity.kt — App 啟動畫面（Splash Screen）
 *
 * 所屬模組：ui/auth（認證模組）
 *
 * 本 Activity 為 App 的入口點（在 AndroidManifest.xml 中設定為 LAUNCHER），
 * 負責顯示品牌 Logo 與載入進度條動畫，模擬系統初始化過程。
 * 進度條從 0% 遞增至 100% 後，自動導航至 [LoginActivity] 登入頁面。
 */
package com.frauddetector.ui.auth

import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.ProgressBar
import androidx.appcompat.app.AppCompatActivity
import com.frauddetector.R

/**
 * 啟動畫面 Activity。
 *
 * 顯示品牌動畫與進度條，完成後自動跳轉至登入頁面。
 * 進度每 50 毫秒遞增 5%，總計約 1 秒完成動畫。
 */
class SplashActivity : AppCompatActivity() {

    /**
     * Activity 建立時初始化畫面並啟動進度條動畫。
     * 動畫完成（進度達 100%）後導航至 [LoginActivity]。
     */
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_splash)

        // 取得進度條元件並設定最大值為 100
        val progressBar = findViewById<ProgressBar>(R.id.splashProgress)
        progressBar.max = 100

        // 模擬載入進度：每 50ms 遞增 5%，達 100% 後跳轉至登入頁
        val handler = Handler(Looper.getMainLooper())
        var progress = 0
        val runnable = object : Runnable {
            override fun run() {
                progress += 5
                progressBar.progress = progress
                if (progress < 100) {
                    // 尚未完成，繼續遞增
                    handler.postDelayed(this, 50)
                } else {
                    // 進度完成，導航至登入頁並結束 Splash
                    startActivity(Intent(this@SplashActivity, LoginActivity::class.java))
                    finish()
                }
            }
        }
        // 延遲 500ms 後開始動畫（讓使用者先看到品牌畫面）
        handler.postDelayed(runnable, 500)
    }
}
