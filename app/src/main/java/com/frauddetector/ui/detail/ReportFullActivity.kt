/**
 * ReportFullActivity.kt — 完整詐騙回報表單頁面
 *
 * 所屬模組：ui/detail（詳情模組）
 *
 * 本 Activity 提供完整的詐騙回報表單，功能包含：
 * - 詐騙類型選擇（7 種 Chip：假冒政府機關、投資詐騙、交友詐騙等）
 * - 事件資訊填寫（日期、時間、涉及金額）
 * - 事件經過描述（必填文字欄位）
 * - 附加證據上傳（截圖/錄音，功能開發中）
 * - 匿名回報選項
 * - 提交後產生唯一案件編號（FG-XXXXXX 格式）
 */
package com.frauddetector.ui.detail

import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.EditText
import android.widget.ImageButton
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.frauddetector.R
import com.frauddetector.ui.dialog.ResultDialog
import com.google.android.material.button.MaterialButton
import com.google.android.material.chip.Chip
import com.google.android.material.chip.ChipGroup

class ReportFullActivity : AppCompatActivity() {

    private var selectedType: String = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_report_full)

        // Back
        findViewById<ImageButton>(R.id.btnReportBack).setOnClickListener { finish() }

        // Fraud type chips
        val chipGroup = findViewById<ChipGroup>(R.id.chipGroupFraudType)
        val types = listOf("假冒政府機關", "假冒銀行客服", "投資詐騙", "交友詐騙", "釣魚詐騙", "騷擾電話", "其他")
        chipGroup.removeAllViews()
        types.forEach { type ->
            val chip = Chip(this).apply {
                text = type
                isCheckable = true
                isCheckedIconVisible = false
            }
            chip.setOnCheckedChangeListener { _, isChecked ->
                if (isChecked) {
                    selectedType = type
                    // Uncheck others
                    for (i in 0 until chipGroup.childCount) {
                        val c = chipGroup.getChildAt(i) as? Chip
                        if (c != null && c != chip) c.isChecked = false
                    }
                }
            }
            chipGroup.addView(chip)
        }

        // Add Evidence
        findViewById<MaterialButton>(R.id.btnAddEvidence).setOnClickListener {
            Toast.makeText(this, "截圖附件功能需要系統權限", Toast.LENGTH_SHORT).show()
        }

        // Submit Report
        findViewById<MaterialButton>(R.id.btnSubmitReport).setOnClickListener {
            val desc = try {
                findViewById<EditText>(R.id.etEventDetail)?.text?.toString()?.trim() ?: ""
            } catch (_: Exception) { "" }

            if (desc.isEmpty()) {
                ResultDialog.newInstance(false, "回報失敗", "請填寫事件經過描述後再送出。")
                    .show(supportFragmentManager, "result")
                return@setOnClickListener
            }

            Toast.makeText(this, "SUBMITTING REPORT...", Toast.LENGTH_SHORT).show()
            Handler(Looper.getMainLooper()).postDelayed({
                val caseId = "FG-${System.currentTimeMillis().toString().takeLast(6)}"
                ResultDialog.newInstance(true, "回報成功", "案件編號 $caseId\n感謝您的回報！")
                    .show(supportFragmentManager, "result")
            }, 800)
        }
    }
}
