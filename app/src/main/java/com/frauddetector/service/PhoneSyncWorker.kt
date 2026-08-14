package com.frauddetector.service

import android.content.Context
import androidx.work.Worker
import androidx.work.WorkerParameters

/**
 * WorkManager 背景定期同步電話風險資料庫（[PhoneSyncManager]）——不依賴使用者剛好打開
 * 電話分頁，App 沒在前景執行時系統也會照排程叫起來跑。實際同步邏輯（含冷卻判斷、
 * 分頁抓取）都在 [PhoneSyncManager]，這裡只是 WorkManager 要求的 Worker 外殼。
 *
 * 排程設定見 [com.frauddetector.FlashApplication]。
 */
class PhoneSyncWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        return try {
            PhoneSyncManager.syncFullPhoneDatabase(applicationContext)
            Result.success()
        } catch (e: Exception) {
            // 背景排程失敗不用重試到底——反正冷卻時間到、下次排程或使用者開電話分頁時
            // 還會再試一次，沒必要因為一次失敗就讓 WorkManager 短時間內重跑耗電
            Result.success()
        }
    }
}
