/**
 * PhoneFragment.kt — 電話查詢頁籤
 *
 * 所屬模組：ui/main（主畫面模組）
 *
 * 本 Fragment 為底部導航「電話」頁籤，提供電話號碼詐騙資料庫查詢功能。
 * 功能包含：
 * - 以 RecyclerView 列表顯示電話號碼記錄（號碼、風險等級、詐騙類型、舉報次數）
 * - 即時搜尋過濾（輸入號碼即時篩選列表）
 * - 點擊號碼導航至 [PhoneDetailActivity] 查看詳情
 *
 * 資料來源為 [SampleData]，待後端就緒後可替換為 API 呼叫。
 */
package com.frauddetector.ui.main

import android.content.Intent
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.ImageButton
import android.widget.Toast
import androidx.fragment.app.Fragment
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.frauddetector.R
import com.frauddetector.adapter.PhoneAdapter
import com.frauddetector.data.SampleData
import com.frauddetector.ui.detail.PhoneDetailActivity

/**
 * 電話查詢 Fragment，顯示電話號碼詐騙資料庫並支援即時搜尋。
 */
class PhoneFragment : Fragment() {

    private lateinit var adapter: PhoneAdapter

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View? {
        return inflater.inflate(R.layout.fragment_phone, container, false)
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        val items = SampleData.getPhoneRecords()

        // RecyclerView
        val rv = view.findViewById<RecyclerView>(R.id.rvPhones)
        adapter = PhoneAdapter(items) { phone ->
            val intent = Intent(requireContext(), PhoneDetailActivity::class.java)
            intent.putExtra("phoneId", phone.id)
            startActivity(intent)
        }
        rv.layoutManager = LinearLayoutManager(requireContext())
        rv.adapter = adapter

        // Search
        view.findViewById<EditText>(R.id.etPhoneSearch).addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {
                adapter.filter(s?.toString() ?: "")
            }
            override fun afterTextChanged(s: Editable?) {}
        })

        // Info button
        view.findViewById<ImageButton>(R.id.btnPhoneInfo).setOnClickListener {
            Toast.makeText(requireContext(), "社群舉報資料庫包含 ${items.size} 筆號碼", Toast.LENGTH_SHORT).show()
        }
    }
}
