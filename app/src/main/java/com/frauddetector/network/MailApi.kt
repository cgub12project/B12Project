/**
 * MailApi.kt — Gmail/Outlook 信箱連接 API 介面定義
 *
 * 所屬模組：network（網路層）
 *
 * 使用方式：透過 [ApiClient.mailApi] 取得此介面的實例。
 */
package com.frauddetector.network

import retrofit2.Call
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

interface MailApi {

    /** 取得信箱授權網址，App 用瀏覽器／Custom Tab 開啟。 */
    @GET("api/v1/mail/connect/{provider}")
    fun connectMailbox(
        @Header("Authorization") token: String,
        @Path("provider") provider: String
    ): Call<MailConnectResponse>

    /** 查詢目前使用者已連接的信箱清單。 */
    @GET("api/v1/mail/accounts")
    fun listMailAccounts(
        @Header("Authorization") token: String
    ): Call<MailAccountsResponse>

    /** 中斷某個信箱的連接（連同判定紀錄一併刪除）。 */
    @DELETE("api/v1/mail/accounts/{account_id}")
    fun disconnectMailAccount(
        @Header("Authorization") token: String,
        @Path("account_id") accountId: Int
    ): Call<MailDisconnectResponse>

    /** 立即同步已連接的信箱：抓新信並逐封做 AI 判斷。可能需要數十秒才回應。 */
    @POST("api/v1/mail/sync")
    fun syncMailboxes(
        @Header("Authorization") token: String
    ): Call<MailSyncResponse>

    /** 查詢已完成 AI 判斷的信件列表（依收信時間新到舊）。 */
    @GET("api/v1/mail/messages")
    fun listMailMessages(
        @Header("Authorization") token: String,
        @Query("risk_level") riskLevel: String? = null,
        @Query("include_preview") includePreview: Boolean = true,
        @Query("limit") limit: Int = 20,
        @Query("offset") offset: Int = 0
    ): Call<MailMessagesResponse>

    /** 真封鎖：在這個已連接信箱的 Gmail 端建立過濾規則，之後這個寄件人的信不會再進收件匣。 */
    @POST("api/v1/mail/accounts/{account_id}/block-sender")
    fun blockSender(
        @Header("Authorization") token: String,
        @Path("account_id") accountId: Int,
        @Body body: MailBlockSenderRequest
    ): Call<MailBlockSenderResponse>

    /** 查詢這個已連接信箱目前真封鎖了哪些寄件人。 */
    @GET("api/v1/mail/accounts/{account_id}/blocked-senders")
    fun getBlockedSenders(
        @Header("Authorization") token: String,
        @Path("account_id") accountId: Int
    ): Call<MailBlockedSendersResponse>

    /** 解除真封鎖。 */
    @DELETE("api/v1/mail/accounts/{account_id}/blocked-senders/{sender}")
    fun unblockSender(
        @Header("Authorization") token: String,
        @Path("account_id") accountId: Int,
        @Path("sender") sender: String
    ): Call<MailBlockSenderResponse>

    /**
     * 已連接信箱真實郵件的完整內容——後端明確表示這支是設計給「回報詐騙郵件」用的
     * （見 [MailMessageContent.reportText] 已經幫忙組好回報用的格式化文字），
     * 一般查看完整信件走「開啟原信」深連結到 Gmail 網頁版即可，不需要呼叫這支。
     */
    @GET("api/v1/mail/messages/{analysis_id}/content")
    fun getMailMessageContent(
        @Header("Authorization") token: String,
        @Path("analysis_id") analysisId: Int
    ): Call<MailMessageContent>
}
