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
