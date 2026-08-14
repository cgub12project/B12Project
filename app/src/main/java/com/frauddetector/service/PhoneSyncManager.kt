package com.frauddetector.service

import android.content.Context
import com.frauddetector.db.AppDatabase
import com.frauddetector.db.CachedPhone
import com.frauddetector.network.ApiClient
import com.frauddetector.network.PhoneOut
import com.frauddetector.network.TokenManager
import java.io.IOException

/**
 * 把後端社群資料庫裡「有風險（mid／high）」的號碼整批同步到本機快取（[CachedPhone]），
 * 讓離線時查得到的號碼不再侷限於「使用者自己撥打/接聽過而個別查詢快取過」的那幾支。
 *
 * 呼叫端自行決定要在哪個背景執行緒呼叫（本函式是同步阻塞的）：
 * - [com.frauddetector.ui.main.PhoneFragment] 在使用者打開電話分頁時，透過自己的
 *   單執行緒 executor 呼叫（前景、使用者當下在等資料）
 * - [PhoneSyncWorker] 透過 WorkManager 的背景執行緒定期呼叫（背景、不依賴使用者
 *   剛好打開電話分頁，見 [PhoneSyncWorker] 的排程設定）
 *
 * 兩邊共用同一份 [getLastSyncTime] 冷卻判斷，不會因為兩條觸發路徑而重複同步。
 */
object PhoneSyncManager {
    /** 同步的最小間隔——不用每次觸發都整批重抓，太浪費流量也沒必要。
     * 原本是 6 小時，縮短成 1 小時：這是離線資料新鮮度 vs. 流量/電量的取捨，
     * 之後如果覺得還是太久，再跟使用者確認要調到多短。 */
    const val SYNC_INTERVAL_MS = 60 * 60 * 1000L // 1 小時
    private const val PAGE_SIZE = 100

    /** @return true 表示這次真的打了網路同步（可能成功也可能中途失敗)；false 表示因為冷卻或沒登入而跳過 */
    fun syncFullPhoneDatabase(context: Context): Boolean {
        val dao = AppDatabase.getInstance(context).cachedPhoneDao()
        val lastSync = dao.getLastSyncTime()
        val now = System.currentTimeMillis()
        if (lastSync != null && now - lastSync < SYNC_INTERVAL_MS) return false

        val token = TokenManager(context).accessToken
        if (token.isNullOrEmpty()) return false

        return try {
            val all = mutableListOf<CachedPhone>()
            for (riskLevel in listOf("high", "mid")) {
                var offset = 0
                while (true) {
                    val response = ApiClient.phoneApi.listPhones(
                        "Bearer $token",
                        riskLevel = riskLevel,
                        limit = PAGE_SIZE,
                        offset = offset
                    ).execute()
                    if (!response.isSuccessful) break
                    val body = response.body() ?: break
                    if (body.items.isEmpty()) break
                    all += body.items.map { it.toCachedPhone(now) }
                    offset += body.items.size
                    if (offset >= body.total || body.items.size < PAGE_SIZE) break
                }
            }
            if (all.isNotEmpty()) {
                dao.replaceAll(all)
            }
            true
        } catch (e: IOException) {
            // 同步失敗（無網路/逾時等）：保留現有快取，不清空、不中斷
            false
        }
    }
}

/** [PhoneFragment] 的搜尋結果（單筆查詢）也用得到這個轉換，所以是頂層 extension，不是 object 內的 private member */
fun PhoneOut.toCachedPhone(cachedAt: Long) = CachedPhone(
    phoneNumber = phoneNumber,
    riskLevel = riskLevel,
    fraudType = fraudType,
    reportCount = reportCount,
    lastReportedAt = lastReportedAt,
    cachedAt = cachedAt
)
