package com.frauddetector.ui.main

import android.Manifest
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
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
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.frauddetector.R
import com.frauddetector.adapter.PhoneAdapter
import com.frauddetector.data.PhoneRecord
import com.frauddetector.db.AppDatabase
import com.frauddetector.db.CachedPhone
import com.frauddetector.network.ApiClient
import com.frauddetector.network.PhoneDetailResponse
import com.frauddetector.network.PhoneListResponse
import com.frauddetector.network.PhoneOut
import com.frauddetector.network.TokenManager
import com.frauddetector.service.BlockedNumbersManager
import com.frauddetector.service.CallLogHelper
import com.frauddetector.service.CallRecord
import com.frauddetector.service.PhoneNumberUtils
import com.frauddetector.service.PhoneSyncManager
import com.frauddetector.service.toCachedPhone
import com.frauddetector.ui.detail.PhoneDetailActivity
import com.frauddetector.ui.dialog.ReportBottomSheet
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import java.io.IOException
import java.util.concurrent.Executors

/**
 * 電話分頁：預設清單來源是手機真實通話紀錄（[CallLogHelper]，完全不需要網路），
 * 每支號碼再另外查風險資料（本機快取／後端社群資料庫，這部分才需要網路）。
 * 搜尋框則是查任意號碼（不限於通話過的），走既有的後端搜尋 API。
 */
class PhoneFragment : Fragment() {

    private lateinit var adapter: PhoneAdapter
    private lateinit var tvOfflineBanner: TextView
    private val searchHandler = Handler(Looper.getMainLooper())
    private var pendingSearch: Runnable? = null
    private val executor = Executors.newSingleThreadExecutor()

    private val requestCallLogPermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (!granted) {
            Toast.makeText(requireContext(), "需要通話紀錄權限才能顯示來電清單", Toast.LENGTH_LONG).show()
        }
        loadCallBasedList()
    }

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

        // 預設清單：檢查通話紀錄權限 → 讀取真實通話紀錄（不需要網路）
        checkCallLogPermissionAndLoad()

        // 背景把社群資料庫裡有風險的號碼整批同步到本機，離線時才查得到「使用者自己
        // 沒撥打/接聽過、但社群已經回報過」的號碼，不只是查過的才有資料。
        // 實際同步邏輯在 PhoneSyncManager（跟 PhoneSyncWorker 的背景排程共用同一份），
        // 這裡只是「使用者剛好打開電話分頁」這條前景觸發路徑
        val ctx = context?.applicationContext
        if (ctx != null) {
            executor.execute { PhoneSyncManager.syncFullPhoneDatabase(ctx) }
        }

        // 搜尋框：清空時回到通話紀錄清單；有輸入文字時 debounce 400ms 後查任意號碼
        view.findViewById<EditText>(R.id.etPhoneSearch).addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun afterTextChanged(s: Editable?) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {
                pendingSearch?.let { searchHandler.removeCallbacks(it) }
                val query = s?.toString()?.trim().orEmpty()
                val runnable = Runnable {
                    if (query.isEmpty()) loadCallBasedList() else searchPhones(query)
                }
                pendingSearch = runnable
                searchHandler.postDelayed(runnable, 400)
            }
        })

        view.findViewById<ImageButton>(R.id.btnPhoneInfo).setOnClickListener {
            Toast.makeText(
                requireContext(),
                "預設顯示您的通話紀錄，並標示社群回報的風險等級；搜尋框可查詢任意號碼",
                Toast.LENGTH_LONG
            ).show()
        }
    }

    private fun checkCallLogPermissionAndLoad() {
        if (ContextCompat.checkSelfPermission(requireContext(), Manifest.permission.READ_CALL_LOG)
            == PackageManager.PERMISSION_GRANTED
        ) {
            loadCallBasedList()
        } else {
            requestCallLogPermission.launch(Manifest.permission.READ_CALL_LOG)
        }
    }

    /**
     * 預設清單：讀取真實通話紀錄（本機、不需要網路，一定會有結果），
     * 依號碼分組取每支號碼最新一筆，再套上本機快取／後端查回來的風險資料。
     * 沒網路時只會用本機已有的快取（或顯示「尚無回報資料」），不會擋住整份清單不顯示。
     */
    private fun loadCallBasedList() {
        val ctx = context?.applicationContext ?: return
        executor.execute {
            val hasPermission = ContextCompat.checkSelfPermission(ctx, Manifest.permission.READ_CALL_LOG) ==
                PackageManager.PERMISSION_GRANTED
            val latestPerNumber = if (hasPermission) {
                CallLogHelper.getRecentCalls(ctx, 50)
                    .groupBy { PhoneNumberUtils.normalize(it.number) }
                    .values
                    .mapNotNull { records -> records.maxByOrNull { it.date } }
                    .sortedByDescending { it.date }
            } else {
                emptyList()
            }

            val dao = AppDatabase.getInstance(ctx).cachedPhoneDao()

            // Pass 1：純本機資料立刻顯示，通話紀錄本身跟網路完全無關
            publishCallRecords(ctx, latestPerNumber, dao, offline = false)

            // Pass 2：對「本機還沒有風險資料」的號碼，有網路才去後端個別查詢補上
            val token = TokenManager(ctx).accessToken
            if (!token.isNullOrEmpty()) {
                val cachedNumbers = dao.getAll().map { PhoneNumberUtils.normalize(it.phoneNumber) }.toSet()
                val numbersNeedingLookup = latestPerNumber
                    .map { it.number }
                    .distinct()
                    .filterNot { PhoneNumberUtils.normalize(it) in cachedNumbers }

                var networkFailed = false
                for (number in numbersNeedingLookup) {
                    if (networkFailed) break
                    try {
                        val response = ApiClient.phoneApi.getPhoneDetail("Bearer $token", number).execute()
                        if (response.isSuccessful) {
                            response.body()?.let {
                                dao.insertAll(listOf(it.toCachedPhone(System.currentTimeMillis())))
                            }
                        }
                    } catch (e: IOException) {
                        networkFailed = true // 網路不通，不用再逐個號碼重試
                    }
                }
                // 補完風險資料後重新整理一次畫面；如果是因為沒網路中斷查詢，提示一下（清單本身仍然照常顯示）
                publishCallRecords(ctx, latestPerNumber, dao, offline = networkFailed)
            }
        }
    }

    private fun publishCallRecords(
        ctx: Context,
        latestPerNumber: List<CallRecord>,
        dao: com.frauddetector.db.CachedPhoneDao,
        offline: Boolean
    ) {
        val cachedByNumber = dao.getAll().associateBy { PhoneNumberUtils.normalize(it.phoneNumber) }
        val records = latestPerNumber
            .filterNot { BlockedNumbersManager.isBlocked(ctx, it.number) }
            .map { call -> call.toPhoneRecord(cachedByNumber[PhoneNumberUtils.normalize(call.number)]) }

        activity?.runOnUiThread {
            if (!isAdded) return@runOnUiThread
            adapter.updateItems(records)
            if (offline) {
                tvOfflineBanner.text = "⚠ 目前無網路，部分號碼的風險資料可能不是最新"
                tvOfflineBanner.visibility = View.VISIBLE
            } else {
                tvOfflineBanner.visibility = View.GONE
            }
        }
    }

    /** 搜尋框有輸入文字時：查任意號碼（不限於通話過的），走後端搜尋 API，失敗時退回本機快取 */
    private fun searchPhones(query: String) {
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

                        executor.execute {
                            val dao = AppDatabase.getInstance(ctx).cachedPhoneDao()
                            val now = System.currentTimeMillis()
                            dao.insertAll(items.map { it.toCachedPhone(now) })
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
                    loadSearchFromCache(ctx, query)
                }
            })
    }

    /** 搜尋時連網失敗，退回本機快取裡符合搜尋字串的號碼 */
    private fun loadSearchFromCache(ctx: Context, query: String) {
        executor.execute {
            val dao = AppDatabase.getInstance(ctx).cachedPhoneDao()
            val cached = dao.getAll()
            val lastSync = dao.getLastSyncTime()

            activity?.runOnUiThread {
                if (!isAdded) return@runOnUiThread
                val records = cached
                    .filter { it.phoneNumber.contains(query) }
                    .filterNot { BlockedNumbersManager.isBlocked(ctx, it.phoneNumber) }
                    .map { it.toPhoneRecord() }
                if (records.isEmpty()) {
                    Toast.makeText(ctx, "網路連線失敗，本機也查無這支號碼的資料", Toast.LENGTH_SHORT).show()
                }
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

    private fun CallRecord.toPhoneRecord(cached: CachedPhone?) = PhoneRecord(
        id = number,
        number = number,
        riskLevel = cached?.riskLevel ?: "safe",
        riskLabel = riskLabelOf(cached?.riskLevel ?: "safe"),
        type = cached?.fraudType ?: "尚無回報資料",
        count = (cached?.reportCount ?: 0).toString(),
        lastReport = cached?.lastReportedAt?.take(10) ?: "—",
        reports = emptyList()
    )

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

    private fun PhoneDetailResponse.toCachedPhone(cachedAt: Long) = CachedPhone(
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
