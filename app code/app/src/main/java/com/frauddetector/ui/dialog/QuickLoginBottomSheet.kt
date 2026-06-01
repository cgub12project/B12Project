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
