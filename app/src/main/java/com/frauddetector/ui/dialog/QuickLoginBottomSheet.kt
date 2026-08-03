/**
 * QuickLoginBottomSheet.kt — 生物辨識快速登入介面（BottomSheet）
 *
 * 所屬模組：ui/dialog（彈窗模組）
 *
 * 顯示 BiometricPrompt 進行指紋／臉部辨識驗證。
 * 呼叫端（[com.frauddetector.ui.auth.SplashActivity]）需在 show() 前設定 [onResult]，
 * 驗證成功／失敗／取消皆會回呼一次並自動關閉此 BottomSheet。
 */
package com.frauddetector.ui.dialog

import android.content.DialogInterface
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import com.frauddetector.R
import com.google.android.material.bottomsheet.BottomSheetDialogFragment
import com.google.android.material.button.MaterialButton

class QuickLoginBottomSheet : BottomSheetDialogFragment() {

    /** 驗證結果回呼：true = 成功，false = 失敗／取消 */
    var onResult: ((Boolean) -> Unit)? = null

    private var resultDelivered = false
    private var biometricPrompt: BiometricPrompt? = null

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View? {
        return inflater.inflate(R.layout.dialog_quick_login, container, false)
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        view.findViewById<MaterialButton>(R.id.btnQuickCancel).setOnClickListener {
            biometricPrompt?.cancelAuthentication()
            deliver(false)
            dismiss()
        }

        showBiometricPrompt(view)
    }

    private fun showBiometricPrompt(view: View) {
        val executor = ContextCompat.getMainExecutor(requireContext())
        val callback = object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                view.findViewById<TextView>(R.id.tvQuickStatus)?.text = "驗證成功"
                deliver(true)
                dismiss()
            }

            override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                // 使用者按了系統對話框的取消，或多次失敗鎖定
                deliver(false)
                dismiss()
            }

            override fun onAuthenticationFailed() {
                // 單次指紋/臉部不符，允許重試，不關閉
            }
        }

        val prompt = BiometricPrompt(this, executor, callback)
        biometricPrompt = prompt

        val promptInfo = BiometricPrompt.PromptInfo.Builder()
            .setTitle("快速登入")
            .setSubtitle("使用生物辨識驗證身份以繼續")
            .setAllowedAuthenticators(androidx.biometric.BiometricManager.Authenticators.BIOMETRIC_WEAK)
            .setNegativeButtonText("使用密碼登入")
            .build()

        prompt.authenticate(promptInfo)
    }

    override fun onCancel(dialog: DialogInterface) {
        super.onCancel(dialog)
        deliver(false)
    }

    private fun deliver(success: Boolean) {
        if (resultDelivered) return
        resultDelivered = true
        onResult?.invoke(success)
    }
}
