package com.frauddetector.service

import android.content.Context
import java.io.File

/** Stores the user's preferred fraud-detection route. */
object DetectionModePreferences {
    private const val PREFS_NAME = "detection_mode"
    private const val KEY_MODE = "selected_mode"
    // Set to true only when the JNI inference runtime is packaged and used by RagDetector.
    private const val LOCAL_INFERENCE_ENABLED = false
    const val LOCAL_MODEL_FILE_NAME = "flash-v4.1.gguf"

    enum class Mode { CLOUD, LOCAL }

    fun selectedMode(context: Context): Mode = when (
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .getString(KEY_MODE, Mode.CLOUD.name)
    ) {
        Mode.LOCAL.name -> Mode.LOCAL
        else -> Mode.CLOUD
    }

    fun selectMode(context: Context, mode: Mode) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_MODE, mode.name)
            .apply()
    }

    /** The private download flow will place the model here rather than in the APK. */
    fun localModelFile(context: Context): File =
        File(File(context.noBackupFilesDir, "models"), LOCAL_MODEL_FILE_NAME)

    /** A local mode must never be presented as ready before a readable model is present. */
    fun isLocalModeReady(context: Context): Boolean =
        LOCAL_INFERENCE_ENABLED && localModelFile(context).isFile && localModelFile(context).canRead()
}
