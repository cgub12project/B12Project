/**
 * ShareWarningActivity.kt — 分享警告頁面
 *
 * 所屬模組：ui/detail（詳情模組）
 *
 * 本 Activity 提供詐騙警告的分享功能，功能包含：
 * - 自動生成警告文字（包含號碼、詐騙類型、舉報次數等資訊）
 * - 多平台一鍵分享：LINE、WhatsApp、Messenger（Intent.ACTION_SEND 指定套件）、簡訊（ACTION_SENDTO）
 * - 複製到剪貼簿
 * - 儲存警告卡片截圖至相簿（MediaStore）
 */
package com.frauddetector.ui.detail

import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.ClipboardManager
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.MediaStore
import android.view.View
import android.widget.ImageButton
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import com.frauddetector.ui.BaseActivity
import androidx.core.content.ContextCompat
import com.frauddetector.R
import com.google.android.material.button.MaterialButton

class ShareWarningActivity : BaseActivity() {

    private lateinit var warningText: String

    private val requestStoragePermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) saveWarningImage() else Toast.makeText(this, "未授予儲存權限，無法儲存圖片", Toast.LENGTH_SHORT).show()
    }

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

        // Share platforms — Intent.ACTION_SEND 指定套件，未安裝時提示使用者
        findViewById<LinearLayout>(R.id.btnShareLine).setOnClickListener {
            shareToApp("jp.naver.line.android", "LINE")
        }
        findViewById<LinearLayout>(R.id.btnShareWhatsApp).setOnClickListener {
            shareToApp("com.whatsapp", "WhatsApp")
        }
        findViewById<LinearLayout>(R.id.btnShareMessenger).setOnClickListener {
            shareToApp("com.facebook.orca", "Messenger")
        }
        findViewById<LinearLayout>(R.id.btnShareSms).setOnClickListener {
            shareViaSms()
        }

        // Copy text
        findViewById<MaterialButton>(R.id.btnCopyText).setOnClickListener {
            val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            clipboard.setPrimaryClip(ClipData.newPlainText("warning", warningText))
            Toast.makeText(this, "COPIED TO CLIPBOARD", Toast.LENGTH_SHORT).show()
        }

        // Save image
        findViewById<MaterialButton>(R.id.btnSaveImage).setOnClickListener {
            if (needsStoragePermission()) {
                requestStoragePermission.launch(android.Manifest.permission.WRITE_EXTERNAL_STORAGE)
            } else {
                saveWarningImage()
            }
        }
    }

    /** 指定套件分享；若裝置未安裝該 App 則提示，而非直接崩潰 */
    private fun shareToApp(packageName: String, appLabel: String) {
        val intent = Intent(Intent.ACTION_SEND).apply {
            type = "text/plain"
            putExtra(Intent.EXTRA_TEXT, warningText)
            setPackage(packageName)
        }
        try {
            startActivity(intent)
        } catch (e: ActivityNotFoundException) {
            Toast.makeText(this, "裝置未安裝 $appLabel，改用「複製文字」分享", Toast.LENGTH_SHORT).show()
        }
    }

    private fun shareViaSms() {
        val intent = Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:")).apply {
            putExtra("sms_body", warningText)
        }
        try {
            startActivity(intent)
        } catch (e: ActivityNotFoundException) {
            Toast.makeText(this, "找不到簡訊 App", Toast.LENGTH_SHORT).show()
        }
    }

    /** API 28 以下需要 WRITE_EXTERNAL_STORAGE 執行時權限；API 29+ 走 Scoped Storage 不需要 */
    private fun needsStoragePermission(): Boolean {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) return false
        return ContextCompat.checkSelfPermission(this, android.Manifest.permission.WRITE_EXTERNAL_STORAGE) !=
            PackageManager.PERMISSION_GRANTED
    }

    /** 將警告預覽卡片截圖並儲存至相簿（MediaStore） */
    private fun saveWarningImage() {
        val box = findViewById<LinearLayout>(R.id.sharePreviewBox)
        if (box.width <= 0 || box.height <= 0) {
            Toast.makeText(this, "畫面尚未準備好，請稍後再試", Toast.LENGTH_SHORT).show()
            return
        }

        val bitmap = Bitmap.createBitmap(box.width, box.height, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bitmap)
        (box.background ?: android.graphics.drawable.ColorDrawable(Color.WHITE)).apply {
            setBounds(0, 0, box.width, box.height)
            draw(canvas)
        }
        box.draw(canvas)

        val saved = try {
            val filename = "FLASH_Warning_${System.currentTimeMillis()}.png"
            val contentValues = ContentValues().apply {
                put(MediaStore.Images.Media.DISPLAY_NAME, filename)
                put(MediaStore.Images.Media.MIME_TYPE, "image/png")
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    put(MediaStore.Images.Media.RELATIVE_PATH, "Pictures/FLASH")
                }
            }
            val uri = contentResolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, contentValues)
            if (uri != null) {
                contentResolver.openOutputStream(uri)?.use { out ->
                    bitmap.compress(Bitmap.CompressFormat.PNG, 100, out)
                }
                true
            } else {
                false
            }
        } catch (e: Exception) {
            false
        }

        Toast.makeText(
            this,
            if (saved) "圖片已儲存至相簿" else "儲存失敗，請稍後再試",
            Toast.LENGTH_SHORT
        ).show()
    }
}
