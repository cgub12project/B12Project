package com.frauddetector.ui.main

import android.content.Intent
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.fragment.app.Fragment
import com.frauddetector.R
import com.frauddetector.network.TokenManager
import com.frauddetector.ui.auth.ForgotPasswordActivity
import com.frauddetector.ui.auth.LoginActivity
import com.frauddetector.ui.dialog.QuickSetupDialog

class SettingsFragment : Fragment() {

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View? {
        return inflater.inflate(R.layout.fragment_settings, container, false)
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        setupProfile(view)
        setupSettingsItems(view)
        setupClickListeners(view)
    }

    private fun setupProfile(view: View) {
        val tokenManager = TokenManager(requireContext())
        val email = tokenManager.userEmail
        val name = tokenManager.userName

        val tvName = view.findViewById<TextView>(R.id.tvProfileName)
        val tvEmail = view.findViewById<TextView>(R.id.tvProfileEmail)

        if (!name.isNullOrBlank()) {
            tvName.text = name
            tvEmail.text = email ?: getString(R.string.verified_email)
        } else if (!email.isNullOrBlank()) {
            tvName.text = email
            tvEmail.text = getString(R.string.verified_email)
        } else {
            tvName.text = "未登入"
            tvEmail.text = ""
        }
    }

    private fun setupSettingsItems(view: View) {
        setupItem(view, R.id.settingMsgMonitor, R.drawable.ic_msg_set,
            getString(R.string.msg_monitoring), getString(R.string.msg_monitoring_sub))
        setupItem(view, R.id.settingEmailScan, R.drawable.ic_email_set,
            getString(R.string.email_scan), getString(R.string.email_scan_sub))
        setupItem(view, R.id.settingCallerId, R.drawable.ic_phone_set,
            getString(R.string.caller_id), getString(R.string.caller_id_sub))
        setupItem(view, R.id.settingQuickLogin, R.drawable.ic_lock_set,
            getString(R.string.quick_login), getString(R.string.quick_login_sub))
        setupItem(view, R.id.settingHighRiskAlert, R.drawable.ic_bell_set,
            getString(R.string.high_risk_alert), getString(R.string.high_risk_alert_sub))
        setupItem(view, R.id.settingDailyReport, R.drawable.ic_calendar_set,
            getString(R.string.daily_report), getString(R.string.daily_report_sub))
        setupItem(view, R.id.settingChangePassword, R.drawable.ic_key_set,
            getString(R.string.change_password), getString(R.string.change_password_sub))
        setupItem(view, R.id.settingPrivacy, R.drawable.ic_shield_set,
            getString(R.string.privacy_data), getString(R.string.privacy_data_sub))
        setupItem(view, R.id.settingLogout, R.drawable.ic_logout_set,
            getString(R.string.logout), getString(R.string.logout_sub))
    }

    private fun setupItem(view: View, itemId: Int, iconRes: Int, label: String, sub: String) {
        val item = view.findViewById<View>(itemId)
        item.findViewById<ImageView>(R.id.settingsIcon).setImageResource(iconRes)
        item.findViewById<TextView>(R.id.tvSettingsLabel).text = label
        item.findViewById<TextView>(R.id.tvSettingsSub).text = sub
    }

    private fun setupClickListeners(view: View) {
        view.findViewById<View>(R.id.settingChangePassword).setOnClickListener {
            startActivity(Intent(requireContext(), ForgotPasswordActivity::class.java))
        }

        view.findViewById<View>(R.id.settingPrivacy).setOnClickListener {
            Toast.makeText(requireContext(), getString(R.string.not_implemented), Toast.LENGTH_SHORT).show()
        }

        view.findViewById<View>(R.id.settingLogout).setOnClickListener {
            AlertDialog.Builder(requireContext())
                .setTitle("登出")
                .setMessage("確定要登出嗎？")
                .setPositiveButton("登出") { _, _ ->
                    TokenManager(requireContext()).clear()
                    val intent = Intent(requireContext(), LoginActivity::class.java)
                    intent.flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
                    startActivity(intent)
                }
                .setNegativeButton("取消", null)
                .show()
        }

        view.findViewById<View>(R.id.settingQuickLogin).setOnClickListener {
            QuickSetupDialog().show(parentFragmentManager, "quick_setup")
        }
    }
}
