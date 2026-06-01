package com.frauddetector.ui.detail

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.os.Bundle
import android.widget.ImageButton
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.frauddetector.R
import com.frauddetector.ui.dialog.ResultDialog
import com.google.android.material.button.MaterialButton

class ShareWarningActivity : AppCompatActivity() {

    private lateinit var warningText: String

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_share_warning)

        val phoneNumber = intent.getStringExtra("phoneNumber") ?: "+886-800-XXX-XXX"
        val phoneType = intent.getStringExtra("phoneType") ?: "假冒政府機關"
        val phoneCount = intent.getStringExtra("phoneCount") ?: "2,847"

        // Build warning text
        warningText = "【F.L.A.S.H. AI 警告】\n" +
            "號碼 $phoneNumber 已被標記為高危詐騙號碼。\n" +
            "類型：$phoneType\n" +
            "社群回報：$phoneCount 次\n" +
            "——\n" +
            "請勿回撥或依指示操作！\n" +
            "由「F.L.A.S.H. 詐騙感知」自動生成"

        // Update preview text if view exists
        try {
            findViewById<TextView>(R.id.tvSharePreview)?.text = warningText
        } catch (_: Exception) {}

        // Back
        findViewById<ImageButton>(R.id.btnShareBack).setOnClickListener { finish() }

        // Share platforms
        findViewById<LinearLayout>(R.id.btnShareLine).setOnClickListener {
            ResultDialog.newInstance(true, "已開啟 LINE", "正在跳轉至 LINE...")
                .show(supportFragmentManager, "share")
        }
        findViewById<LinearLayout>(R.id.btnShareWhatsApp).setOnClickListener {
            ResultDialog.newInstance(true, "已開啟 WhatsApp", "正在跳轉至 WhatsApp...")
                .show(supportFragmentManager, "share")
        }
        findViewById<LinearLayout>(R.id.btnShareMessenger).setOnClickListener {
            ResultDialog.newInstance(true, "已開啟 Messenger", "正在跳轉至 Messenger...")
                .show(supportFragmentManager, "share")
        }
        findViewById<LinearLayout>(R.id.btnShareSms).setOnClickListener {
            ResultDialog.newInstance(true, "已開啟簡訊", "正在跳轉至簡訊...")
                .show(supportFragmentManager, "share")
        }

        // Copy text
        findViewById<MaterialButton>(R.id.btnCopyText).setOnClickListener {
            val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            clipboard.setPrimaryClip(ClipData.newPlainText("warning", warningText))
            Toast.makeText(this, "COPIED TO CLIPBOARD", Toast.LENGTH_SHORT).show()
        }

        // Save image
        findViewById<MaterialButton>(R.id.btnSaveImage).setOnClickListener {
            Toast.makeText(this, "圖片已儲存至相簿", Toast.LENGTH_SHORT).show()
        }
    }
}
