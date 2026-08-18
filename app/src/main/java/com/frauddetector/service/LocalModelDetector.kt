package com.frauddetector.service

import android.content.Context
import android.os.Build
import android.util.Log
import com.frauddetector.network.ApiClient
import com.frauddetector.network.RagDetectResponse

/**
 * The on-device implementation of the privacy-first detection mode.
 *
 * The GGUF file is deliberately external to the APK and must be placed by the future verified
 * downloader at [DetectionModePreferences.localModelFile]. Native libraries only support arm64;
 * unsupported devices stay on the cloud route instead of failing at runtime.
 */
object LocalModelDetector {
    private const val TAG = "LocalModelDetector"
    private const val MODELFILE_ASSET = "flash-v4.1-modelfile.txt"
    private const val MAX_TOKENS = 96

    private val loadLock = Any()
    @Volatile private var librariesLoaded = false

    private data class LocalOutput(
        val scam_type: String? = null,
        val confidence_score: Double? = null,
    )

    fun isAvailable(context: Context): Boolean =
        Build.SUPPORTED_ABIS.any { it == "arm64-v8a" } &&
            DetectionModePreferences.localModelFile(context).canRead()

    fun detect(context: Context, content: String): RagDetectResponse? {
        if (content.isBlank() || !isAvailable(context)) return null

        return try {
            ensureLibrariesLoaded()
            val response = LocalModelNative.classify(
                DetectionModePreferences.localModelFile(context).absolutePath,
                formatChatPrompt(loadSystemPrompt(context), content),
                MAX_TOKENS,
            ) ?: return null
            mapResponse(response)
        } catch (error: Exception) {
            Log.e(TAG, "local detection failed", error)
            null
        }
    }

    private fun ensureLibrariesLoaded() {
        if (librariesLoaded) return
        synchronized(loadLock) {
            if (librariesLoaded) return
            System.loadLibrary("ggml-base")
            System.loadLibrary("ggml-cpu")
            System.loadLibrary("ggml")
            System.loadLibrary("llama")
            System.loadLibrary("flash_inference")
            librariesLoaded = true
        }
    }

    private fun loadSystemPrompt(context: Context): String =
        context.assets.open(MODELFILE_ASSET).bufferedReader(Charsets.UTF_8).use { reader ->
            val modelfile = reader.readText()
            modelfile.substringAfter("SYSTEM \"\"\"")
                .substringBefore("\"\"\"")
                .trim()
        }

    /** Qwen2's ChatML format, matching the template in the bundled Modelfile. */
    private fun formatChatPrompt(systemPrompt: String, message: String): String =
        "<|im_start|>system\n$systemPrompt<|im_end|>\n" +
            "<|im_start|>user\n$message<|im_end|>\n" +
            "<|im_start|>assistant\n"

    private fun mapResponse(raw: String): RagDetectResponse? {
        val json = raw.substringAfter('{', missingDelimiterValue = "")
            .substringBeforeLast('}', missingDelimiterValue = "")
            .takeIf { it.isNotBlank() }
            ?.let { "{$it}" }
            ?: return null
        val output = ApiClient.gson.fromJson(json, LocalOutput::class.java) ?: return null
        val scamType = output.scam_type?.trim()?.takeIf { it.isNotEmpty() } ?: return null
        val confidence = ((output.confidence_score ?: 0.0) / 100.0).coerceIn(0.0, 1.0)
        val isScam = scamType != "正常訊息"
        val riskLevel = when {
            !isScam -> "safe"
            confidence >= 0.8 -> "high"
            else -> "mid"
        }
        return RagDetectResponse(
            isScam = isScam,
            riskLevel = riskLevel,
            scamType = scamType,
            confidence = confidence,
            reasons = listOf("由手機本機模型判斷，內容未傳送至後端。"),
            advice = if (isScam) "請勿點擊連結、匯款或提供驗證碼。" else null,
            model = "flash-v4.1-local",
        )
    }
}

/** JNI surface implemented by native/flash_inference.cpp. */
internal object LocalModelNative {
    @JvmStatic
    external fun classify(modelPath: String, prompt: String, maxTokens: Int): String?
}
