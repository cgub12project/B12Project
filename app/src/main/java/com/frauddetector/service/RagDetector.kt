package com.frauddetector.service

import android.content.Context
import android.util.Log
import com.frauddetector.db.AppDatabase
import com.frauddetector.db.CapturedNotification
import com.frauddetector.network.ApiClient
import com.frauddetector.network.RagDetectRequest
import com.frauddetector.network.RagDetectResponse
import com.frauddetector.network.TokenManager

/**
 * 呼叫後端 /api/v1/rag/detect 取得訊息的 AI 風險判斷，並快取到 Room DB，
 * 避免同一則訊息重複打 API。
 *
 * 必須在背景執行緒呼叫（內部為同步 Retrofit 呼叫）。
 */
object RagDetector {
    private const val TAG = "RagDetector"

    /**
     * 若該筆通知已有快取風險則直接回傳；否則呼叫 /rag/detect 並寫回 DB。
     * 未登入或呼叫失敗時，原樣回傳（riskLevel 維持 null，UI 端會以 "safe" 顯示）。
     */
    fun detectAndCache(context: Context, notification: CapturedNotification): CapturedNotification {
        if (notification.riskLevel != null) return notification

        val token = TokenManager(context).accessToken
        if (token.isNullOrEmpty()) return notification

        return try {
            val response = ApiClient.ragApi
                .detect("Bearer $token", RagDetectRequest(notification.content))
                .execute()

            val body = response.body()
            if (response.isSuccessful && body != null) {
                val reason = body.reasons.firstOrNull()
                AppDatabase.getInstance(context).capturedNotificationDao()
                    .updateRisk(notification.id, body.riskLevel, body.scamType, reason, body.confidence)
                notification.copy(
                    riskLevel = body.riskLevel,
                    scamType = body.scamType,
                    aiReason = reason,
                    confidence = body.confidence
                )
            } else {
                Log.w(TAG, "detect failed: HTTP ${response.code()}")
                notification
            }
        } catch (e: Exception) {
            Log.e(TAG, "detect failed for id=${notification.id}", e)
            notification
        }
    }

    /**
     * 把群組對話串接成一段文字：「發送者: 內容」每則一行，依時間先後排列，用換行符號銜接。
     * 格式已用真實案例驗證過（見 [detectConversationRisk] 的說明）。
     *
     * @param limit 最多取幾則（依時間新到舊取，取完後轉回舊到新排列）
     */
    fun buildConversationText(messages: List<CapturedNotification>, limit: Int = 15): String {
        return messages
            .sortedByDescending { it.timestamp }
            .take(limit)
            .sortedBy { it.timestamp }
            .joinToString("\n") { "${it.sender}: ${it.content}" }
    }

    /** 群組整體對話判斷結果的記憶體快取：conversationKey → (視窗指紋, 上次結果)。 */
    private val conversationCache = mutableMapOf<String, Pair<String, RagDetectResponse>>()

    /**
     * 對群組對話做整體判斷：把最近 [limit] 則訊息用 [buildConversationText] 串接後，
     * 一次呼叫 /rag/detect 取得整段對話的風險等級與完整解釋（reasons/advice）。
     *
     * 取代舊版「逐則訊息分析取最高風險」的做法——已用真實案例驗證過：三則各自分析
     * 最高只到 mid（0.68），串接後同一組訊息直接判成 high（0.73），且判定理由會
     * 明確點名多個發送者（例如「Jessica 老師分析賺翻、小美跟著操作賺20萬」），
     * 證實這個格式真的能讓 AI 看出「群組裡多人互相佐證同一套話術」這種只看單句
     * 看不出來的模式。
     *
     * 用「視窗指紋」（訊息數＋最新一筆的 id）記憶體快取結果——同一個對話只要沒有新
     * 訊息進來，視窗內容就跟上次完全一樣，直接回傳上次結果，不必每次打開同一個
     * 群組對話都重新等一次 API；一有新訊息，指紋跟著變，就會自動重新分析。
     * 只存在記憶體（App 程序存活期間），不會寫進 DB，符合「即時視窗、不長期累積」
     * 的設計原則。
     *
     * @param conversationKey 對話識別碼（例如 "$app|$groupName"），用來區分不同對話的快取
     * @return null 代表沒有訊息、未登入或呼叫失敗；呼叫端應 fallback 顯示 "safe"/`--`
     */
    fun detectConversationRisk(
        context: Context,
        conversationKey: String,
        messages: List<CapturedNotification>,
        limit: Int = 15
    ): RagDetectResponse? {
        if (messages.isEmpty()) return null

        val fingerprint = "${messages.size}:${messages.maxOf { it.id }}"
        conversationCache[conversationKey]?.let { (cachedFingerprint, cachedResponse) ->
            if (cachedFingerprint == fingerprint) return cachedResponse
        }

        val token = TokenManager(context).accessToken
        if (token.isNullOrEmpty()) return null

        val text = buildConversationText(messages, limit)
        if (text.isBlank()) return null

        return try {
            val response = ApiClient.ragApi.detect("Bearer $token", RagDetectRequest(text)).execute()
            if (response.isSuccessful) {
                response.body()?.also { conversationCache[conversationKey] = fingerprint to it }
            } else {
                Log.w(TAG, "conversation detect failed: HTTP ${response.code()}")
                null
            }
        } catch (e: Exception) {
            Log.e(TAG, "conversation detect failed", e)
            null
        }
    }

    /**
     * 即時查詢單一則訊息的完整 AI 判斷（風險等級、詐騙類型、完整理由、建議），
     * 給「點單則訊息看詳細分析」功能用。故意不快取、不寫 DB——[detectAndCache] 已經
     * 把每則訊息的風險等級/詐騙類型/第一條理由快取起來給列表卡片用，但完整的
     * reasons 清單與 advice 建議沒有存，這裡每次點擊都直接重新問一次拿完整版本。
     *
     * @return null 代表未登入、內容為空或呼叫失敗
     */
    fun detectLive(context: Context, content: String): RagDetectResponse? {
        if (content.isBlank()) return null
        val token = TokenManager(context).accessToken
        if (token.isNullOrEmpty()) return null

        return try {
            val response = ApiClient.ragApi.detect("Bearer $token", RagDetectRequest(content)).execute()
            if (response.isSuccessful) {
                response.body()
            } else {
                Log.w(TAG, "single message detect failed: HTTP ${response.code()}")
                null
            }
        } catch (e: Exception) {
            Log.e(TAG, "single message detect failed", e)
            null
        }
    }

    /**
     * 把 /rag/detect 的 risk_level（三段式）＋ confidence（信心值 0-1）換算成 0-100 的
     * 「近期對話風險評分」，只給沒有真實可疑帳號分數時的對話詳情頁當備援顯示用。
     *
     * 設計原則：risk_level 決定落在哪個區間（區間之間不重疊），confidence 只在區間內部
     * 微調位置——不能直接拿 confidence 當分數，因為 confidence 代表「AI 對判斷有多確定」，
     * 不是「危險程度」：實測過一則正常的帳單通知 risk_level=safe 但 confidence 高達 0.72，
     * 比好幾則 risk_level=mid 的詐騙訊息信心值都高，直接用信心值當分數會讓安全訊息
     * 分數更高，順序整個顛倒。
     *
     * - safe：0-33 分，(1-confidence)×33 —— AI 越確定安全，分數越接近 0
     * - mid：34-66 分，34 + confidence×33
     * - high：67-100 分，67 + confidence×33 —— AI 越確定是詐騙，分數越接近 100
     */
    fun computeMessageRiskScore(riskLevel: String, confidence: Double): Int {
        val c = confidence.coerceIn(0.0, 1.0)
        val score = when (riskLevel) {
            "high" -> 67 + c * 33
            "mid" -> 34 + c * 33
            else -> (1 - c) * 33
        }
        return score.toInt().coerceIn(0, 100)
    }
}
