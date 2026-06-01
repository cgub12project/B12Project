/**
 * FacebookPickerActivity.kt — Facebook 帳號選擇頁面
 *
 * 所屬模組：ui/auth（認證模組）
 *
 * 本 Activity 模擬 Facebook OAuth 登入的帳號選擇介面。
 * 目前使用預設的模擬帳號資料，展示 Facebook 登入的 UI 流程。
 * 使用者選擇帳號後，模擬認證過程並導航至主畫面。
 *
 * 注意：目前為展示用途，尚未整合 Facebook SDK 的實際 OAuth 認證。
 */
package com.frauddetector.ui.auth

import android.content.Intent
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.ImageButton
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.frauddetector.R
import com.frauddetector.ui.dialog.ResultDialog
import com.frauddetector.ui.main.MainActivity

/**
 * Facebook 帳號選擇 Activity。
 *
 * 顯示可用的 Facebook 帳號列表，使用者點選後模擬認證流程，
 * 成功後導航至 [MainActivity]。
 */
class FacebookPickerActivity : AppCompatActivity() {

    /** Facebook 帳號資料類別，用於 RecyclerView 顯示 */
    private data class FbAccount(val name: String, val email: String, val avatarColor: String)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_facebook_picker)

        findViewById<ImageButton>(R.id.btnFbBack).setOnClickListener { finish() }

        val accounts = listOf(
            FbAccount("王小明", "xiaoming.wang@gmail.com", "#1877F2"),
            FbAccount("李佳穎", "jiayin.li@hotmail.com", "#42B72A")
        )

        val rv = findViewById<RecyclerView>(R.id.rvFbAccounts)
        rv.layoutManager = LinearLayoutManager(this)
        rv.adapter = object : RecyclerView.Adapter<RecyclerView.ViewHolder>() {
            inner class VH(val layout: LinearLayout) : RecyclerView.ViewHolder(layout)

            override fun onCreateViewHolder(parent: android.view.ViewGroup, viewType: Int): RecyclerView.ViewHolder {
                val row = LinearLayout(parent.context).apply {
                    orientation = LinearLayout.HORIZONTAL
                    gravity = android.view.Gravity.CENTER_VERTICAL
                    setPadding(dp(20), dp(14), dp(20), dp(14))
                    isClickable = true; isFocusable = true
                    setBackgroundResource(android.R.drawable.list_selector_background)
                }
                val av = TextView(parent.context).apply {
                    layoutParams = LinearLayout.LayoutParams(dp(48), dp(48))
                    gravity = android.view.Gravity.CENTER
                    textSize = 20f; setTextColor(Color.WHITE)
                }
                row.addView(av)
                val info = LinearLayout(parent.context).apply {
                    orientation = LinearLayout.VERTICAL
                    layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
                    setPadding(dp(14), 0, 0, 0)
                }
                info.addView(TextView(parent.context).apply { textSize = 14f; setTextColor(Color.parseColor("#1C1E21")) })
                info.addView(TextView(parent.context).apply { textSize = 12f; setTextColor(Color.parseColor("#65676B")) })
                row.addView(info)
                return VH(row)
            }

            override fun onBindViewHolder(holder: RecyclerView.ViewHolder, position: Int) {
                val acct = accounts[position]
                val vh = holder as VH
                val av = vh.layout.getChildAt(0) as TextView
                av.text = acct.name.first().toString()
                av.background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(Color.parseColor(acct.avatarColor)) }
                val info = vh.layout.getChildAt(1) as LinearLayout
                (info.getChildAt(0) as TextView).text = acct.name
                (info.getChildAt(1) as TextView).text = acct.email
                vh.layout.setOnClickListener {
                    Toast.makeText(this@FacebookPickerActivity, "AUTHENTICATING...", Toast.LENGTH_SHORT).show()
                    Handler(Looper.getMainLooper()).postDelayed({
                        ResultDialog.newInstance(true, "Facebook 登入成功", "已使用 ${acct.name} 的帳號登入。")
                            .show(supportFragmentManager, "login_ok")
                        Handler(Looper.getMainLooper()).postDelayed({
                            startActivity(Intent(this@FacebookPickerActivity, MainActivity::class.java)
                                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
                        }, 1200)
                    }, 900)
                }
            }

            override fun getItemCount() = accounts.size
        }

        findViewById<LinearLayout>(R.id.btnAddFbAccount).setOnClickListener {
            Toast.makeText(this, "新增 Facebook 帳號功能開發中", Toast.LENGTH_SHORT).show()
        }
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()
}
