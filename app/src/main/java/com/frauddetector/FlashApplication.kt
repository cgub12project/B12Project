package com.frauddetector

import android.app.Application
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import com.frauddetector.network.ApiClient
import com.frauddetector.service.PhoneSyncManager
import com.frauddetector.service.PhoneSyncWorker
import java.util.concurrent.TimeUnit

class FlashApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        ApiClient.init(this)
        schedulePhoneSyncWork()
    }

    /**
     * 電話風險資料庫背景定期同步，不依賴使用者剛好打開電話分頁。
     * `KEEP`：如果排程已經存在就不要重新排一次（避免每次 App 啟動都把冷卻計時重置），
     * WorkManager 的排程本身會跨行程重啟持續存在，不需要每次 onCreate 都重建。
     * 間隔跟 [PhoneSyncManager.SYNC_INTERVAL_MS] 用同一個值，避免兩處各自維護一份數字。
     */
    private fun schedulePhoneSyncWork() {
        val request = PeriodicWorkRequestBuilder<PhoneSyncWorker>(
            PhoneSyncManager.SYNC_INTERVAL_MS, TimeUnit.MILLISECONDS
        ).setConstraints(
            Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
        ).build()

        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
            "phone_risk_db_sync",
            ExistingPeriodicWorkPolicy.KEEP,
            request
        )
    }
}
