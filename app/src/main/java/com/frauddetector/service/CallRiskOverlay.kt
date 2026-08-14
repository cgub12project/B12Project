package com.frauddetector.service

import android.content.Context
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.LayoutInflater
import android.view.View
import android.view.WindowManager
import android.widget.TextView
import com.frauddetector.R

/**
 * 來電響鈴時的風險標籤懸浮視窗 —— Whoscall 風格，只顯示提醒不自動擋接聽
 * （攔截決定完全交給 [CallBlockingService] 既有的封鎖名單邏輯，這裡只負責「顯示」）。
 *
 * 需要使用者手動授權 `SYSTEM_ALERT_WINDOW`（見 [PermissionHelper.canDrawOverlays]），
 * 沒授權時 [show] 直接 no-op；某些廠牌系統也可能拒絕加懸浮視窗（已知的 OEM 相容性風險，
 * 見 dev-notes/相關規劃），加視窗失敗時同樣靜默放棄，絕對不能讓這個提醒功能影響電話
 * 本身正常響鈴/接聽。
 */
object CallRiskOverlay {
    private const val AUTO_DISMISS_MS = 12_000L

    private var overlayView: View? = null
    private val mainHandler = Handler(Looper.getMainLooper())
    private var dismissRunnable: Runnable? = null

    /** 可以從任何執行緒呼叫（[CallBlockingService] 是在背景執行緒查完風險快取後呼叫這裡）。 */
    fun show(context: Context, phoneNumber: String, riskLevel: String, fraudType: String?) {
        if (!PermissionHelper.canDrawOverlays(context)) return
        val appCtx = context.applicationContext
        mainHandler.post { showInternal(appCtx, phoneNumber, riskLevel, fraudType) }
    }

    fun hide() {
        mainHandler.post { hideInternal() }
    }

    private fun showInternal(context: Context, phoneNumber: String, riskLevel: String, fraudType: String?) {
        hideInternal() // 先收掉前一個（理論上不會同時有兩通響鈴中的來電，保險起見還是先清）

        val windowManager = context.getSystemService(Context.WINDOW_SERVICE) as? WindowManager ?: return
        val view = LayoutInflater.from(context).inflate(R.layout.overlay_call_risk, null)
        val dp = context.resources.displayMetrics.density

        val (label, color) = when (riskLevel) {
            "high" -> "⚠ 高風險來電" to Color.parseColor("#A63D2F")
            "mid" -> "⚠ 可疑來電" to Color.parseColor("#C46B4A")
            else -> "來電提醒" to Color.parseColor("#7A9E7E")
        }

        val radius = 16f * dp
        view.background = GradientDrawable().apply {
            setColor(color)
            // 貼底部、只有上面兩角圓——實測系統原生的來電卡片會佔住螢幕最上方（大約來電響鈴
            // 1 秒後出現，蓋掉原本貼頂端的版面），貼底部比較不會被蓋住
            cornerRadii = floatArrayOf(radius, radius, radius, radius, 0f, 0f, 0f, 0f)
        }
        view.findViewById<TextView>(R.id.tvOverlayTitle).text = label
        view.findViewById<TextView>(R.id.tvOverlayNumber).text = phoneNumber
        view.findViewById<TextView>(R.id.tvOverlayFraudType).apply {
            if (!fraudType.isNullOrBlank()) {
                text = "社群回報類型：$fraudType"
                visibility = View.VISIBLE
            } else {
                visibility = View.GONE
            }
        }
        view.findViewById<View>(R.id.tvOverlayDismiss).setOnClickListener { hideInternal() }

        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.BOTTOM
            y = (24 * dp).toInt() // 留一點空間避開手勢列/導覽列，實機依裝置可能還要微調
        }

        try {
            windowManager.addView(view, params)
            overlayView = view
        } catch (e: Exception) {
            // 部分廠牌/系統狀態可能拒絕加懸浮視窗，靜默失敗，不影響電話本身正常響鈴
            return
        }

        val runnable = Runnable { hideInternal() }
        dismissRunnable = runnable
        mainHandler.postDelayed(runnable, AUTO_DISMISS_MS)
    }

    private fun hideInternal() {
        dismissRunnable?.let { mainHandler.removeCallbacks(it) }
        dismissRunnable = null
        val view = overlayView ?: return
        overlayView = null
        try {
            val windowManager = view.context.getSystemService(Context.WINDOW_SERVICE) as? WindowManager
            windowManager?.removeView(view)
        } catch (e: Exception) {
            // 視窗可能已經被系統移除（例如來電已結束），忽略
        }
    }
}
