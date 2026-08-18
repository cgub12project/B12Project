/**
 * BlockConfirmDialog.kt — 封鎖前的確認對話框
 *
 * 所屬模組：ui/dialog（彈窗模組）
 *
 * 封鎖是「一按就生效、而且使用者不容易自己找到哪裡可以復原」的動作——訊息/郵件的
 * 封鎖清單藏在設定頁裡，電話封鎖後該號碼直接從列表消失，誤觸的人多半只會覺得
 * 資料不見了。所以所有「加入封鎖」的入口統一先跳這一層確認。
 *
 * 反過來，**解除封鎖不走這裡**：解除是把東西放回來的復原動作，本身就是誤觸的解藥，
 * 再加一層確認只是多一次點擊。
 *
 * 用 [forAccount]（訊息／郵件寄件人）或 [forNumber]（電話號碼）建立，兩者只差文案。
 */
package com.frauddetector.ui.dialog

import android.graphics.Color
import android.graphics.drawable.ColorDrawable
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.TextView
import androidx.fragment.app.DialogFragment
import com.frauddetector.R

class BlockConfirmDialog : DialogFragment() {

    /** 按下「封鎖」後要執行的動作。由呼叫端在 show() 前設定。 */
    var onConfirm: (() -> Unit)? = null

    companion object {
        private const val ARG_IS_NUMBER = "isNumber"
        private const val ARG_TARGET = "target"

        /** 訊息／郵件的帳號或寄件人 */
        fun forAccount(target: String = "", onConfirm: () -> Unit) =
            create(isNumber = false, target = target, onConfirm = onConfirm)

        /** 電話號碼 */
        fun forNumber(target: String = "", onConfirm: () -> Unit) =
            create(isNumber = true, target = target, onConfirm = onConfirm)

        private fun create(isNumber: Boolean, target: String, onConfirm: () -> Unit) =
            BlockConfirmDialog().apply {
                arguments = Bundle().apply {
                    putBoolean(ARG_IS_NUMBER, isNumber)
                    putString(ARG_TARGET, target)
                }
                this.onConfirm = onConfirm
            }
    }

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View? {
        return inflater.inflate(R.layout.dialog_block_confirm, container, false)
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        // 轉螢幕等重建後 onConfirm 會是 null（lambda 沒辦法放進 Bundle 帶過去），
        // 這種情況直接關掉，不留一個按了沒反應的封鎖鈕
        if (onConfirm == null && savedInstanceState != null) {
            dismissAllowingStateLoss()
            return
        }

        val isNumber = arguments?.getBoolean(ARG_IS_NUMBER) ?: false
        val target = arguments?.getString(ARG_TARGET).orEmpty()

        view.findViewById<TextView>(R.id.tvBlockConfirmTitle).setText(
            if (isNumber) R.string.block_confirm_number_title else R.string.block_confirm_account_title
        )
        view.findViewById<TextView>(R.id.tvBlockConfirmMsg).setText(
            if (isNumber) R.string.block_confirm_number_msg else R.string.block_confirm_account_msg
        )

        view.findViewById<TextView>(R.id.tvBlockConfirmTarget).apply {
            if (target.isBlank()) {
                visibility = View.GONE
            } else {
                text = target
                visibility = View.VISIBLE
            }
        }

        view.findViewById<TextView>(R.id.btnBlockCancel).setOnClickListener { dismiss() }
        view.findViewById<TextView>(R.id.btnBlockConfirm).setOnClickListener {
            val action = onConfirm
            dismiss()
            action?.invoke()
        }
    }

    override fun onStart() {
        super.onStart()
        // 版面自己畫了米白圓角卡（bg_dialog_cream），系統預設的白色圓角視窗底
        // 會在卡片外圍露出一圈白，所以把視窗底設成透明
        dialog?.window?.apply {
            setBackgroundDrawable(ColorDrawable(Color.TRANSPARENT))
            setLayout(
                (resources.displayMetrics.widthPixels * 0.86f).toInt(),
                WindowManager.LayoutParams.WRAP_CONTENT
            )
        }
    }
}
