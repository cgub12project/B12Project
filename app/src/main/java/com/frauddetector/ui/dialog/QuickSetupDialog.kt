/**
 * QuickSetupDialog.kt — 快速登入設定引導對話框
 *
 * 所屬模組：ui/dialog（彈窗模組）
 *
 * 本 DialogFragment 在使用者首次開啟「快速登入」設定時顯示，
 * 引導使用者啟用生物辨識（指紋/臉部辨識）快速登入功能。
 * 提供「立即開啟」與「稍後再說」兩個選項。
 *
 * 注意：BiometricPrompt API 整合尚未完成，目前僅顯示提示。
 */
package com.frauddetector.ui.dialog

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Toast
import androidx.fragment.app.DialogFragment
import com.frauddetector.R
import com.google.android.material.button.MaterialButton

class QuickSetupDialog : DialogFragment() {

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View? {
        return inflater.inflate(R.layout.dialog_quick_setup, container, false)
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        // Later
        view.findViewById<MaterialButton>(R.id.btnSetupLater).setOnClickListener {
            dismiss()
        }

        // Enable now
        view.findViewById<MaterialButton>(R.id.btnSetupNow).setOnClickListener {
            // TODO: 開啟快速登入，儲存偏好設定到 SharedPreferences / 資料庫
            Toast.makeText(requireContext(), getString(R.string.not_implemented), Toast.LENGTH_SHORT).show()
            dismiss()
        }
    }
}
