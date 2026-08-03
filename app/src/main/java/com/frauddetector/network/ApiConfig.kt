/**
 * ApiConfig.kt — API 連線設定檔
 *
 * 所屬模組：network（網路層）
 *
 * 本檔案集中管理後端 API 的連線設定常數，
 * 包括基礎網址（BASE_URL）等環境相關的組態。
 * 當部署環境變更時（如從測試環境切換到正式環境），
 * 只需修改此檔案即可，無需變動其他網路層程式碼。
 */
package com.frauddetector.network

/**
 * API 設定 — 集中管理後端服務的連線參數。
 *
 * BASE_URL 目前指向 Cloudflare Tunnel（臨時網址，每次隧道重啟會變更）。
 * 正式上線後請替換為固定的後端伺服器位址。
 */
object ApiConfig {
    /**
     * 後端 API 的基礎網址。
     *
     * 目前使用 Cloudflare Tunnel 產生的臨時網址進行開發測試。
     * 注意事項：
     * - 此網址在每次 Cloudflare Tunnel 重啟後會變更，需手動更新
     * - 正式上線後應替換為固定的生產環境網址（例如 https://api.flash-app.com/）
     * - 網址結尾必須包含斜線（/），否則 Retrofit 可能無法正確拼接路徑
     */
    const val BASE_URL = "https://innovative-promoted-backing-sam.trycloudflare.com/"

    // 備用網址（已停用）：
//      const val BASE_URL = "https://canal-introducing-upcoming-prompt.trycloudflare.com/"
//      const val BASE_URL = "https://essex-poem-opposite-inc.trycloudflare.com/"
//      const val BASE_URL = "https://paste-year-ships-fixtures.trycloudflare.com/"
//      const val BASE_URL = "https://surge-supposed-jaguar-arrangement.trycloudflare.com/"

}
