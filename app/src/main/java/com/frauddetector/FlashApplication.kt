package com.frauddetector

import android.app.Application
import com.frauddetector.network.ApiClient

class FlashApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        ApiClient.init(this)
    }
}
