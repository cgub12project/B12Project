package com.frauddetector.ui

import android.content.Context
import android.content.res.Configuration
import androidx.appcompat.app.AppCompatActivity
import com.frauddetector.service.FontScaleManager

/**
 * 所有 Activity 的共用基底類別，統一套用使用者在設定頁選擇的文字放大倍率。
 *
 * 透過 [attachBaseContext] 覆寫 [Configuration.fontScale]，讓全 App（含所有以 sp
 * 定義的 textSize）依同一倍率縮放。已經開著的舊 Activity 不會即時變化，使用者在
 * 設定頁切換倍率後會呼叫 recreate() 讓當前畫面立即套用，其餘畫面下次開啟時生效。
 */
abstract class BaseActivity : AppCompatActivity() {

    override fun attachBaseContext(newBase: Context) {
        val scale = FontScaleManager.getScale(newBase)
        val config = Configuration(newBase.resources.configuration)
        config.fontScale = scale
        super.attachBaseContext(newBase.createConfigurationContext(config))
    }
}
