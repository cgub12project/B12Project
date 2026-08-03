/**
 * RagApi.kt — RAG 詐騙偵測 API 介面定義
 *
 * 所屬模組：network（網路層）
 *
 * 使用方式：透過 [ApiClient.ragApi] 取得此介面的實例。
 */
package com.frauddetector.network

import retrofit2.Call
import retrofit2.http.Body
import retrofit2.http.Header
import retrofit2.http.POST

interface RagApi {

    /**
     * 偵測一則訊息是否為詐騙。
     *
     * @param token JWT 存取權杖，格式為 "Bearer {access_token}"
     * @param body [RagDetectRequest] 包含待偵測的訊息文字
     * @return [Call]<[RagDetectResponse]> 風險等級、判定理由、防詐建議與相似案例
     */
    @POST("api/v1/rag/detect")
    fun detect(
        @Header("Authorization") token: String,
        @Body body: RagDetectRequest
    ): Call<RagDetectResponse>
}
