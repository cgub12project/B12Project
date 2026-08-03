/**
 * MessageReportBottomSheet.kt — 帳號/訊息詐騙回報表單（BottomSheet）
 *
 * 所屬模組：ui/dialog（彈窗模組）
 *
 * 本 BottomSheet 提供可疑社群帳號的詐騙回報功能，已與後端 API 串接。
 * 功能包含：
 * - 7 種詐騙類型 Chip 單選
 * - 5 種社群平台 Chip 單選（LINE/Facebook/Instagram/WhatsApp/Telegram）
 * - 帳號名稱（必填）與帳號 ID（選填）輸入
 * - 回報描述文字輸入（選填）
 * - 支援預填帳號資訊（從 AccountDetailActivity 傳入）
 * - 呼叫 POST /api/v1/reports/account API 提交回報
 * - 需要 JWT Token 認證
 */
package com.frauddetector.ui.dialog

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import com.frauddetector.R
import com.frauddetector.network.ApiClient
import com.frauddetector.network.MessageReportBody
import com.frauddetector.network.ReportSubmitResponse
import com.frauddetector.network.TokenManager
import com.google.android.material.bottomsheet.BottomSheetDialogFragment
import com.google.android.material.button.MaterialButton
import com.google.android.material.chip.Chip
import com.google.android.material.chip.ChipGroup
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

/**
 * 帳號回報 BottomSheet，透過 Retrofit 呼叫後端回報 API。
 * 使用 [newInstance] 工廠方法建立並傳入帳號名稱、平台與 ID 參數。
 */
class MessageReportBottomSheet : BottomSheetDialogFragment() {

    companion object {
        private const val ARG_ACCOUNT_NAME = "account_name"
        private const val ARG_PLATFORM = "platform"
        private const val ARG_ACCOUNT_ID = "account_id"

        fun newInstance(
            accountName: String,
            platform: String = "",
            accountId: String = ""
        ): MessageReportBottomSheet {
            return MessageReportBottomSheet().apply {
                arguments = Bundle().also {
                    it.putString(ARG_ACCOUNT_NAME, accountName)
                    it.putString(ARG_PLATFORM, platform)
                    it.putString(ARG_ACCOUNT_ID, accountId)
                }
            }
        }
    }

    private val platforms = listOf("LINE", "Facebook", "Instagram", "WhatsApp", "Telegram")

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View? {
        return inflater.inflate(R.layout.dialog_message_report_bottom_sheet, container, false)
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        val preFilledName = arguments?.getString(ARG_ACCOUNT_NAME) ?: ""
        val preFilledPlatform = arguments?.getString(ARG_PLATFORM) ?: ""
        val preFilledId = arguments?.getString(ARG_ACCOUNT_ID) ?: ""

        // 顯示帳號資訊
        view.findViewById<TextView>(R.id.tvMsgModalAccount).text = preFilledName

        val chipGroupType = view.findViewById<ChipGroup>(R.id.chipGroupMsgType)
        val etOtherType = view.findViewById<EditText>(R.id.etMsgOtherType)
        val chipGroupPlatform = view.findViewById<ChipGroup>(R.id.chipGroupPlatform)
        val etAccountName = view.findViewById<EditText>(R.id.etAccountName)
        val etAccountId = view.findViewById<EditText>(R.id.etAccountId)
        val etContent = view.findViewById<EditText>(R.id.etMsgContent)
        val btnSubmit = view.findViewById<MaterialButton>(R.id.btnMsgSubmit)

        // 預填帳號欄位
        etAccountName.setText(preFilledName)
        if (preFilledId.isNotEmpty()) etAccountId.setText(preFilledId)

        // 建立詐騙類型 Chips
        val fraudTypes = listOf(
            R.string.type_gov, R.string.type_bank, R.string.type_invest,
            R.string.type_romance, R.string.type_phish, R.string.type_harass, R.string.type_other
        )
        for (typeRes in fraudTypes) {
            val chip = Chip(requireContext()).apply {
                text = getString(typeRes)
                isCheckable = true
            }
            chipGroupType.addView(chip)
        }

        // 選擇「其他」時顯示自填欄位
        chipGroupType.setOnCheckedStateChangeListener { group, checkedIds ->
            val selectedText = checkedIds.firstOrNull()?.let { group.findViewById<Chip>(it)?.text }
            etOtherType.visibility =
                if (selectedText == getString(R.string.type_other)) View.VISIBLE else View.GONE
        }

        // 建立平台 Chips（預選平台）
        for (platform in platforms) {
            val chip = Chip(requireContext()).apply {
                text = platform
                isCheckable = true
                isChecked = (platform.equals(preFilledPlatform, ignoreCase = true))
            }
            chipGroupPlatform.addView(chip)
        }

        btnSubmit.setOnClickListener {
            // 驗證詐騙類型
            val selectedTypeChip = (0 until chipGroupType.childCount)
                .map { chipGroupType.getChildAt(it) as Chip }
                .firstOrNull { it.isChecked }

            if (selectedTypeChip == null) {
                Toast.makeText(requireContext(), "請選擇詐騙類型", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            val fraudType = if (selectedTypeChip.text == getString(R.string.type_other)) {
                val otherText = etOtherType.text.toString().trim()
                if (otherText.isEmpty()) {
                    Toast.makeText(requireContext(), "請說明詐騙類型", Toast.LENGTH_SHORT).show()
                    return@setOnClickListener
                }
                otherText
            } else {
                selectedTypeChip.text.toString()
            }

            // 驗證平台
            val selectedPlatformChip = (0 until chipGroupPlatform.childCount)
                .map { chipGroupPlatform.getChildAt(it) as Chip }
                .firstOrNull { it.isChecked }

            if (selectedPlatformChip == null) {
                Toast.makeText(requireContext(), "請選擇社群平台", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            val platform = selectedPlatformChip.text.toString()

            // 驗證帳號名稱
            val accountName = etAccountName.text.toString().trim()
            if (accountName.isEmpty()) {
                Toast.makeText(requireContext(), "請填寫帳號名稱", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            // 描述為選填欄位，不限制字數
            val content = etContent.text.toString().trim()

            val accountId = etAccountId.text.toString().trim().ifEmpty { null }

            submitReport(fraudType, platform, accountName, accountId, content, btnSubmit)
        }
    }

    /**
     * 提交帳號詐騙回報至後端 API。
     * 先檢查登入狀態（JWT Token），再透過 Retrofit 發送 POST 請求。
     */
    private fun submitReport(
        fraudType: String,
        platform: String,
        accountName: String,
        accountId: String?,
        content: String,
        btnSubmit: MaterialButton
    ) {
        val tokenManager = TokenManager(requireContext())
        val token = tokenManager.accessToken

        if (token.isNullOrEmpty()) {
            dismiss()
            ResultDialog.newInstance(
                false,
                getString(R.string.report_login_required),
                getString(R.string.report_login_required_msg)
            ).show(parentFragmentManager, "result")
            return
        }

        btnSubmit.isEnabled = false
        btnSubmit.text = getString(R.string.submitting)

        ApiClient.reportApi.reportAccount(
            "Bearer $token",
            MessageReportBody(
                fraudType = fraudType,
                content = content,
                platform = platform,
                accountName = accountName,
                accountId = accountId
            )
        ).enqueue(object : Callback<ReportSubmitResponse> {
            override fun onResponse(call: Call<ReportSubmitResponse>, response: Response<ReportSubmitResponse>) {
                if (!isAdded) return
                dismiss()
                if (response.isSuccessful) {
                    val caseNumber = response.body()?.caseNumber
                    val msg = getString(R.string.report_success_msg) +
                        (caseNumber?.let { "\n案件編號：$it" } ?: "")
                    ResultDialog.newInstance(true, getString(R.string.report_success), msg)
                        .show(parentFragmentManager, "result")
                } else {
                    val msg = ApiClient.parseError(response.errorBody()?.string())
                    ResultDialog.newInstance(false, getString(R.string.report_failed), msg)
                        .show(parentFragmentManager, "result")
                }
            }

            override fun onFailure(call: Call<ReportSubmitResponse>, t: Throwable) {
                if (!isAdded) return
                dismiss()
                ResultDialog.newInstance(
                    false,
                    getString(R.string.report_network_error),
                    getString(R.string.report_network_error_msg)
                ).show(parentFragmentManager, "result")
            }
        })
    }
}
