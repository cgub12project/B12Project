package com.frauddetector.ui.main

import android.content.Context
import android.content.Intent
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
import androidx.appcompat.app.AlertDialog
import androidx.fragment.app.Fragment
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import androidx.room.InvalidationTracker
import com.frauddetector.R
import com.frauddetector.adapter.EmailAdapter
import com.frauddetector.data.EmailAlert
import com.frauddetector.db.AppDatabase
import com.frauddetector.db.CapturedNotification
import com.frauddetector.network.ApiClient
import com.frauddetector.network.MailBlockSenderRequest
import com.frauddetector.network.MailMessageItem
import com.frauddetector.network.TokenManager
import com.frauddetector.service.BlockedEmailsManager
import com.frauddetector.service.RagDetector
import com.frauddetector.ui.SwipeToDeleteHelper
import com.frauddetector.ui.detail.MailMessageDetailActivity
import com.frauddetector.ui.dialog.BlockConfirmDialog
import com.frauddetector.ui.dialog.MessageReportBottomSheet
import com.google.android.material.chip.Chip
import com.google.android.material.chip.ChipGroup
import java.io.IOException
import java.text.SimpleDateFormat
import java.time.Instant
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors

class EmailFragment : Fragment() {

    companion object {
        /**
         * 每次切到郵件分頁，`MainActivity` 是用 `replace()` 換 Fragment，不是 show/hide，
         * 所以 `EmailFragment` 實例本身、包括它所有的欄位，每次切分頁都是全新的——
         * 原本 `lastKnownMailItems` 是實例欄位，一離開再回來就歸零，等於每次都要
         * 重新等一次網路查詢才有東西可看，切分頁感覺很卡。改成放在 companion object
         * （跟著 App 行程活，不跟著 Fragment 實例），切分頁回來能立刻用上次的結果先顯示，
         * 背景再視情況重新整理，不會每次都從空白開始。
         *
         * 2026-08-18 補上 SharedPreferences 備份：上面這個 companion object 變數只跟著
         * App 行程活，行程被系統殺掉或使用者滑掉重開（不只是切分頁）一樣會歸零，
         * 導致「重新點進 App、郵件分頁空白等同步」——跟 RagDetector 對話快取原本的問題
         * 是同一類，做法也一樣：process 重啟後第一次用到時，先從 SharedPreferences
         * 復原上次的結果，不用整個 DB schema，零風險。
         */
        private var cachedMailItems: List<MailMessageItem> = emptyList()
        private var cachedMailItemsRestored = false

        private const val MAIL_CACHE_PREFS = "email_fragment_cache"
        private const val MAIL_CACHE_KEY = "cached_mail_items"

        private fun restoreCachedMailItemsIfNeeded(context: Context) {
            if (cachedMailItemsRestored) return
            cachedMailItemsRestored = true
            if (cachedMailItems.isNotEmpty()) return
            val json = context.applicationContext
                .getSharedPreferences(MAIL_CACHE_PREFS, Context.MODE_PRIVATE)
                .getString(MAIL_CACHE_KEY, null) ?: return
            try {
                val type = object : com.google.gson.reflect.TypeToken<List<MailMessageItem>>() {}.type
                cachedMailItems = ApiClient.gson.fromJson(json, type)
            } catch (e: Exception) {
                // 復原失敗就當作沒有，正常走 Pass 3 的網路同步
            }
        }

        private fun persistCachedMailItems(context: Context, items: List<MailMessageItem>) {
            val json = ApiClient.gson.toJson(items)
            context.applicationContext
                .getSharedPreferences(MAIL_CACHE_PREFS, Context.MODE_PRIVATE)
                .edit().putString(MAIL_CACHE_KEY, json).apply()
        }
    }

    private lateinit var adapter: EmailAdapter
    private lateinit var tvSyncStatus: TextView
    private lateinit var tvSubtitle: TextView
    private lateinit var tvUnanalyzedHint: TextView
    private var currentProviderFilter = "全部"
    private val executor = Executors.newSingleThreadExecutor()

    // 即時刷新：同 MessagesFragment，captured_notifications 表有任何寫入就 debounce 重新載入
    private val refreshHandler = Handler(Looper.getMainLooper())
    private var pendingRefresh: Runnable? = null
    private val dbObserver = object : InvalidationTracker.Observer("captured_notifications") {
        override fun onInvalidated(tables: Set<String>) {
            pendingRefresh?.let { refreshHandler.removeCallbacks(it) }
            // 本機通知資料變動觸發的刷新不用重新呼叫後端同步（同步可能跑數十秒），
            // 只重讀本機資料 + 重新查一次已分析信件列表
            val r = Runnable { loadEmails(triggerSync = false) }
            pendingRefresh = r
            refreshHandler.postDelayed(r, 400)
        }
    }

    override fun onResume() {
        super.onResume()
        val ctx = context?.applicationContext ?: return
        AppDatabase.getInstance(ctx).invalidationTracker.addObserver(dbObserver)
    }

    override fun onPause() {
        super.onPause()
        pendingRefresh?.let { refreshHandler.removeCallbacks(it) }
        val ctx = context?.applicationContext ?: return
        AppDatabase.getInstance(ctx).invalidationTracker.removeObserver(dbObserver)
    }

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View? {
        return inflater.inflate(R.layout.fragment_email, container, false)
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        val rv = view.findViewById<RecyclerView>(R.id.rvEmails)
        tvSyncStatus = view.findViewById(R.id.tvMailSyncStatus)
        tvSubtitle = view.findViewById(R.id.tvEmailSubtitle)
        tvUnanalyzedHint = view.findViewById(R.id.tvUnanalyzedHint)
        adapter = EmailAdapter(
            items = emptyList(),
            onBlock = { email ->
                // 封鎖寄件人在 Gmail 端會真的建立過濾規則（不只是本機隱藏），
                // 誤觸的代價比其他操作大，一律先跳確認（見 BlockConfirmDialog 的說明）
                BlockConfirmDialog.forAccount(email.sender) {
                    val ctx = requireContext()
                    val nowBlocked = BlockedEmailsManager.toggle(ctx, email.sender)
                    if (nowBlocked) {
                        Toast.makeText(ctx, "已封鎖 ${email.sender}", Toast.LENGTH_SHORT).show()
                        adapter.removeItem(email.id)
                        // 真實郵件（有連接信箱帳號）另外呼叫後端在 Gmail 端真的建立封鎖規則；
                        // 本機通知擷取的項目沒有對應的信箱帳號，只能停在上面的本機清單過濾
                        if (email.id.startsWith("mail_") && email.accountEmail.isNotEmpty()) {
                            blockSenderOnBackend(email.accountEmail, email.sender)
                        }
                    }
                }.show(childFragmentManager, "blockConfirm")
            },
            onOpenDetail = { email ->
                val rawId = email.id.removePrefix("mail_").toIntOrNull()
                val mailItem = cachedMailItems.firstOrNull { it.id == rawId }
                if (mailItem != null) {
                    startActivity(
                        Intent(requireContext(), MailMessageDetailActivity::class.java)
                            .putExtra(MailMessageDetailActivity.EXTRA_MAIL_ITEM, mailItem)
                    )
                } else {
                    Toast.makeText(requireContext(), "找不到這封信的資料，請重新整理", Toast.LENGTH_SHORT).show()
                }
            },
            onReport = { email -> confirmAndReport(email) }
        )
        rv.layoutManager = LinearLayoutManager(requireContext())
        rv.adapter = adapter

        // 左滑刪除：滑到底跳確認對話框，確認才真的刪除本機擷取的郵件紀錄（可能是廣告郵件佔用列表）
        SwipeToDeleteHelper.attach(
            context = requireContext(),
            recyclerView = rv,
            getLabel = { position -> adapter.getItemAt(position).sender },
            onConfirmedDelete = { position -> deleteEmail(adapter.getItemAt(position)) },
            onCanceled = { position -> adapter.notifyItemChanged(position) }
        )

        // 在背景執行緒排隊做完整的 loadEmails() 之前，先在主執行緒同步把上次同步結果畫出來——
        // restoreCachedMailItemsIfNeeded 讀的是小檔案的 SharedPreferences，很快，換來的是
        // 少一次「丟給背景執行緒排隊→查 DB→切回主執行緒」的來回，肉眼可見的空白閃一下會消失。
        // 本機通知擷取的郵件（不是這次同步結果的那些）還是交給下面 loadEmails() 的背景流程補上。
        val appCtx = requireContext().applicationContext
        restoreCachedMailItemsIfNeeded(appCtx)
        if (cachedMailItems.isNotEmpty()) {
            publishItems(appCtx, emptyList(), cachedMailItems)
        }

        // 第一次進分頁才觸發後端信箱同步（可能跑數十秒），InvalidationTracker 觸發的刷新不重複同步
        loadEmails(triggerSync = true)

        // 搜尋圖示 → 展開/收合搜尋框
        val searchBox = view.findViewById<View>(R.id.emailSearchBox)
        val etSearch = view.findViewById<EditText>(R.id.etEmailSearch)
        view.findViewById<ImageButton>(R.id.btnEmailSearch).setOnClickListener {
            if (searchBox.visibility == View.VISIBLE) {
                searchBox.visibility = View.GONE
                etSearch.setText("")
            } else {
                searchBox.visibility = View.VISIBLE
            }
        }
        etSearch.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun afterTextChanged(s: Editable?) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {
                adapter.filterByQuery(s?.toString() ?: "")
            }
        })

        // Provider chip filter — 動態生成，在 loadEmails() 後建立
    }

    /**
     * 真封鎖：先查一次已連接信箱清單，用 email 反查 account_id（MailMessageItem 本身
     * 只有 account_email，沒有 account_id），再呼叫 block-sender。sender 欄位可能是
     * 「"顯示名稱" <email>」這種完整格式，Gmail 的過濾規則條件要吃乾淨的 email 地址，
     * 有角括號的話先抽出來。本機清單（BlockedEmailsManager）已經在呼叫端先切好，
     * 這裡失敗只提示、不影響本機封鎖已經生效的事實。
     */
    private fun blockSenderOnBackend(accountEmail: String, rawSender: String) {
        val ctx = context?.applicationContext ?: return
        val token = TokenManager(ctx).accessToken ?: return
        val senderAddress = extractEmailAddress(rawSender)
        executor.execute {
            try {
                val accountsResp = ApiClient.mailApi.listMailAccounts("Bearer $token").execute()
                val accountId = accountsResp.body()?.items
                    ?.firstOrNull { it.emailAddress == accountEmail }?.id
                if (accountId == null) return@execute
                val response = ApiClient.mailApi.blockSender(
                    "Bearer $token", accountId,
                    MailBlockSenderRequest(senderAddress)
                ).execute()
                activity?.runOnUiThread {
                    if (!isAdded) return@runOnUiThread
                    if (response.isSuccessful) {
                        Toast.makeText(ctx, "已在 Gmail 端封鎖 $senderAddress，之後這個寄件人的信不會再進收件匣", Toast.LENGTH_LONG).show()
                    } else {
                        val err = ApiClient.parseError(response.errorBody()?.string())
                        Toast.makeText(ctx, "本機已封鎖，但 Gmail 端封鎖失敗：$err", Toast.LENGTH_LONG).show()
                    }
                }
            } catch (e: IOException) {
                activity?.runOnUiThread {
                    if (isAdded) Toast.makeText(ctx, "本機已封鎖，但網路異常，Gmail 端封鎖未完成", Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    private fun extractEmailAddress(raw: String): String {
        val match = Regex("<([^>]+)>").find(raw)
        return match?.groupValues?.get(1) ?: raw
    }

    /**
     * 回報前先跳提醒：這支端點（GET .../content）後端明確表示是設計給回報用的，
     * 會把信件完整內容抓回來——使用者要清楚知道「繼續」等於把完整信件內容送到後端、
     * 存進社群回報資料庫，不是靜默發生。取消就什麼都不做，不會呼叫任何 API。
     */
    private fun confirmAndReport(email: EmailAlert) {
        AlertDialog.Builder(requireContext())
            .setTitle("回報前提醒")
            .setMessage("回報會把這封信的完整內容傳送到後端，存進社群回報資料庫，其他使用者查詢時看得到。確定要繼續嗎？")
            .setPositiveButton("繼續回報") { _, _ -> fetchContentThenShowReportSheet(email) }
            .setNegativeButton("取消", null)
            .show()
    }

    private fun fetchContentThenShowReportSheet(email: EmailAlert) {
        val ctx = context?.applicationContext ?: return
        val token = TokenManager(ctx).accessToken
        if (token.isNullOrEmpty()) {
            Toast.makeText(ctx, "請先登入", Toast.LENGTH_SHORT).show()
            return
        }
        val rawId = email.id.removePrefix("mail_").toIntOrNull()
        if (rawId == null) {
            Toast.makeText(ctx, "找不到這封信的資料，請重新整理", Toast.LENGTH_SHORT).show()
            return
        }
        executor.execute {
            try {
                val response = ApiClient.mailApi.getMailMessageContent("Bearer $token", rawId).execute()
                activity?.runOnUiThread {
                    if (!isAdded) return@runOnUiThread
                    if (response.isSuccessful) {
                        val content = response.body()
                        MessageReportBottomSheet.newInstance(
                            accountName = email.sender,
                            platform = email.provider,
                            accountId = "",
                            platformOptions = listOf(email.provider),
                            content = content?.reportText ?: ""
                        ).show(childFragmentManager, "report_email")
                    } else {
                        Toast.makeText(
                            ctx,
                            "取得信件內容失敗：${ApiClient.parseError(response.errorBody()?.string())}",
                            Toast.LENGTH_SHORT
                        ).show()
                    }
                }
            } catch (e: IOException) {
                activity?.runOnUiThread {
                    if (isAdded) Toast.makeText(ctx, "網路錯誤，無法取得信件內容", Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    /** 根據實際資料動態產生郵件供應商篩選 Chips */
    private fun buildDynamicChips(items: List<EmailAlert>) {
        val chipGroup = view?.findViewById<ChipGroup>(R.id.chipGroupProvider) ?: return
        chipGroup.removeAllViews()

        val chipAll = Chip(requireContext()).apply {
            text = "全部"
            isCheckable = true
            isChecked = currentProviderFilter == "全部"
        }
        chipGroup.addView(chipAll)

        // 即時刷新會重建整個 ChipGroup，用 currentProviderFilter 還原原本選取的 chip
        val providers = items.map { it.provider }.distinct().sorted()
        providers.forEach { provider ->
            val chip = Chip(requireContext()).apply {
                text = provider
                isCheckable = true
                isChecked = provider == currentProviderFilter
            }
            chipGroup.addView(chip)
        }

        chipGroup.setOnCheckedStateChangeListener { _, checkedIds ->
            currentProviderFilter = if (checkedIds.isEmpty() || checkedIds.first() == chipAll.id) {
                "全部"
            } else {
                val selectedChip = chipGroup.findViewById<Chip>(checkedIds.first())
                selectedChip?.text?.toString() ?: "全部"
            }
            adapter.filterByProvider(currentProviderFilter)
        }
    }

    /**
     * @param triggerSync 這次載入是不是「使用者主動打開郵件分頁」（而不是本機資料變動觸發的
     * 背景刷新）。是的話就呼叫後端 `POST /mail/sync`（抓已連接信箱的新信 + AI 判斷，可能跑
     * 數十秒）——每次都真的同步，不做冷卻節流，避免「剛重新連接信箱、想立刻看到最新資料」
     * 卻被冷卻擋掉、看起來像「同步了但沒看到信」。畫面不會因此空白閃爍是靠 [cachedMailItems]
     * （Pass 1 先用上次結果墊著顯示），不是靠這裡少打 API。
     */
    private fun loadEmails(triggerSync: Boolean) {
        // 先取用 applicationContext（理由同 MessagesFragment）：Fragment 若在背景任務跑完前
        // 就 detach，requireContext() 會拋例外把整個背景執行緒帶崩，進而讓 App 閃退。
        val ctx = context?.applicationContext ?: return
        executor.execute {
            // App 行程重啟後第一次進來，先把上次同步結果從 SharedPreferences 復原回
            // cachedMailItems，讓下面 Pass 1 不會拿到空清單墊底（見 companion object 說明）。
            restoreCachedMailItemsIfNeeded(ctx)

            val db = AppDatabase.getInstance(ctx)
            val dao = db.capturedNotificationDao()

            // 清掉舊版本插入過的 Gmail/Outlook 測試種子資料（現在郵件頁改用真實信箱連接取得
            // 資料，不需要假資料）。先 SELECT COUNT 確認真的有殘留才執行 DELETE——
            // deleteEmailTestSeed() 本身是 no-op 安全的，但即使刪 0 筆，寫入語句還是會
            // 觸發 InvalidationTracker 讓 captured_notifications 的觀察者以為有資料變動，
            // 造成 loadEmails() 被無謂地重新觸發、跟這次呼叫自己形成迴圈。
            if (dao.getEmailTestSeedCount() > 0) {
                dao.deleteEmailTestSeed()
            }

            // 取得每個 sender 的最新一筆郵件（本機通知擷取的）
            val grouped = dao.getLatestEmailPerSender()

            // Pass 1：先用目前已快取的風險等級立刻顯示列表，不等待 AI 偵測；
            // mailItems 用上一次成功查到的結果墊著，不要傳空清單（見 cachedMailItems 說明）
            publishItems(ctx, grouped, cachedMailItems)

            // Pass 2：背景逐一偵測尚未快取風險的郵件，偵測完再重新整理一次畫面
            var anyNewlyDetected = false
            val detected = grouped.map { notif ->
                if (notif.riskLevel == null) {
                    anyNewlyDetected = true
                    RagDetector.detectAndCache(ctx, notif)
                } else {
                    notif
                }
            }
            if (anyNewlyDetected) {
                publishItems(ctx, detected, cachedMailItems)
            }

            // Pass 3：已連接信箱（Gmail/Outlook API）的真實郵件，需要登入 + 網路，失敗就靜默降級
            // 為只顯示本機通知擷取的資料，不影響前兩個 Pass 已經顯示的內容
            val token = TokenManager(ctx).accessToken
            if (!token.isNullOrEmpty()) {
                // 冷卻機制拿掉了——之前的顧慮是「切分頁太頻繁會一直重打同步」，但實測發現
                // 冷卻視窗內剛好遇到「重新連接信箱後想立刻看到最新資料」會被誤擋，看起來像
                // 「同步了但沒看到信」。畫面不會空白是靠 cachedMailItems（Pass 1 立刻用上次
                // 結果先顯示），不需要再靠這個冷卻來避免閃爍，兩者職責分開比較不會互相打架。
                if (triggerSync) {
                    activity?.runOnUiThread { if (isAdded) tvSyncStatus.visibility = View.VISIBLE }
                    try {
                        ApiClient.mailApi.syncMailboxes("Bearer $token").execute()
                    } catch (e: IOException) {
                        // 同步失敗（無網路/逾時等）不影響本機資料顯示
                    } finally {
                        activity?.runOnUiThread { if (isAdded) tvSyncStatus.visibility = View.GONE }
                    }
                }
                try {
                    val response = ApiClient.mailApi.listMailMessages("Bearer $token", limit = 50).execute()
                    if (response.isSuccessful) {
                        val mailItems = response.body()?.items ?: emptyList()
                        cachedMailItems = mailItems
                        persistCachedMailItems(ctx, mailItems)
                        publishItems(ctx, detected, mailItems)
                    }
                } catch (e: IOException) {
                    // 查詢失敗，維持上一次已知的真實郵件資料，不清空
                }
            }
        }
    }

    /**
     * 左滑刪除確認後執行：從本機 DB 刪掉這個寄件人的所有擷取郵件，並立即從列表移除。
     * 只刪本機擷取紀錄，不影響真正的 Gmail/Outlook 信箱。
     *
     * 透過信箱連接讀到的真實郵件（id 以 "mail_" 開頭）沒有對應的刪除端點，
     * 這裡不處理刪除，只還原滑動視覺狀態；要隱藏可以改用封鎖寄件人。
     */
    private fun deleteEmail(email: EmailAlert) {
        if (email.id.startsWith("mail_")) {
            Toast.makeText(
                requireContext(),
                "這是透過信箱連接讀取的真實郵件，無法在這裡刪除；可以封鎖寄件人來隱藏",
                Toast.LENGTH_LONG
            ).show()
            adapter.notifyDataSetChanged()
            return
        }

        val ctx = requireContext().applicationContext
        val parts = email.id.removePrefix("grp_").split("_", limit = 2)
        if (parts.size == 2) {
            val (app, sender) = parts
            executor.execute {
                AppDatabase.getInstance(ctx).capturedNotificationDao().deleteEmailConversation(sender, app)
            }
        }
        adapter.removeItem(email.id)
        Toast.makeText(requireContext(), "已刪除「${email.sender}」的郵件紀錄", Toast.LENGTH_SHORT).show()
    }

    /** 合併本機通知擷取的郵件 + 已連接信箱的真實郵件，依時間新到舊排序後一起顯示 */
    private fun publishItems(ctx: Context, grouped: List<CapturedNotification>, mailItems: List<MailMessageItem>) {
        val notifPairs = grouped.map { it.timestamp to it.toGroupedEmailAlert() }
        val mailPairs = mailItems.map { parseIsoTimestamp(it.receivedAt) to it.toEmailAlert() }
        val items = (notifPairs + mailPairs)
            .sortedByDescending { it.first }
            .map { it.second }
            .filterNot { BlockedEmailsManager.isBlocked(ctx, it.sender) }

        activity?.runOnUiThread {
            if (!isAdded) return@runOnUiThread
            adapter.updateItems(items)
            buildDynamicChips(items)
            tvSubtitle.text = "${items.count { it.level == "high" || it.level == "mid" }} SUSPICIOUS"

            val unanalyzedCount = items.count { it.level == "unanalyzed" }
            tvUnanalyzedHint.text = "$unanalyzedCount 封尚未完成分析，暫不計入安全數量"
            tvUnanalyzedHint.visibility = if (unanalyzedCount > 0) View.VISIBLE else View.GONE
        }
    }
}

/**
 * `Instant.parse()` 只吃嚴格帶時區的 ISO 字串（例如結尾有 "Z" 或 "+08:00"）。
 * 後端如果回傳沒有時區資訊的「naive」ISO 字串（例如 FastAPI/Pydantic 常見的
 * "2026-08-05T10:30:00"，沒有結尾時區標記），Instant.parse 會直接丟例外，
 * 原本的寫法會整個吃掉例外退回 0（顯示成 1970 年、排序也全部黏在一起，
 * 對應到「時間錯亂」的回報）。這裡改成退回時當作 UTC 時間解析，而不是直接放棄。
 */
private fun parseIsoTimestamp(iso: String): Long {
    return try {
        Instant.parse(iso).toEpochMilli()
    } catch (e: Exception) {
        try {
            java.time.LocalDateTime.parse(iso).atZone(java.time.ZoneOffset.UTC).toInstant().toEpochMilli()
        } catch (e2: Exception) {
            0L
        }
    }
}

private fun CapturedNotification.toGroupedEmailAlert(): EmailAlert {
    val sdf = SimpleDateFormat("MM/dd HH:mm", Locale.getDefault())
    val timeStr = sdf.format(Date(timestamp))
    // 還沒分析完（或分析失敗）不能當「安全」——理由同 MessagesFragment 的 toGroupedAlertItem
    val level = riskLevel ?: "unanalyzed"
    // 標籤（來源／詐騙類型）移除（2026-08-18，跟訊息分頁同一次改版）：卡片下方標籤跟
    // MailMessageDetailActivity 顯示的內容重複，列表上只留卡片顏色＋詳情頁再看細節。
    val tags = emptyList<String>()

    return EmailAlert(
        id = "grp_${app}_${sender}",
        sender = sender,
        subject = content.take(60),
        preview = content,
        time = timeStr,
        level = level,       // 由 /rag/detect 判斷後快取的風險等級
        provider = app,   // "Gmail" or "Outlook"
        tags = tags
    )
}

/**
 * 已連接信箱抓回來、後端已完成 AI 判斷的真實郵件。
 * `sender`／`subject`／`preview` 是後端當次即時向 Gmail API／Graph API 取回的，
 * 取不到時（授權失效、配額用盡等）為 null，用預設文字顯示，不影響風險判定結果照常顯示。
 */
private fun MailMessageItem.toEmailAlert(): EmailAlert {
    val sdf = SimpleDateFormat("MM/dd HH:mm", Locale.getDefault())
    val timeStr = try {
        sdf.format(Date(parseIsoTimestamp(receivedAt)))
    } catch (e: Exception) {
        "—"
    }
    val providerLabel = if (provider == "gmail") "Gmail" else "Outlook"
    // 標籤移除（見 toGroupedEmailAlert 說明）：providerLabel／scamType 在
    // MailMessageDetailActivity 的 tvMeta／風險列已經會顯示，這裡不重複。
    val tags = emptyList<String>()

    return EmailAlert(
        id = "mail_$id",
        sender = sender ?: "(寄件者未知)",
        subject = subject ?: "(無法取得主旨)",
        preview = preview ?: if (!previewAvailable) "內容暫時無法取得（授權可能已失效，請至設定重新連接）" else "",
        time = timeStr,
        level = riskLevel,
        provider = providerLabel,
        tags = tags,
        accountEmail = accountEmail
    )
}
