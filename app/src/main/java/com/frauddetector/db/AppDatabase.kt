package com.frauddetector.db

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase

@Database(entities = [CapturedNotification::class, CachedPhone::class], version = 5, exportSchema = false)
abstract class AppDatabase : RoomDatabase() {

    abstract fun capturedNotificationDao(): CapturedNotificationDao
    abstract fun cachedPhoneDao(): CachedPhoneDao

    companion object {
        @Volatile
        private var INSTANCE: AppDatabase? = null

        fun getInstance(context: Context): AppDatabase {
            return INSTANCE ?: synchronized(this) {
                INSTANCE ?: Room.databaseBuilder(
                    context.applicationContext,
                    AppDatabase::class.java,
                    "flash_app.db"
                ).fallbackToDestructiveMigration()
                 .build().also { INSTANCE = it }
            }
        }
    }
}
