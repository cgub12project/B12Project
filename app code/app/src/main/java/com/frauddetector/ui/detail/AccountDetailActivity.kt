package com.frauddetector.ui.detail

import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.frauddetector.R
import com.frauddetector.adapter.EvidenceAdapter
import com.frauddetector.data.SampleData
import com.frauddetector.ui.dialog.MessageReportBottomSheet
import com.frauddetector.ui.dialog.ResultDialog
import com.google.android.material.button.MaterialButton
import com.google.android.material.chip.Chip
import com.google.android.material.chip.ChipGroup

class AccountDetailActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_account_detail)

        val threadId = intent.getStringExtra("threadId") ?: "invest"
        val profile = SampleData.getAccountProfiles()[threadId] ?: return

        // Populate header
        findViewById<TextView>(R.id.tvDetName).text = profile.name
        findViewById<TextView>(R.id.tvDetId).text = profile.identifier
        findViewById<TextView>(R.id.tvRingVal).text = profile.riskScore.toString()
        findViewById<TextView>(R.id.tvDetMsgs).text = "${profile.suspectMsgs} 則"
        findViewById<TextView>(R.id.tvDetDays).text = "${profile.days} 天"

        // Progress ring
        val ring = findViewById<ProgressBar>(R.id.riskRing)
        ring.progress = profile.riskScore

        // Triggered rules
        val chipGroup = findViewById<ChipGroup>(R.id.chipGroupRules)
        chipGroup.removeAllViews()
        profile.rules.forEach { rule ->
            val chip = Chip(this).apply {
                text = rule
                textSize = 10f
                isClickable = false
                setTextColor(Color.parseColor("#FF3B30"))
                chipBackgroundColor = android.content.res.ColorStateList.valueOf(
                    Color.parseColor("#1AFF3B30")
                )
                chipStrokeWidth = 0f
            }
            chipGroup.addView(chip)
        }

        // Evidence RecyclerView
        val rv = findViewById<RecyclerView>(R.id.rvEvidence)
        rv.layoutManager = LinearLayoutManager(this)
        rv.adapter = EvidenceAdapter(profile.evidences)

        // Back
        findViewById<LinearLayout>(R.id.btnBackToThread).setOnClickListener { finish() }

        // Block & Report
        findViewById<MaterialButton>(R.id.btnBlockReport).setOnClickListener {
            val (platform, accountId) = parseIdentifier(profile.identifier)
            MessageReportBottomSheet.newInstance(
                accountName = profile.name,
                platform = platform,
                accountId = accountId
            ).show(supportFragmentManager, "report")
        }

        // Share Warning
        findViewById<MaterialButton>(R.id.btnShareWarning).setOnClickListener {
            startActivity(Intent(this, ShareWarningActivity::class.java))
        }
    }

    /** 解析 "LINE: @account_id" 格式，回傳 Pair(platform, accountId) */
    private fun parseIdentifier(identifier: String): Pair<String, String> {
        val idx = identifier.indexOf(": ")
        return if (idx >= 0) {
            Pair(identifier.substring(0, idx).trim(), identifier.substring(idx + 2).trim())
        } else {
            Pair("", identifier)
        }
    }
}
