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
