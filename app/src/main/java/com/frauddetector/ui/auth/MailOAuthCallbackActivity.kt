/**
 * MailOAuthCallbackActivity.kt — Gmail/Outlook 信箱連接完成後的深層連結接收頁
 *
 * 所屬模組：ui/auth（認證模組）
 *
 * 流程：手機開瀏覽器/Custom Tab 導到後端提供的授權網址 → 使用者在 Google/Microsoft
 * 官方畫面同意授權 → 後端收到 callback、換好 token 之後，把瀏覽器導回這個深層連結
 * （`flashapp://mail-callback?status=success&provider=gmail`），系統會直接開啟這個
 * Activity，把使用者帶回 App 裡，不用手動切回來。
 *
 * 這裡只負責顯示連接結果、導回主畫面，實際的 token 交換與儲存都在後端完成，
 * 手機端完全不會經手 refresh token。
 */
package com.frauddetector.ui.auth

import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import com.frauddetector.ui.BaseActivity
import com.frauddetector.ui.main.MainActivity

class MailOAuthCallbackActivity : BaseActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val data = intent?.data
        val status = data?.getQueryParameter("status")
        val provider = data?.getQueryParameter("provider")
        val providerLabel = when (provider) {
            "gmail" -> "Gmail"
            "outlook" -> "Outlook"
            else -> "信箱"
        }

        val message = if (status == "success") {
            "已成功連接 $providerLabel"
        } else {
            "連接 $providerLabel 失敗，請重試"
        }
        Toast.makeText(this, message, Toast.LENGTH_LONG).show()

        startActivity(
            Intent(this, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
        )
        finish()
    }
}
