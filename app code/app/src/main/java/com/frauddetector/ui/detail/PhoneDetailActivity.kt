package com.frauddetector.ui.detail

import android.content.Intent
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.frauddetector.R
import com.frauddetector.adapter.ReportAdapter
import com.frauddetector.data.SampleData
import com.frauddetector.ui.dialog.ReportBottomSheet
import com.frauddetector.ui.dialog.ResultDialog

class PhoneDetailActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_phone_detail)

        val phoneId = intent.getStringExtra("phoneId") ?: "p1"
        val phone = SampleData.getPhoneRecords().find { it.id == phoneId } ?: return

        // Populate data
        findViewById<TextView>(R.id.tvPhoneNumber).text = phone.number

        val tvRisk = findViewById<TextView>(R.id.tvPhoneRisk)
        tvRisk.text = phone.riskLabel
        val riskColor = when (phone.riskLevel) {
            "high" -> Color.parseColor("#FF3B30")
            "mid" -> Color.parseColor("#FF9500")
            else -> Color.parseColor("#34C759")
        }
        tvRisk.setTextColor(Color.WHITE)
        val riskBg = GradientDrawable().apply {
            cornerRadius = 20f * resources.displayMetrics.density
            setColor(riskColor)
        }
        tvRisk.background = riskBg

        findViewById<TextView>(R.id.tvReportCount).text = phone.count
        findViewById<TextView>(R.id.tvLastReport).text = phone.lastReport
        findViewById<TextView>(R.id.tvFraudType).text = phone.type

        // Community reports RecyclerView
        val rv = findViewById<RecyclerView>(R.id.rvCommunityReports)
        rv.layoutManager = LinearLayoutManager(this)
        if (phone.reports.isEmpty()) {
            // Show empty state
            Toast.makeText(this, "NO REPORTS FOUND", Toast.LENGTH_SHORT).show()
        } else {
            rv.adapter = ReportAdapter(phone.reports)
        }

        // Back
        findViewById<LinearLayout>(R.id.btnBackToPhoneList).setOnClickListener { finish() }

        // Dial
        findViewById<LinearLayout>(R.id.btnDial).setOnClickListener {
            Toast.makeText(this, "DIALING: ${phone.number}", Toast.LENGTH_SHORT).show()
        }

        // Block
        findViewById<LinearLayout>(R.id.btnBlock).setOnClickListener {
            ResultDialog.newInstance(
                isSuccess = true,
                title = "封鎖成功",
                message = "號碼已加入封鎖名單。"
            ).show(supportFragmentManager, "result")
        }

        // Report -> BottomSheet
        findViewById<LinearLayout>(R.id.btnReport).setOnClickListener {
            ReportBottomSheet.newInstance(phone.number).show(supportFragmentManager, "report")
        }

        // Share
        findViewById<LinearLayout>(R.id.btnShare).setOnClickListener {
            val intent = Intent(this, ShareWarningActivity::class.java)
            intent.putExtra("phoneNumber", phone.number)
            intent.putExtra("phoneType", phone.type)
            intent.putExtra("phoneCount", phone.count)
            startActivity(intent)
        }
    }
}
