/**
 * MainActivity.kt — 應用程式主畫面（底部導航容器）
 *
 * 所屬模組：ui/main（主畫面模組）
 *
 * 本 Activity 作為登入成功後的主要容器，透過 Material Design 底部導航列
 * （BottomNavigationView）管理四個主要頁籤的 Fragment 切換：
 * - 訊息（MessagesFragment）— 詐騙訊息警報列表
 * - 郵件（EmailFragment）— 可疑郵件警報列表
 * - 電話（PhoneFragment）— 電話號碼詐騙資料庫
 * - 設定（SettingsFragment）— 個人資料與系統設定
 *
 * 預設載入「訊息」頁籤。
 */
package com.frauddetector.ui.main

import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.fragment.app.Fragment
import com.frauddetector.R
import com.google.android.material.bottomnavigation.BottomNavigationView

/**
 * 主畫面 Activity，負責管理底部導航與 Fragment 切換。
 */
class MainActivity : AppCompatActivity() {

    /**
     * 初始化底部導航列，並設定預設頁籤為訊息頁。
     */
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        val bottomNav = findViewById<BottomNavigationView>(R.id.bottomNav)

        // 首次建立時載入預設頁籤（訊息頁）
        if (savedInstanceState == null) {
            loadFragment(MessagesFragment())
        }

        // 底部導航項目點擊事件：切換對應的 Fragment
        bottomNav.setOnItemSelectedListener { item ->
            when (item.itemId) {
                R.id.nav_messages -> loadFragment(MessagesFragment())
                R.id.nav_email -> loadFragment(EmailFragment())
                R.id.nav_phone -> loadFragment(PhoneFragment())
                R.id.nav_settings -> loadFragment(SettingsFragment())
                else -> false
            }
        }
    }

    /**
     * 載入指定的 Fragment 至容器中，替換目前顯示的 Fragment。
     *
     * @param fragment 要載入的 Fragment 實例
     * @return 固定回傳 true，表示導航項目已被選中
     */
    private fun loadFragment(fragment: Fragment): Boolean {
        supportFragmentManager.beginTransaction()
            .replace(R.id.fragmentContainer, fragment)
            .commit()
        return true
    }
}
