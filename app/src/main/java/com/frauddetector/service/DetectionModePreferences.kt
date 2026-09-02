package com.frauddetector.service

import android.content.Context
import java.io.File

/** Stores the user's preferred fraud-detection route. */
object DetectionModePreferences {
    private const val PREFS_NAME = "detection_mode"
    private const val KEY_MODE = "selected_mode"
    private const val KEY_MODEL_FILE_NAME = "local_model_file_name"
    private const val KEY_MODEL_VERSION = "local_model_version"

    /** 後端還沒給 manifest 之前的預設檔名（AI 隊友交付的 flash-v4.1.gguf）。 */
    const val LOCAL_MODEL_FILE_NAME = "flash-v4.1.gguf"

    enum class Mode { CLOUD, LOCAL }

    private fun prefs(context: Context) =
        context.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    fun selectedMode(context: Context): Mode = when (prefs(context).getString(KEY_MODE, Mode.CLOUD.name)) {
        Mode.LOCAL.name -> Mode.LOCAL
        else -> Mode.CLOUD
    }

    fun selectMode(context: Context, mode: Mode) {
        prefs(context).edit().putString(KEY_MODE, mode.name).apply()
    }

    /** 模型與下載暫存檔放的目錄（App 私有、不進雲端備份）。 */
    fun modelsDir(context: Context): File =
        File(context.applicationContext.noBackupFilesDir, "models")

    /**
     * The private download flow places the model here rather than in the APK.
     *
     * 檔名以 manifest 實際給的為準（[rememberDownloadedModel]），後端換版換檔名時
     * 不必改 App；還沒下載過就沿用 [LOCAL_MODEL_FILE_NAME]。
     */
    fun localModelFile(context: Context): File =
        File(modelsDir(context), prefs(context).getString(KEY_MODEL_FILE_NAME, LOCAL_MODEL_FILE_NAME) ?: LOCAL_MODEL_FILE_NAME)

    /** 已下載完成並通過 SHA-256 驗證的模型版本（沒有就是 null）。 */
    fun localModelVersion(context: Context): String? = prefs(context).getString(KEY_MODEL_VERSION, null)

    /** 下載完成且校驗通過後呼叫，記住這次拿到的檔名與版本。 */
    fun rememberDownloadedModel(context: Context, fileName: String, version: String) {
        prefs(context).edit()
            .putString(KEY_MODEL_FILE_NAME, fileName)
            .putString(KEY_MODEL_VERSION, version)
            .apply()
    }

    /**
     * 刪除已下載的模型（含未完成的續傳暫存檔）並回到雲端模式——地端模式沒有模型
     * 就完全無法判斷，留在地端模式等於什麼都不判，比退回雲端更危險。
     */
    fun deleteLocalModel(context: Context) {
        modelsDir(context).listFiles()?.forEach { it.delete() }
        prefs(context).edit()
            .remove(KEY_MODEL_FILE_NAME)
            .remove(KEY_MODEL_VERSION)
            .apply()
        selectMode(context, Mode.CLOUD)
    }

    /** A local mode must never be presented as ready before a readable model is present. */
    fun isLocalModeReady(context: Context): Boolean =
        LocalModelDetector.isAvailable(context)
}
