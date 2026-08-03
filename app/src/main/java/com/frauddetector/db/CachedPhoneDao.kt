package com.frauddetector.db

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction

@Dao
interface CachedPhoneDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    fun insertAll(records: List<CachedPhone>)

    @Query("DELETE FROM cached_phones")
    fun clearAll()

    /** 用最新一批查詢結果整批取代快取內容，避免殘留伺服器端已移除／已改變的舊號碼 */
    @Transaction
    fun replaceAll(records: List<CachedPhone>) {
        clearAll()
        insertAll(records)
    }

    @Query("SELECT * FROM cached_phones ORDER BY lastReportedAt DESC")
    fun getAll(): List<CachedPhone>

    @Query("SELECT MAX(cachedAt) FROM cached_phones")
    fun getLastSyncTime(): Long?
}
