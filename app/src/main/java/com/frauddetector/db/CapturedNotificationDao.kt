package com.frauddetector.db

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query

@Dao
interface CapturedNotificationDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    fun insert(notification: CapturedNotification)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    fun insertAll(notifications: List<CapturedNotification>)

    /** 取得所有訊息類通知，按時間倒序 */
    @Query("SELECT * FROM captured_notifications WHERE type = 'message' ORDER BY timestamp DESC")
    fun getMessages(): List<CapturedNotification>

    /** 取得所有郵件類通知，按時間倒序 */
    @Query("SELECT * FROM captured_notifications WHERE type = 'email' ORDER BY timestamp DESC")
    fun getEmails(): List<CapturedNotification>

    /** 依 App 篩選訊息 */
    @Query("SELECT * FROM captured_notifications WHERE type = 'message' AND app = :appName ORDER BY timestamp DESC")
    fun getMessagesByApp(appName: String): List<CapturedNotification>

    /**
     * 取得每個「對話」的最新一筆訊息（用於分組顯示）。
     * 對話 key：groupName 非空時用 (app, groupName)（LINE 群組），否則用 (app, sender)（私訊）。
     * 以 timestamp（而非 id）判斷「最新」——SmsHelper 匯入簡訊是照 date DESC 讀取後依序 insert，
     * 同批次中較新的簡訊反而會拿到較小的 id，MAX(id) 會選錯（較舊）那一筆。
     * WHERE 子句額外比對 (groupName != '') 是否相同，避免「私訊聯絡人名稱剛好等於某個群組名」時
     * 誤把兩個不相關的對話合併成一筆。
     */
    @Query("""
        SELECT * FROM captured_notifications
        WHERE type = 'message' AND id IN (
            SELECT MAX(n.id) FROM captured_notifications n
            WHERE n.type = 'message'
              AND n.timestamp = (
                  SELECT MAX(m.timestamp) FROM captured_notifications m
                  WHERE m.type = 'message'
                    AND m.app = n.app
                    AND (m.groupName != '') = (n.groupName != '')
                    AND (CASE WHEN m.groupName != '' THEN m.groupName ELSE m.sender END)
                      = (CASE WHEN n.groupName != '' THEN n.groupName ELSE n.sender END)
              )
            GROUP BY n.app, (n.groupName != ''), CASE WHEN n.groupName != '' THEN n.groupName ELSE n.sender END
        )
        ORDER BY timestamp DESC
    """)
    fun getLatestMessagePerConversation(): List<CapturedNotification>

    /**
     * 取得每個 sender 的最新一筆郵件
     */
    @Query("""
        SELECT * FROM captured_notifications
        WHERE type = 'email' AND id IN (
            SELECT MAX(id) FROM captured_notifications
            WHERE type = 'email'
            GROUP BY app, sender
        )
        ORDER BY timestamp DESC
    """)
    fun getLatestEmailPerSender(): List<CapturedNotification>

    /** 取得指定 LINE 群組對話串的訊息數量（用於「N則訊息」顯示） */
    @Query("SELECT COUNT(*) FROM captured_notifications WHERE app = :app AND groupName = :groupName AND groupName != ''")
    fun getMessageCountByGroup(app: String, groupName: String): Int

    /** 取得指定私訊對話串的訊息數量（排除同名但屬於群組訊息的列） */
    @Query("SELECT COUNT(*) FROM captured_notifications WHERE app = :app AND sender = :sender AND groupName = ''")
    fun getMessageCountByPrivateSender(sender: String, app: String): Int

    /** 取得指定 LINE 群組對話串的所有訊息（點進群組對話用） */
    @Query("SELECT * FROM captured_notifications WHERE app = :app AND groupName = :groupName AND groupName != '' ORDER BY timestamp ASC")
    fun getMessagesByGroup(app: String, groupName: String): List<CapturedNotification>

    /** 取得指定私訊對話串的所有訊息（排除同 sender 但屬於群組訊息的列，避免誤併對話） */
    @Query("SELECT * FROM captured_notifications WHERE app = :app AND sender = :sender AND groupName = '' ORDER BY timestamp ASC")
    fun getMessagesByPrivateSender(sender: String, app: String): List<CapturedNotification>

    /** 刪除指定 LINE 群組對話串的所有本機擷取訊息（左滑刪除用） */
    @Query("DELETE FROM captured_notifications WHERE app = :app AND groupName = :groupName AND groupName != ''")
    fun deleteGroupConversation(app: String, groupName: String)

    /** 刪除指定私訊對話串的所有本機擷取訊息（左滑刪除用） */
    @Query("DELETE FROM captured_notifications WHERE app = :app AND sender = :sender AND groupName = ''")
    fun deletePrivateConversation(sender: String, app: String)

    /** 刪除指定寄件人的所有本機擷取郵件（左滑刪除用） */
    @Query("DELETE FROM captured_notifications WHERE type = 'email' AND app = :app AND sender = :sender")
    fun deleteEmailConversation(sender: String, app: String)

    /** 檢查是否已有簡訊歷史（避免重複匯入） */
    @Query("SELECT COUNT(*) FROM captured_notifications WHERE app = '簡訊' AND packageName = 'sms_history'")
    fun getSmsHistoryCount(): Int

    /** 檢查開發者測試資料是否已插入過，避免長按重複插入造成重複列 */
    @Query("SELECT COUNT(*) FROM captured_notifications WHERE app = 'LINE' AND sender = '陳大富' AND packageName = 'jp.naver.line.android' AND content LIKE '%投資顧問陳大富%'")
    fun getTestDataCount(): Int

    /** 寫入 AI 偵測結果快取（riskLevel/scamType/aiReason/confidence），避免重複呼叫 /rag/detect */
    @Query("UPDATE captured_notifications SET riskLevel = :riskLevel, scamType = :scamType, aiReason = :aiReason, confidence = :confidence WHERE id = :id")
    fun updateRisk(id: Long, riskLevel: String, scamType: String?, aiReason: String?, confidence: Double?)

    /** 依 id 取得單筆通知（偵測後重新讀取最新狀態用） */
    @Query("SELECT * FROM captured_notifications WHERE id = :id LIMIT 1")
    fun getById(id: Long): CapturedNotification?
}
