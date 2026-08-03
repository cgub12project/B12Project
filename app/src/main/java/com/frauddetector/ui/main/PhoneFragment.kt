package com.frauddetector.ui.main

import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.Editable
import android.text.TextWatcher
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.ImageButton
import android.widget.TextView
import android.widget.Toast
import androidx.fragment.app.Fragment
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.frauddetector.R
import com.frauddetector.adapter.PhoneAdapter
import com.frauddetector.data.PhoneRecord
import com.frauddetector.db.AppDatabase
import com.frauddetector.db.CachedPhone
import com.frauddetector.network.ApiClient
import com.frauddetector.network.PhoneListResponse
import com.frauddetector.network.PhoneOut
import com.frauddetector.network.TokenManager
import com.frauddetector.service.BlockedNumbersManager
import com.frauddetector.ui.detail.PhoneDetailActivity
import com.frauddetector.ui.dialog.ReportBottomSheet
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import java.util.concurrent.Executors

class PhoneFragment : Fragment() {

    private lateinit var adapter: PhoneAdapter
    private lateinit var tvOfflineBanner: TextView
    private val searchHandler = Handler(Looper.getMainLooper())
    private var pendingSearch: Runnable? = null
    private val executor = Executors.newSingleThreadExecutor()

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View? {
        return inflater.inflate(R.layout.fragment_phone, container, false)
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        val rv = view.findViewById<RecyclerView>(R.id.rvPhones)
        tvOfflineBanner = view.findViewById(R.id.tvPhoneOfflineBanner)
        adapter = PhoneAdapter(
            items = emptyList(),
            onMore = { phone ->
                val intent = Intent(requireContext(), PhoneDetailActivity::class.java)
                intent.putExtra("phoneNumber", phone.number)
                startActivity(intent)
            },
            onBlock = { phone ->
                val nowBlocked = BlockedNumbersManager.toggle(requireContext(), phone.number)
                if (nowBlocked) {
                    Toast.makeText(requireContext(), "已封鎖 ${phone.number}", Toast.LENGTH_SHORT).show()
                    adapter.removeItem(phone.id)
                }
            },
            onReport = { phone ->
                ReportBottomSheet.newInstance(phone.number).show(childFragmentManager, "report")
            },
            onDial = { phone ->
                try {
                    startActivity(Intent(Intent.ACTION_DIAL, Uri.parse("tel:${phone.number}")))
                } catch (e: ActivityNotFoundException) {
                    Toast.makeText(requireContext(), "找不到撥號 App", Toast.LENGTH_SHORT).show()
                }
            }
        )
        rv.layoutManager = LinearLayoutManager(requireContext())
        rv.adapter = adapter

        // 初始載入：查詢後端詐騙電話資料庫（不帶關鍵字）
        searchPhones(null)

        // 搜尋框：debounce 400ms 後打 GET /api/v1/phones?search=
        view.findViewById<EditText>(R.id.etPhoneSearch).addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun afterTextChanged(s: Editable?) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {
                pendingSearch?.let { searchHandler.removeCallbacks(it) }
                val query = s?.toString()?.trim().orEmpty()
                val runnable = Runnable { searchPhones(query.ifEmpty { null }) }
                pendingSearch = runnable
                searchHandler.postDelayed(runnable, 400)
            }
        })

        view.findViewById<ImageButton>(R.id.btnPhoneInfo).setOnClickListener {
            Toast.makeText(requireContext(), "資料來源：社群回報的詐騙電話資料庫", Toast.LENGTH_SHORT).show()
        }
    }

    private fun searchPhones(query: String?) {
        val ctx = context?.applicationContext ?: return
        val token = TokenManager(ctx).accessToken
        if (token.isNullOrEmpty()) {
            Toast.makeText(ctx, "請先登入以查詢電話資料庫", Toast.LENGTH_SHORT).show()
            return
        }

        ApiClient.phoneApi.listPhones("Bearer $token", search = query)
            .enqueue(object : Callback<PhoneListResponse> {
                override fun onResponse(call: Call<PhoneListResponse>, response: Response<PhoneListResponse>) {
                    if (!isAdded) return
                    if (response.isSuccessful) {
                        tvOfflineBanner.visibility = View.GONE
                        val items = response.body()?.items ?: emptyList()
                        val records = items
                            .filterNot { BlockedNumbersManager.isBlocked(ctx, it.phoneNumber) }
                            .map { it.toPhoneRecord() }
                        adapter.updateItems(records)

                        // 查詢成功且不是搜尋（完整清單）時，整批寫入本機快取，供下次查詢失敗時退回顯示
                        if (query == null) {
                            executor.execute {
                                val dao = AppDatabase.getInstance(ctx).cachedPhoneDao()
                                val now = System.currentTimeMillis()
                                dao.replaceAll(items.map { it.toCachedPhone(now) })
                            }
                        }
                    } else {
                        Toast.makeText(
                            ctx,
                            "查詢失敗：${ApiClient.parseError(response.errorBody()?.string())}",
                            Toast.LENGTH_SHORT
                        ).show()
                    }
                }

                override fun onFailure(call: Call<PhoneListResponse>, t: Throwable) {
                    if (!isAdded) return
                    loadFromCache(ctx, query)
                }
            })
    }

    /** 連網查詢失敗（無網路／逾時）時，退回本機快取顯示，並在畫面上標示資料非即時 */
    private fun loadFromCache(ctx: android.content.Context, query: String?) {
        executor.execute {
            val dao = AppDatabase.getInstance(ctx).cachedPhoneDao()
            val cached = dao.getAll()
            val lastSync = dao.getLastSyncTime()

            activity?.runOnUiThread {
                if (!isAdded) return@runOnUiThread
                if (cached.isEmpty()) {
                    Toast.makeText(ctx, "網路連線失敗，且尚無本機快取資料", Toast.LENGTH_SHORT).show()
                    return@runOnUiThread
                }
                val records = cached
                    .filter { query.isNullOrBlank() || it.phoneNumber.contains(query) }
                    .filterNot { BlockedNumbersManager.isBlocked(ctx, it.phoneNumber) }
                    .map { it.toPhoneRecord() }
                adapter.updateItems(records)
                tvOfflineBanner.text = "⚠ 網路連線失敗，顯示離線快取資料（${formatCacheAge(lastSync)}）"
                tvOfflineBanner.visibility = View.VISIBLE
            }
        }
    }

    private fun formatCacheAge(cachedAt: Long?): String {
        if (cachedAt == null) return "時間未知"
        val minutes = (System.currentTimeMillis() - cachedAt) / 60000
        return when {
            minutes < 1 -> "剛剛更新"
            minutes < 60 -> "最後更新於 $minutes 分鐘前"
            else -> "最後更新於 ${minutes / 60} 小時前"
        }
    }

    private fun PhoneOut.toPhoneRecord() = PhoneRecord(
        id = id.toString(),
        number = phoneNumber,
        riskLevel = riskLevel,
        riskLabel = riskLabelOf(riskLevel),
        type = fraudType ?: "未分類",
        count = reportCount.toString(),
        lastReport = lastReportedAt?.take(10) ?: "—",
        reports = emptyList()
    )

    private fun PhoneOut.toCachedPhone(cachedAt: Long) = CachedPhone(
        phoneNumber = phoneNumber,
        riskLevel = riskLevel,
        fraudType = fraudType,
        reportCount = reportCount,
        lastReportedAt = lastReportedAt,
        cachedAt = cachedAt
    )

    private fun CachedPhone.toPhoneRecord() = PhoneRecord(
        id = phoneNumber,
        number = phoneNumber,
        riskLevel = riskLevel,
        riskLabel = riskLabelOf(riskLevel),
        type = fraudType ?: "未分類",
        count = reportCount.toString(),
        lastReport = lastReportedAt?.take(10) ?: "—",
        reports = emptyList()
    )

    private fun riskLabelOf(level: String) = when (level) {
        "high" -> "詐騙"
        "mid" -> "可疑"
        else -> "安全"
    }
}
