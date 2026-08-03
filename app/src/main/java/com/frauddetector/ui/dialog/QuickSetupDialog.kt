/**
 * QuickSetupDialog.kt — 快速登入設定引導對話框
 *
 * 所屬模組：ui/dialog（彈窗模組）
 *
 * 引導使用者啟用生物辨識快速登入：檢查裝置是否已設定指紋/臉部辨識，
 * 若可用則開啟本地旗標並同步 PUT /api/v1/users/me/settings 的 quick_login 欄位。
 */
package com.frauddetector.ui.dialog

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Toast
import androidx.biometric.BiometricManager
import androidx.fragment.app.DialogFragment
import com.frauddetector.R
import com.frauddetector.network.ApiClient
import com.frauddetector.network.TokenManager
import com.frauddetector.network.UserSettingsOut
import com.frauddetector.network.UserSettingsUpdateRequest
import com.google.android.material.button.MaterialButton
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

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
            val canAuth = BiometricManager.from(requireContext())
                .canAuthenticate(BiometricManager.Authenticators.BIOMETRIC_WEAK)
            if (canAuth != BiometricManager.BIOMETRIC_SUCCESS) {
                Toast.makeText(
                    requireContext(),
                    "此裝置尚未設定生物辨識，請先至系統設定新增指紋或臉部辨識",
                    Toast.LENGTH_LONG
                ).show()
                dismiss()
                return@setOnClickListener
            }

            TokenManager(requireContext()).quickLoginEnabled = true
            pushQuickLoginSetting()
            Toast.makeText(requireContext(), "快速登入已啟用，下次啟動 App 時將以生物辨識驗證", Toast.LENGTH_SHORT).show()
            dismiss()
        }
    }

    private fun pushQuickLoginSetting() {
        val token = TokenManager(requireContext()).accessToken ?: return
        ApiClient.userApi.updateSettings("Bearer $token", UserSettingsUpdateRequest(quickLogin = true))
            .enqueue(object : Callback<UserSettingsOut> {
                override fun onResponse(call: Call<UserSettingsOut>, response: Response<UserSettingsOut>) {}
                override fun onFailure(call: Call<UserSettingsOut>, t: Throwable) {}
            })
    }
}
