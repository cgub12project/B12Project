package com.frauddetector.ui.main

import android.os.Bundle
import androidx.appcompat.app.AlertDialog
import com.frauddetector.ui.BaseActivity
import androidx.fragment.app.Fragment
import com.frauddetector.R
import com.frauddetector.service.FontScaleManager
import com.frauddetector.service.PermissionHelper
import com.google.android.material.bottomnavigation.BottomNavigationView

class MainActivity : BaseActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        val bottomNav = findViewById<BottomNavigationView>(R.id.bottomNav)

        // 導覽列 icon 預設固定 24dp，不會跟著文字大小設定縮放（FontScaleManager 只透過
        // Configuration.fontScale 動 sp 文字），這裡另外依同一個倍率手動調整 icon 尺寸，
        // 避免字體調到「特大」時文字變大但 icon 沒變、視覺比例失衡。
        // 2026-09-02 拿掉分頁文字後，icon 基準從 24dp 放大到 26dp——導覽列高度沒變，
        // 原本被文字佔掉的空間空出來，維持 24dp 會顯得整排 icon 浮在中間偏小
        val iconScale = FontScaleManager.getScale(this)
        val baseIconSizePx = (26 * resources.displayMetrics.density).toInt()
        bottomNav.itemIconSize = (baseIconSizePx * iconScale).toInt()

        if (savedInstanceState == null) {
            loadFragment(MessagesFragment())
        }

        bottomNav.setOnItemSelectedListener { item ->
            when (item.itemId) {
                R.id.nav_messages -> loadFragment(MessagesFragment())
                R.id.nav_email -> loadFragment(EmailFragment())
                R.id.nav_phone -> loadFragment(PhoneFragment())
                R.id.nav_settings -> loadFragment(SettingsFragment())
                else -> false
            }
        }

        // 首次進入時檢查通知存取權
        checkNotificationAccess()
    }

    private fun loadFragment(fragment: Fragment): Boolean {
        supportFragmentManager.beginTransaction()
            .replace(R.id.fragmentContainer, fragment)
            .commit()
        return true
    }

    private fun checkNotificationAccess() {
        if (!PermissionHelper.isNotificationListenerEnabled(this)) {
            AlertDialog.Builder(this)
                .setTitle("啟用通知監控")
                .setMessage("F.L.A.S.H. 需要「通知存取權」才能即時擷取 LINE、簡訊、WhatsApp、Gmail 等通知，進行詐騙偵測分析。\n\n請在接下來的設定頁面中找到「F.L.A.S.H. 詐騙感知」並開啟。")
                .setPositiveButton("前往設定") { _, _ ->
                    PermissionHelper.openNotificationListenerSettings(this)
                }
                .setNegativeButton("稍後再說", null)
                .setCancelable(false)
                .show()
        }
    }
}
