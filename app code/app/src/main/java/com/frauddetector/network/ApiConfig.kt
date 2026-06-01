package com.frauddetector.network

/**
 * API 設定。
 *
 * BASE_URL 目前指向 Cloudflare Tunnel（臨時網址，每次隧道重啟會變更）。
 * 正式上線後請替換為固定的後端伺服器位址。
 */
object ApiConfig {
    const val BASE_URL = "https://surge-supposed-jaguar-arrangement.trycloudflare.com/"
//      const val BASE_URL = "https://llltrycloudflare.com/"

}
