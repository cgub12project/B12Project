package com.frauddetector.service

import android.telecom.Call
import android.telecom.CallScreeningService
import android.util.Log
import com.frauddetector.db.AppDatabase
import java.util.concurrent.Executors

/**
 * 來電篩選服務 — 系統會在每通來電進來時呼叫 [onScreenCall]，讓 App 決定是否攔截這通電話。
 *
 * 只有在使用者把 FLASH 設為系統的「預設來電辨識/垃圾電話攔截 App」（`ROLE_CALL_SCREENING`，
 * 見 [PermissionHelper.createCallScreeningRoleRequestIntent]）之後，系統才會實際綁定並
 * 呼叫這個服務——沒設定的話這個 class 完全不會被觸發，封鎖名單就只是列表過濾（舊行為）。
 *
 * 攔截邏輯只看使用者自己在「封鎖名單」（[BlockedNumbersManager]）明確封鎖過的號碼，
 * 不會依風險分數自動攔截未曾封鎖過的號碼，避免誤擋正常來電——這個決定跟響鈴標籤是
 * 兩件事：風險標籤只是「提醒」，不代表要自動擋，見下面的風險查詢說明。
 */
class CallBlockingService : CallScreeningService() {

    companion object {
        private const val TAG = "CallBlockingService"

        // onScreenCall 官方文件說是在主執行緒呼叫，但 Room 預設不允許在主執行緒查詢；
        // 用一個共用的背景執行緒處理風險查詢，不影響 respondToCall() 儘快回應系統。
        private val executor = Executors.newSingleThreadExecutor()
    }

    override fun onScreenCall(callDetails: Call.Details) {
        val number = callDetails.handle?.schemeSpecificPart ?: ""
        val isBlocked = number.isNotBlank() && BlockedNumbersManager.isBlocked(applicationContext, number)

        val response = CallResponse.Builder()
            .setDisallowCall(isBlocked)
            .setRejectCall(isBlocked)
            .setSkipCallLog(false)          // 仍然留在通話紀錄裡，使用者查得到被擋了哪些號碼
            .setSkipNotification(isBlocked) // 被擋的電話不跳通知打擾使用者
            .build()

        respondToCall(callDetails, response)

        // 未封鎖的來電：背景查一次本機風險快取（PhoneFragment.syncFullPhoneDatabase 同步下來的
        // 社群 mid/high 風險號碼，完全離線可用，不需要這裡再打網路），命中的話顯示風險標籤
        // 懸浮視窗（CallRiskOverlay）——只是提醒，不影響上面已經送出的允許回應。
        if (!isBlocked && number.isNotBlank()) {
            val normalized = PhoneNumberUtils.normalize(number)
            executor.execute {
                val cached = AppDatabase.getInstance(applicationContext)
                    .cachedPhoneDao()
                    .getAll()
                    .firstOrNull { PhoneNumberUtils.normalize(it.phoneNumber) == normalized }
                if (cached != null && cached.riskLevel != "safe") {
                    Log.d(
                        TAG,
                        "來電號碼命中本機風險快取：$number（riskLevel=${cached.riskLevel}, fraudType=${cached.fraudType}）"
                    )
                    CallRiskOverlay.show(applicationContext, number, cached.riskLevel, cached.fraudType)
                }
            }
        }
    }
}
