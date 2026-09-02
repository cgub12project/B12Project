/**
 * LocalModelDownloader.kt — 地端模型的私有下載器
 *
 * 所屬模組：service（背景服務／領域邏輯）
 *
 * 對應後端 2026-09-02 上線的兩支端點（契約見 dev-notes/後端協助_地端模型私有下載部署需求.txt）：
 * - GET /api/v1/local-model/manifest：帶 Bearer Token 換取版本、大小、SHA-256 與短效簽章網址
 * - 簽章網址本身：支援 HTTP Range 續傳的模型檔下載入口
 *
 * 全部方法都是同步的，必須在背景執行緒呼叫。
 */
package com.frauddetector.service

import android.content.Context
import android.util.Log
import com.frauddetector.network.ApiClient
import com.frauddetector.network.LocalModelManifest
import com.frauddetector.network.TokenManager
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.io.RandomAccessFile
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

object LocalModelDownloader {
    private const val TAG = "LocalModelDownloader"

    /** 續傳暫存檔的副檔名：下載中的檔案永遠帶著它，校驗通過才改名成正式檔名。 */
    private const val PART_SUFFIX = ".part"

    private const val BUFFER_SIZE = 256 * 1024

    /**
     * 連續幾次「完全沒有前進」就放棄。
     *
     * 只要有下載到東西就把計數歸零：1.93 GB 在行動網路上本來就會斷好幾次，
     * 每斷一次就把使用者丟回失敗對話框等於下載不完。
     */
    private const val MAX_STALLED_ATTEMPTS = 5

    /** 連線總次數上限，避免伺服器每次只吐幾個 byte 時無限重連。 */
    private const val MAX_ATTEMPTS = 100

    /** 下載階段，給 UI 顯示「下載中」「重新連線中」「驗證中」三種等待狀態。 */
    enum class Phase { DOWNLOADING, RECONNECTING, VERIFYING }

    sealed class Outcome {
        /** 下載完成、SHA-256 核對通過、已改名成正式檔案。 */
        object Success : Outcome()

        /** 使用者中途取消——已下載的部分保留著，下次可以續傳。 */
        object Cancelled : Outcome()

        data class Failure(val message: String) : Outcome()
    }

    /** [fetchManifest] 的結果：拿到 manifest，或一則已中文化的失敗訊息。 */
    sealed class ManifestResult {
        data class Loaded(val manifest: LocalModelManifest) : ManifestResult()
        data class Failed(val message: String) : ManifestResult()
    }

    /**
     * 模型檔專用的 OkHttp 客戶端。
     *
     * 刻意不共用 [ApiClient] 的客戶端：那邊掛著 BODY 等級的 HttpLoggingInterceptor，
     * 1.93 GB 的回應會被整包讀進記憶體寫進 logcat；也不需要 TokenAuthenticator，
     * 簽章網址的授權在 URL 裡，不是 Authorization 標頭。
     */
    private val downloadClient: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .writeTimeout(60, TimeUnit.SECONDS)
            .retryOnConnectionFailure(true)
            .build()
    }

    /**
     * 取得模型 manifest（版本、大小、SHA-256、短效簽章網址）。
     *
     * 後端回 503 代表模型檔還沒部署上去——實測 2026-09-02 就是這個狀態，端點都在、
     * 只是還沒設定 LOCAL_MODEL_PATH，所以這裡把它翻成使用者看得懂的訊息，不是當成錯誤。
     */
    fun fetchManifest(context: Context): ManifestResult {
        val token = TokenManager(context).accessToken
        if (token.isNullOrEmpty()) return ManifestResult.Failed("請先登入後再下載地端模型")

        return try {
            val response = ApiClient.localModelApi.manifest("Bearer $token").execute()
            val body = response.body()
            when {
                response.isSuccessful && body != null -> ManifestResult.Loaded(body)
                response.code() == 503 -> ManifestResult.Failed("後端尚未部署地端模型檔，請稍後再試")
                else -> ManifestResult.Failed(ApiClient.parseError(response.errorBody()?.string()))
            }
        } catch (e: Exception) {
            Log.e(TAG, "fetch manifest failed", e)
            ManifestResult.Failed("無法連線到後端，請確認網路後再試")
        }
    }

    /** 這個 manifest 對應的模型已經下載了多少 bytes（沒下載過就是 0）。 */
    fun downloadedBytes(context: Context, manifest: LocalModelManifest): Long =
        partFile(context, manifest).let { if (it.exists()) it.length() else 0L }

    /**
     * 下載模型檔：支援中斷續傳（HTTP Range）、取消，以及下載完成後的 SHA-256 校驗。
     *
     * 校驗沒過不會留下正式檔案（暫存檔一併刪除重來）——地端模式的判斷完全依賴這個檔案，
     * 載入到一個壞掉或被掉包的模型比沒有模型更糟。
     *
     * @param onProgress 進度回報（階段、已完成 bytes、總 bytes），在背景執行緒呼叫
     * @param isCancelled 每個緩衝區寫完都會問一次，回 true 就停下來（已下載的部分保留）
     */
    fun download(
        context: Context,
        manifest: LocalModelManifest,
        onProgress: (Phase, Long, Long) -> Unit,
        isCancelled: () -> Boolean
    ): Outcome {
        val partFile = partFile(context, manifest)
        partFile.parentFile?.mkdirs()

        var current = manifest
        var refreshedSignature = false
        // 連續沒有進度的次數，以及最後一次的中斷原因（真的放棄時要顯示給使用者）
        var stalledAttempts = 0
        var attempts = 0
        var lastError: String? = null

        while (true) {
            if (isCancelled()) return Outcome.Cancelled
            if (attempts++ >= MAX_ATTEMPTS) {
                return Outcome.Failure(lastError ?: "下載重試次數過多，請稍後再試")
            }

            // 舊版模型留下的暫存檔比這次要下載的還大，續傳只會拼出壞檔案，直接重來
            if (partFile.exists() && partFile.length() > current.sizeBytes) partFile.delete()

            val startAt = if (partFile.exists()) partFile.length() else 0L
            if (startAt == current.sizeBytes) break

            val request = Request.Builder()
                .url(current.downloadUrl)
                .apply { if (startAt > 0) header("Range", "bytes=$startAt-") }
                .build()

            var authExpired = false
            try {
                downloadClient.newCall(request).execute().use { response ->
                    if (response.code == 401 || response.code == 403) {
                        authExpired = true
                        return@use
                    }
                    if (!response.isSuccessful) {
                        return Outcome.Failure("下載失敗（HTTP ${response.code}）")
                    }

                    // 伺服器不接受 Range 時會回 200 並從頭給整個檔案，這時必須從 0 覆寫，
                    // 否則會把整份檔案接在已下載的資料後面，拼出一個壞掉的模型。
                    val appendMode = response.code == 206 && startAt > 0
                    val bodyStream = response.body?.byteStream()
                        ?: return Outcome.Failure("下載失敗：伺服器沒有回傳內容")

                    RandomAccessFile(partFile, "rw").use { output ->
                        var written = if (appendMode) startAt else 0L
                        if (!appendMode) output.setLength(0)
                        output.seek(written)
                        val buffer = ByteArray(BUFFER_SIZE)
                        var lastReport = written
                        onProgress(Phase.DOWNLOADING, written, current.sizeBytes)
                        while (true) {
                            if (isCancelled()) {
                                output.fd.sync()
                                return Outcome.Cancelled
                            }
                            val read = bodyStream.read(buffer)
                            if (read <= 0) break
                            output.write(buffer, 0, read)
                            written += read
                            // 每 4 MB 回報一次就夠——每個緩衝區都回報會讓 UI 執行緒被進度
                            // 更新塞滿（1.93 GB / 256 KB 約 7900 次）
                            if (written - lastReport >= 4L * 1024 * 1024) {
                                lastReport = written
                                onProgress(Phase.DOWNLOADING, written, current.sizeBytes)
                            }
                        }
                        output.fd.sync()
                        onProgress(Phase.DOWNLOADING, written, current.sizeBytes)
                    }
                }
            } catch (e: Exception) {
                // 不直接收掉：連線斷在半路是 1.93 GB 下載的常態，記下原因後回到迴圈用
                // Range 從斷點續傳，真的連續幾次都沒進度才放棄。
                Log.w(TAG, "model download interrupted, will retry", e)
                lastError = "下載中斷：${describeError(e)}。已下載的部分會保留，可以再按一次繼續。"
            }

            if (authExpired) {
                // 簽章過期（預設 24 小時）：換一組新的再續傳，已下載的部分不必重來
                if (refreshedSignature) return Outcome.Failure("下載授權已失效，請重新登入後再試")
                refreshedSignature = true
                when (val refreshed = fetchManifest(context)) {
                    is ManifestResult.Failed -> return Outcome.Failure(refreshed.message)
                    is ManifestResult.Loaded -> {
                        // 後端在下載途中換了模型版本，舊的續傳資料不能用
                        if (!refreshed.manifest.sha256.equals(current.sha256, ignoreCase = true)) {
                            partFile.delete()
                        }
                        current = refreshed.manifest
                    }
                }
                continue
            }

            // 這一輪結束（正常收尾或中途斷線）但檔案還沒滿：回到迴圈用 Range 續傳。
            if (partFile.length() >= current.sizeBytes) break
            if (partFile.length() > startAt) {
                stalledAttempts = 0
            } else {
                // 一個 byte 都沒前進，再重試也可能只是原地空轉，給幾次機會就收掉
                stalledAttempts++
                if (stalledAttempts >= MAX_STALLED_ATTEMPTS) {
                    return Outcome.Failure(lastError ?: "下載沒有進度，請確認網路後重試")
                }
            }

            onProgress(Phase.RECONNECTING, partFile.length(), current.sizeBytes)
            // 退避等待：連續失敗時拉長間隔，免得沒訊號時瘋狂重連把電吃光
            val backoffMs = 2000L shl minOf(stalledAttempts, 3)
            if (!waitBeforeRetry(backoffMs, isCancelled)) return Outcome.Cancelled
        }

        if (partFile.length() != current.sizeBytes) {
            return Outcome.Failure("下載結果大小不符（${partFile.length()} / ${current.sizeBytes} bytes），請重試")
        }

        onProgress(Phase.VERIFYING, current.sizeBytes, current.sizeBytes)
        val digest = sha256Of(partFile, isCancelled) ?: return Outcome.Cancelled
        if (!digest.equals(current.sha256, ignoreCase = true)) {
            partFile.delete()
            return Outcome.Failure("模型檔校驗失敗（SHA-256 不符），已刪除，請重新下載")
        }

        val target = File(DetectionModePreferences.modelsDir(context), current.fileName)
        if (target.exists()) target.delete()
        if (!partFile.renameTo(target)) {
            return Outcome.Failure("模型檔搬移失敗，請確認手機儲存空間")
        }
        DetectionModePreferences.rememberDownloadedModel(context, current.fileName, current.version)
        return Outcome.Success
    }

    /** 把常見的網路例外翻成使用者看得懂的中文（原本會直接把 "timeout" 印出來）。 */
    private fun describeError(e: Exception): String = when (e) {
        is java.net.SocketTimeoutException -> "連線逾時"
        is java.net.UnknownHostException -> "找不到伺服器"
        is javax.net.ssl.SSLException -> "連線加密失敗"
        else -> e.message ?: "網路錯誤"
    }

    /** 等待重試，期間仍然可以取消。@return false 代表使用者按了取消。 */
    private fun waitBeforeRetry(millis: Long, isCancelled: () -> Boolean): Boolean {
        val deadline = System.currentTimeMillis() + millis
        while (System.currentTimeMillis() < deadline) {
            if (isCancelled()) return false
            Thread.sleep(200)
        }
        return !isCancelled()
    }

    private fun partFile(context: Context, manifest: LocalModelManifest): File =
        File(DetectionModePreferences.modelsDir(context), manifest.fileName + PART_SUFFIX)

    /** @return 十六進位小寫的 SHA-256；使用者在校驗途中取消則回 null。 */
    private fun sha256Of(file: File, isCancelled: () -> Boolean): String? {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(BUFFER_SIZE)
            while (true) {
                if (isCancelled()) return null
                val read = input.read(buffer)
                if (read <= 0) break
                digest.update(buffer, 0, read)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }
}
