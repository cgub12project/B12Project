package com.frauddetector.ui.main

import android.os.Bundle
import androidx.appcompat.app.AlertDialog
import com.frauddetector.ui.BaseActivity
import androidx.fragment.app.Fragment
import com.frauddetector.R
import com.frauddetector.service.PermissionHelper
import com.google.android.material.bottomnavigation.BottomNavigationView

class MainActivity : BaseActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        val bottomNav = findViewById<BottomNavigationView>(R.id.bottomNav)

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
