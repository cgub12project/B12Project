/**
 * EmailFragment.kt — 郵件警報頁籤
 *
 * 所屬模組：ui/main（主畫面模組）
 *
 * 本 Fragment 為底部導航「郵件」頁籤，顯示可疑郵件警報列表。
 * 功能包含：
 * - 以 RecyclerView 列表展示可疑郵件（寄件人、主旨、預覽、風險等級）
 * - 依郵件供應商篩選（全部/Gmail/Outlook）
 * - 搜尋按鈕（功能開發中）
 *
 * 資料來源為 [SampleData]，待後端就緒後可替換為 API 呼叫。
 */
package com.frauddetector.ui.main

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageButton
import android.widget.Toast
import androidx.fragment.app.Fragment
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.frauddetector.R
import com.frauddetector.adapter.EmailAdapter
import com.frauddetector.data.SampleData
import com.google.android.material.chip.ChipGroup

/**
 * 郵件警報 Fragment，顯示可疑郵件列表並提供供應商篩選功能。
 */
class EmailFragment : Fragment() {

    private lateinit var adapter: EmailAdapter

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View? {
        return inflater.inflate(R.layout.fragment_email, container, false)
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        val items = SampleData.getEmailAlerts()

        // RecyclerView
        val rv = view.findViewById<RecyclerView>(R.id.rvEmails)
        adapter = EmailAdapter(items) { email ->
            // TODO: 正式實作後導航到郵件詳情
            Toast.makeText(requireContext(), "郵件：${email.subject}", Toast.LENGTH_SHORT).show()
        }
        rv.layoutManager = LinearLayoutManager(requireContext())
        rv.adapter = adapter

        // Search button
        view.findViewById<ImageButton>(R.id.btnEmailSearch).setOnClickListener {
            Toast.makeText(requireContext(), "搜尋功能開發中", Toast.LENGTH_SHORT).show()
        }

        // Provider filter chips
        view.findViewById<ChipGroup>(R.id.chipGroupProvider).setOnCheckedStateChangeListener { _, checkedIds ->
            val provider = when {
                checkedIds.isEmpty() -> "全部"
                checkedIds.first() == R.id.chipProviderAll -> "全部"
                checkedIds.first() == R.id.chipGmail -> "Gmail"
                checkedIds.first() == R.id.chipOutlook -> "Outlook"
                else -> "全部"
            }
            adapter.filterByProvider(provider)
        }
    }
}
