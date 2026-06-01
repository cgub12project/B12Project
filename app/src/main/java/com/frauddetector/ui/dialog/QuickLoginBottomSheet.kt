/**
 * QuickLoginBottomSheet.kt — 生物辨識快速登入介面（BottomSheet）
 *
 * 所屬模組：ui/dialog（彈窗模組）
 *
 * 本 BottomSheet 顯示生物辨識驗證的 UI 介面，
 * 包含驗證動畫與取消按鈕。
 *
 * 注意：BiometricPrompt API 整合尚未完成，
 * 目前僅顯示「尚未實作此功能」提示。
 */
package com.frauddetector.ui.dialog

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Toast
import com.frauddetector.R
import com.google.android.material.bottomsheet.BottomSheetDialogFragment
import com.google.android.material.button.MaterialButton

class QuickLoginBottomSheet : BottomSheetDialogFragment() {

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View? {
        return inflater.inflate(R.layout.dialog_quick_login, container, false)
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        // Cancel
        view.findViewById<MaterialButton>(R.id.btnQuickCancel).setOnClickListener {
            dismiss()
        }

        // TODO: 生物辨識驗證需要 BiometricPrompt API
        Toast.makeText(requireContext(), getString(R.string.not_implemented), Toast.LENGTH_SHORT).show()
    }
}
