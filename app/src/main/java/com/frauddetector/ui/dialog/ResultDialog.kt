/**
 * ResultDialog.kt — 通用結果對話框
 *
 * 所屬模組：ui/dialog（彈窗模組）
 *
 * 本 DialogFragment 為全 App 共用的結果回饋對話框，
 * 用於顯示操作成功或失敗的結果訊息。
 * 支援兩種狀態：成功（資訊圖示）與失敗（警告圖示），
 * 搭配自訂標題與詳細訊息文字。
 *
 * 使用 [newInstance] 工廠方法建立，傳入 isSuccess、title、message 參數。
 */
package com.frauddetector.ui.dialog

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.TextView
import androidx.fragment.app.DialogFragment
import com.frauddetector.R
import com.google.android.material.button.MaterialButton

class ResultDialog : DialogFragment() {

    companion object {
        fun newInstance(isSuccess: Boolean, title: String, message: String): ResultDialog {
            return ResultDialog().apply {
                arguments = Bundle().apply {
                    putBoolean("isSuccess", isSuccess)
                    putString("title", title)
                    putString("message", message)
                }
            }
        }
    }

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View? {
        return inflater.inflate(R.layout.dialog_result, container, false)
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        val isSuccess = arguments?.getBoolean("isSuccess") ?: true
        val title = arguments?.getString("title") ?: ""
        val message = arguments?.getString("message") ?: ""

        val icon = view.findViewById<ImageView>(R.id.resultIcon)
        if (isSuccess) {
            icon.setImageResource(android.R.drawable.ic_dialog_info)
        } else {
            icon.setImageResource(android.R.drawable.ic_dialog_alert)
        }

        view.findViewById<TextView>(R.id.tvResultTitle).text = title
        view.findViewById<TextView>(R.id.tvResultMsg).text = message

        view.findViewById<MaterialButton>(R.id.btnResultOk).setOnClickListener {
            dismiss()
        }
    }
}
