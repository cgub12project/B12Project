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

    /**
     * 偵測整段對話：風險判斷 + 目前演進到哪個詐騙階段
     * （接觸建立／培養信任／鋪陳誘餌／索取財物／收尾拖延）。
     *
     * 後端不儲存任何對話內容，上次的階段要由 App 自己保存後放進
     * [RagDetectConversationRequest.previousStage] 回傳，階段才不會因為舊訊息滑出
     * 視窗而倒退。
     *
     * @param token JWT 存取權杖，格式為 "Bearer {access_token}"
     * @param body [RagDetectConversationRequest] 由舊到新排列的對話訊息 + 上次階段
     */
    @POST("api/v1/rag/detect-conversation")
    fun detectConversation(
        @Header("Authorization") token: String,
        @Body body: RagDetectConversationRequest
    ): Call<RagDetectConversationResponse>
}
