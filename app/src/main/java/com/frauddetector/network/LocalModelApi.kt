/**
 * LocalModelApi.kt — 地端模型下載 API 介面定義
 *
 * 所屬模組：network（網路層）
 *
 * 使用方式：透過 [ApiClient.localModelApi] 取得此介面的實例。
 * 模型檔本體不走 Retrofit（1.93 GB 不能整包讀進記憶體），由
 * [com.frauddetector.service.LocalModelDownloader] 以 OkHttp 串流 + Range 續傳下載。
 */
package com.frauddetector.network

import retrofit2.Call
import retrofit2.http.GET
import retrofit2.http.Header

interface LocalModelApi {

    /**
     * 取得地端模型的版本資訊與短效簽章下載網址。
     *
     * @param token JWT 存取權杖，格式為 "Bearer {access_token}"
     * @return 200：[LocalModelManifest]；401 未登入；403 帳號停用；
     *   503 代表後端還沒把模型檔部署上去（實測 2026-09-02 仍是這個狀態）
     */
    @GET("api/v1/local-model/manifest")
    fun manifest(@Header("Authorization") token: String): Call<LocalModelManifest>
}
