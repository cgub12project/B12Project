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
