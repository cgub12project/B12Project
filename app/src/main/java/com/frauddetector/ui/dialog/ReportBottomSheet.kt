/**
 * ReportBottomSheet.kt — 電話號碼詐騙回報表單（BottomSheet）
 *
 * 所屬模組：ui/dialog（彈窗模組）
 *
 * 本 BottomSheet 提供電話號碼的詐騙回報功能，已與後端 API 串接。
 * 功能包含：
 * - 顯示被回報的電話號碼
 * - 7 種詐騙類型 Chip 單選（假冒政府機關、投資詐騙等）
 * - 選擇「其他」時顯示自填文字欄位
 * - 回報描述文字輸入（至少 10 個字）
 * - 呼叫 POST /api/v1/reports/phone/{phone_number} API 提交回報
 * - 需要 JWT Token 認證（未登入時提示用戶先登入）
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
import com.frauddetector.network.PhoneReportRequest
import com.frauddetector.network.TokenManager
import com.google.android.material.bottomsheet.BottomSheetDialogFragment
import com.google.android.material.button.MaterialButton
import com.google.android.material.chip.Chip
import com.google.android.material.chip.ChipGroup
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

/**
 * 電話號碼回報 BottomSheet，透過 Retrofit 呼叫後端回報 API。
 * 使用 [newInstance] 工廠方法建立並傳入電話號碼參數。
 */
class ReportBottomSheet : BottomSheetDialogFragment() {

    companion object {
        private const val ARG_PHONE = "phone_number"

        fun newInstance(phoneNumber: String): ReportBottomSheet {
            return ReportBottomSheet().apply {
                arguments = Bundle().also { it.putString(ARG_PHONE, phoneNumber) }
            }
        }
    }

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View? {
        return inflater.inflate(R.layout.dialog_report_bottom_sheet, container, false)
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        val phoneNumber = arguments?.getString(ARG_PHONE) ?: ""
        view.findViewById<TextView>(R.id.tvModalNumber).text = phoneNumber

        val chipGroup = view.findViewById<ChipGroup>(R.id.chipGroupModalType)
        val etOtherType = view.findViewById<EditText>(R.id.etOtherType)
        val etContent = view.findViewById<EditText>(R.id.etContent)
        val btnSubmit = view.findViewById<MaterialButton>(R.id.btnModalSubmit)

        // 建立詐騙類型 Chips
        val types = listOf(
            R.string.type_gov, R.string.type_bank, R.string.type_invest,
            R.string.type_romance, R.string.type_phish, R.string.type_harass, R.string.type_other
        )
        for (typeRes in types) {
            val chip = Chip(requireContext()).apply {
                text = getString(typeRes)
                isCheckable = true
            }
            chipGroup.addView(chip)
        }

        // 選擇「其他」時顯示自填欄位
        chipGroup.setOnCheckedStateChangeListener { group, checkedIds ->
            val selectedText = checkedIds.firstOrNull()?.let { group.findViewById<Chip>(it)?.text }
            etOtherType.visibility =
                if (selectedText == getString(R.string.type_other)) View.VISIBLE else View.GONE
        }

        btnSubmit.setOnClickListener {
            val selectedChip = (0 until chipGroup.childCount)
                .map { chipGroup.getChildAt(it) as Chip }
                .firstOrNull { it.isChecked }

            if (selectedChip == null) {
                Toast.makeText(requireContext(), "請選擇詐騙類型", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            val fraudType = if (selectedChip.text == getString(R.string.type_other)) {
                val otherText = etOtherType.text.toString().trim()
                if (otherText.isEmpty()) {
                    Toast.makeText(requireContext(), "請說明詐騙類型", Toast.LENGTH_SHORT).show()
                    return@setOnClickListener
                }
                otherText
            } else {
                selectedChip.text.toString()
            }

            val content = etContent.text.toString().trim()
            if (content.length < 10) {
                Toast.makeText(requireContext(), "描述至少需要 10 個字", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            submitReport(phoneNumber, fraudType, content, btnSubmit)
        }
    }

    /**
     * 提交電話號碼詐騙回報至後端 API。
     * 先檢查登入狀態（JWT Token），再透過 Retrofit 發送 POST 請求。
     * 回報成功或失敗皆以 [ResultDialog] 顯示結果。
     */
    private fun submitReport(
        phoneNumber: String,
        fraudType: String,
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

        ApiClient.reportApi.reportPhone(
            "Bearer $token",
            phoneNumber,
            PhoneReportRequest(fraudType = fraudType, content = content)
        ).enqueue(object : Callback<Void> {
            override fun onResponse(call: Call<Void>, response: Response<Void>) {
                if (!isAdded) return
                dismiss()
                if (response.isSuccessful) {
                    ResultDialog.newInstance(
                        true,
                        getString(R.string.report_success),
                        getString(R.string.report_success_msg)
                    ).show(parentFragmentManager, "result")
                } else {
                    val msg = ApiClient.parseError(response.errorBody()?.string())
                    ResultDialog.newInstance(false, getString(R.string.report_failed), msg)
                        .show(parentFragmentManager, "result")
                }
            }

            override fun onFailure(call: Call<Void>, t: Throwable) {
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
