/**
 * ApiClient.kt — Retrofit 網路客戶端單例
 *
 * 所屬模組：network（網路層）
 *
 * 本檔案以單例物件（object）的形式提供 Retrofit 網路客戶端，
 * 統一管理所有 API 介面的建立與設定。主要職責包括：
 * - 設定 OkHttp 客戶端（日誌攔截器、逾時時間）
 * - 建立 Retrofit 實例並綁定 base URL 與 JSON 轉換器
 * - 提供各 API 介面的懶載入存取點（[authApi]、[reportApi]）
 * - 提供統一的 API 錯誤訊息解析方法
 *
 * 日後若需加入 Token Interceptor（自動附加 Authorization header），
 * 可在 [okHttp] 的 Builder 中新增攔截器即可。
 */
package com.frauddetector.network

import android.content.Context
import com.google.gson.Gson
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

/**
 * Retrofit 單例。
 * 所有 API 介面透過此處取得。[init] 需在 [com.frauddetector.FlashApplication.onCreate] 呼叫一次，
 * 才能建立掛載了 [TokenAuthenticator] 的 OkHttp 客戶端（401 時自動用 refresh_token 換發新權杖）。
 */
object ApiClient {

    /** 全域 Gson 實例，供 JSON 序列化/反序列化使用 */
    val gson: Gson = Gson()

    private lateinit var appContext: Context

    fun init(context: Context) {
        appContext = context.applicationContext
    }

    /**
     * OkHttp 客戶端實例（懶載入）。
     *
     * 設定包括：
     * - [HttpLoggingInterceptor]：以 BODY 等級記錄完整的 HTTP 請求/回應內容，便於除錯
     * - [TokenAuthenticator]：401 時以 refresh_token 換發新 access_token 並自動重試
     * - 連線逾時（connectTimeout）：15 秒
     * - 讀取逾時（readTimeout）：15 秒
     * - 寫入逾時（writeTimeout）：15 秒
     */
    private val okHttp: OkHttpClient by lazy {
        // 建立日誌攔截器，設定為 BODY 等級以記錄完整請求/回應
        val logging = HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BODY
        }
        OkHttpClient.Builder()
            .addInterceptor(logging)          // 加入日誌攔截器
            .authenticator(TokenAuthenticator(appContext))  // 401 自動換發 Token
            .connectTimeout(15, TimeUnit.SECONDS)  // 連線逾時 15 秒
            .readTimeout(15, TimeUnit.SECONDS)     // 讀取逾時 15 秒
            .writeTimeout(15, TimeUnit.SECONDS)    // 寫入逾時 15 秒
            .build()
    }

    /**
     * Retrofit 實例（懶載入）。
     *
     * 使用 [ApiConfig.BASE_URL] 作為基礎網址，
     * 搭配 [okHttp] 客戶端與 Gson 轉換器處理 JSON 資料。
     */
    private val retrofit: Retrofit by lazy {
        Retrofit.Builder()
            .baseUrl(ApiConfig.BASE_URL)                        // 設定 API 基礎網址
            .client(okHttp)                                     // 綁定 OkHttp 客戶端
            .addConverterFactory(GsonConverterFactory.create(gson))  // 使用 Gson 進行 JSON 轉換
            .build()
    }

    /**
     * /rag/detect 專用的 OkHttp 客戶端（懶載入），讀取逾時拉長到 90 秒。
     *
     * 該端點在相似度落於中間地帶時會呼叫本地 LLM（Ollama）做綜合判斷，
     * 推論時間可能明顯超過一般 API 的 15 秒逾時，導致 [java.net.SocketTimeoutException]
     * 並讓該則訊息被誤判為安全（風險判斷被略過）。獨立拉長逾時，其餘端點維持原本 15 秒快速失敗。
     */
    private val ragOkHttp: OkHttpClient by lazy {
        okHttp.newBuilder()
            .readTimeout(90, TimeUnit.SECONDS)
            .writeTimeout(90, TimeUnit.SECONDS)
            .build()
    }

    private val ragRetrofit: Retrofit by lazy {
        retrofit.newBuilder()
            .client(ragOkHttp)
            .build()
    }

    /**
     * 電話清單查詢專用的 OkHttp 客戶端（懶載入），逾時縮短為 5 秒。
     *
     * 電話清單查詢失敗時會退回本機快取（見 [com.frauddetector.db.CachedPhoneDao]），
     * 縮短逾時能讓訊號不穩定（請求送出但遲遲無回應）時盡快切換到快取畫面，
     * 不必等滿一般 API 預設的 15 秒逾時才顯示備援資料。
     */
    private val phoneOkHttp: OkHttpClient by lazy {
        okHttp.newBuilder()
            .connectTimeout(5, TimeUnit.SECONDS)
            .readTimeout(5, TimeUnit.SECONDS)
            .writeTimeout(5, TimeUnit.SECONDS)
            .build()
    }

    private val phoneRetrofit: Retrofit by lazy {
        retrofit.newBuilder()
            .client(phoneOkHttp)
            .build()
    }

    /** 認證相關 API 介面（懶載入），提供登入、註冊、忘記密碼等端點 */
    val authApi: AuthApi by lazy { retrofit.create(AuthApi::class.java) }

    /** 舉報相關 API 介面（懶載入），提供電話號碼與帳號的舉報端點 */
    val reportApi: ReportApi by lazy { retrofit.create(ReportApi::class.java) }

    /** RAG 詐騙偵測 API 介面（懶載入，逾時較長，見 [ragOkHttp]） */
    val ragApi: RagApi by lazy { ragRetrofit.create(RagApi::class.java) }

    /** 可疑帳號查詢 API 介面（懶載入） */
    val accountApi: AccountApi by lazy { retrofit.create(AccountApi::class.java) }

    /** 電話號碼查詢 API 介面（懶載入，逾時縮短，見 [phoneOkHttp]） */
    val phoneApi: PhoneApi by lazy { phoneRetrofit.create(PhoneApi::class.java) }

    /** 使用者個人資料與設定 API 介面（懶載入） */
    val userApi: UserApi by lazy { retrofit.create(UserApi::class.java) }

    /**
     * 從 Retrofit errorBody 解析錯誤訊息。
     *
     * FastAPI 後端回傳的錯誤格式有兩種：
     * 1. 一般錯誤：`{"detail": "錯誤訊息字串"}`
     * 2. 驗證錯誤（HTTP 422）：`{"detail": [{"msg": "...", ...}, ...]}`
     *
     * 本方法會依序嘗試解析這兩種格式，並回傳可供 UI 顯示的中文錯誤訊息。
     *
     * @param errorBody Retrofit 回應的 errorBody 字串，可能為 null
     * @return 解析後的錯誤訊息文字；若無法解析則回傳預設的錯誤提示
     */
    fun parseError(errorBody: String?): String {
        // 若 errorBody 為空，直接回傳預設錯誤訊息
        if (errorBody.isNullOrBlank()) return "未知錯誤"
        return try {
            // 第一步：嘗試將 detail 欄位解析為字串（一般錯誤格式）
            val err = gson.fromJson(errorBody, ErrorDetail::class.java)
            err.detail ?: "未知錯誤"
        } catch (_: Exception) {
            // detail 是陣列的情況（422 validation error）
            try {
                // 第二步：將整個 JSON 解析為 Map，再處理 detail 欄位
                val map = gson.fromJson(errorBody, Map::class.java)
                val detail = map["detail"]
                if (detail is List<*>) {
                    // detail 為陣列時，提取每個驗證錯誤的 msg 欄位並以換行連接
                    detail.filterIsInstance<Map<*, *>>()
                        .joinToString("\n") { it["msg"]?.toString() ?: "" }
                        .ifBlank { "請求格式錯誤" }
                } else {
                    // detail 為其他型別時，直接轉為字串
                    detail?.toString() ?: "未知錯誤"
                }
            } catch (_: Exception) {
                // 所有解析都失敗時，回傳通用錯誤訊息
                "伺服器回傳錯誤"
            }
        }
    }
}
