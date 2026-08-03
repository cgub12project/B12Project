/**
 * SettingsFragment.kt — 設定頁籤
 *
 * 所屬模組：ui/main（主畫面模組）
 *
 * 本 Fragment 為底部導航「設定」頁籤，功能包含：
 * - 個人資料顯示（本地快取 + GET /api/v1/users/me 校正）
 * - 6 項設定開關：與後端 GET/PUT /api/v1/users/me/settings 雙向同步
 * - 更改密碼（POST /api/v1/auth/change-password）
 * - 快速登入（生物辨識，[QuickSetupDialog] 導引開啟）
 * - 登出（呼叫 POST /api/v1/auth/logout 後清除本地 Token）
 */
package com.frauddetector.ui.main

import android.content.Intent
import android.os.Bundle
import android.text.InputType
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.biometric.BiometricManager
import androidx.fragment.app.Fragment
import com.frauddetector.R
import com.frauddetector.db.AppDatabase
import com.frauddetector.db.CapturedNotification
import com.frauddetector.network.ApiClient
import com.frauddetector.network.ChangePasswordRequest
import com.frauddetector.network.MessageResponse
import com.frauddetector.network.TokenManager
import com.frauddetector.network.UserOut
import com.frauddetector.network.UserSettingsOut
import com.frauddetector.network.UserSettingsUpdateRequest
import com.frauddetector.service.FontScaleManager
import com.frauddetector.service.PermissionHelper
import com.frauddetector.ui.detail.BlockedNumbersActivity
import com.frauddetector.ui.detail.MyReportsActivity
import com.frauddetector.ui.detail.SuspectAccountsActivity
import com.frauddetector.ui.auth.LoginActivity
import com.frauddetector.ui.dialog.QuickSetupDialog
import com.google.android.material.switchmaterial.SwitchMaterial
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import java.util.concurrent.Executors

/**
 * 設定 Fragment，顯示個人資料與系統設定項目。
 */
class SettingsFragment : Fragment() {

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View? {
        return inflater.inflate(R.layout.fragment_settings, container, false)
    }

    private val executor = Executors.newSingleThreadExecutor()

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        setupProfile(view)
        setupSettingsItems(view)
        setupClickListeners(view)
        refreshProfileFromServer(view)
        loadSettingsToggles(view)

        // Debug: 長按個人資料卡片 → 插入測試資料 / 預覽群組對話串接格式
        view.findViewById<View>(R.id.profileCard).setOnLongClickListener {
            AlertDialog.Builder(requireContext())
                .setTitle("開發者選項")
                .setMessage("插入測試資料到訊息與郵件分頁？\n（現有資料不會被刪除）")
                .setPositiveButton("插入") { _, _ -> insertTestData() }
                .setNeutralButton("預覽群組串接格式") { _, _ -> previewConversationConcat() }
                .setNegativeButton("取消", null)
                .show()
            true
        }
    }

    /**
     * 【本機預覽用，不會呼叫 /rag/detect】把「投資理財交流群」的訊息用
     * [RagDetector.buildConversationText] 串接起來，直接顯示串接後的文字，
     * 用來先確認格式看起來合不合理，還沒真的送去問 AI。
     */
    private fun previewConversationConcat() {
        val ctx = context?.applicationContext ?: return
        executor.execute {
            val dao = AppDatabase.getInstance(ctx).capturedNotificationDao()
            val messages = dao.getMessagesByGroup("LINE", "投資理財交流群")
            val text = com.frauddetector.service.RagDetector.buildConversationText(messages)

            activity?.runOnUiThread {
                AlertDialog.Builder(requireContext())
                    .setTitle("串接後的文字（僅本機預覽，未送出）")
                    .setMessage(
                        if (text.isBlank())
                            "找不到「投資理財交流群」的訊息，請先按「插入」灌測試資料。"
                        else
                            text
                    )
                    .setPositiveButton("關閉", null)
                    .show()
            }
        }
    }

    /** 設定個人資料區塊：先用本地快取顯示（避免閃爍），稍後 [refreshProfileFromServer] 會校正 */
    private fun setupProfile(view: View) {
        val tokenManager = TokenManager(requireContext())
        val email = tokenManager.userEmail
        val name = tokenManager.userName

        val tvName = view.findViewById<TextView>(R.id.tvProfileName)
        val tvEmail = view.findViewById<TextView>(R.id.tvProfileEmail)

        if (!name.isNullOrBlank()) {
            tvName.text = name
            tvEmail.text = email ?: getString(R.string.verified_email)
        } else if (!email.isNullOrBlank()) {
            tvName.text = email
            tvEmail.text = getString(R.string.verified_email)
        } else {
            tvName.text = "未登入"
            tvEmail.text = ""
        }
    }

    /** 呼叫 GET /api/v1/users/me 取得權威個人資料，校正本地快取與畫面顯示 */
    private fun refreshProfileFromServer(view: View) {
        val token = TokenManager(requireContext()).accessToken ?: return
        ApiClient.userApi.getMe("Bearer $token").enqueue(object : Callback<UserOut> {
            override fun onResponse(call: Call<UserOut>, response: Response<UserOut>) {
                if (!isAdded) return
                val user = response.body() ?: return
                if (!response.isSuccessful) return
                TokenManager(requireContext()).saveUserInfo(user.email, user.name)
                view.findViewById<TextView>(R.id.tvProfileName).text = user.name.ifBlank { user.email }
                view.findViewById<TextView>(R.id.tvProfileEmail).text = user.email
            }

            override fun onFailure(call: Call<UserOut>, t: Throwable) {
                // 靜默失敗，維持本地快取顯示即可
            }
        })
    }

    /** 初始化 9 項設定項目的圖示、標題與副標題 */
    private fun setupSettingsItems(view: View) {
        setupItem(view, R.id.settingMsgMonitor, R.drawable.ic_msg_set,
            getString(R.string.msg_monitoring), getString(R.string.msg_monitoring_sub))
        setupItem(view, R.id.settingEmailScan, R.drawable.ic_email_set,
            getString(R.string.email_scan), getString(R.string.email_scan_sub))
        setupItem(view, R.id.settingCallerId, R.drawable.ic_phone_set,
            getString(R.string.caller_id), getString(R.string.caller_id_sub))
        setupItem(view, R.id.settingQuickLogin, R.drawable.ic_lock_set,
            getString(R.string.quick_login), getString(R.string.quick_login_sub))
        setupItem(view, R.id.settingHighRiskAlert, R.drawable.ic_bell_set,
            getString(R.string.high_risk_alert), getString(R.string.high_risk_alert_sub))
        setupItem(view, R.id.settingDailyReport, R.drawable.ic_calendar_set,
            getString(R.string.daily_report), getString(R.string.daily_report_sub))
        setupItem(view, R.id.settingChangePassword, R.drawable.ic_key_set,
            getString(R.string.change_password), getString(R.string.change_password_sub))
        setupItem(view, R.id.settingPrivacy, R.drawable.ic_shield_set,
            getString(R.string.privacy_data), getString(R.string.privacy_data_sub))
        setupItem(view, R.id.settingMyReports, R.drawable.ic_shield_set,
            "我的回報紀錄", "查看已提交的詐騙舉報")
        setupItem(view, R.id.settingSuspectAccounts, R.drawable.ic_shield_set,
            "可疑帳號列表", "查看社群回報的帳號威脅檔案")
        setupItem(view, R.id.settingBlockedNumbers, R.drawable.ic_phone_set,
            "封鎖名單", "查看並解除已封鎖的電話號碼")
        setupItem(view, R.id.settingFontSize, android.R.drawable.ic_menu_zoom,
            "文字大小", "目前：${FontScaleManager.currentLabel(requireContext())}")
        setupItem(view, R.id.settingLogout, R.drawable.ic_logout_set,
            getString(R.string.logout), getString(R.string.logout_sub))
    }

    private fun setupItem(view: View, itemId: Int, iconRes: Int, label: String, sub: String) {
        val item = view.findViewById<View>(itemId)
        item.findViewById<ImageView>(R.id.settingsIcon).setImageResource(iconRes)
        item.findViewById<TextView>(R.id.tvSettingsLabel).text = label
        item.findViewById<TextView>(R.id.tvSettingsSub).text = sub
    }

    /** 設定各設定項目的點擊事件（更改密碼、隱私、登出、快速登入） */
    private fun setupClickListeners(view: View) {
        view.findViewById<View>(R.id.settingChangePassword).setOnClickListener {
            showChangePasswordDialog()
        }

        view.findViewById<View>(R.id.settingPrivacy).setOnClickListener {
            Toast.makeText(requireContext(), getString(R.string.not_implemented), Toast.LENGTH_SHORT).show()
        }

        view.findViewById<View>(R.id.settingMyReports).setOnClickListener {
            startActivity(Intent(requireContext(), MyReportsActivity::class.java))
        }

        view.findViewById<View>(R.id.settingSuspectAccounts).setOnClickListener {
            startActivity(Intent(requireContext(), SuspectAccountsActivity::class.java))
        }

        view.findViewById<View>(R.id.settingBlockedNumbers).setOnClickListener {
            startActivity(Intent(requireContext(), BlockedNumbersActivity::class.java))
        }

        view.findViewById<View>(R.id.settingFontSize).setOnClickListener {
            showFontSizeDialog(view)
        }

        view.findViewById<View>(R.id.settingLogout).setOnClickListener {
            AlertDialog.Builder(requireContext())
                .setTitle("登出")
                .setMessage("確定要登出嗎？")
                .setPositiveButton("登出") { _, _ -> doLogout() }
                .setNegativeButton("取消", null)
                .show()
        }

        view.findViewById<View>(R.id.settingQuickLogin).setOnClickListener {
            QuickSetupDialog().show(parentFragmentManager, "quick_setup")
        }

        // 訊息即時監控 → 開啟通知存取權設定
        view.findViewById<View>(R.id.settingMsgMonitor).setOnClickListener {
            if (PermissionHelper.isNotificationListenerEnabled(requireContext())) {
                Toast.makeText(requireContext(), "通知監控已啟用", Toast.LENGTH_SHORT).show()
            } else {
                PermissionHelper.openNotificationListenerSettings(requireContext())
            }
        }

        // 郵件掃描 → 同樣透過通知存取權
        view.findViewById<View>(R.id.settingEmailScan).setOnClickListener {
            if (PermissionHelper.isNotificationListenerEnabled(requireContext())) {
                Toast.makeText(requireContext(), "郵件掃描已啟用（透過通知監控）", Toast.LENGTH_SHORT).show()
            } else {
                PermissionHelper.openNotificationListenerSettings(requireContext())
            }
        }

        // 來電辨識 → 提示需要通話紀錄權限
        view.findViewById<View>(R.id.settingCallerId).setOnClickListener {
            Toast.makeText(requireContext(), "來電辨識功能透過「電話」分頁的通話紀錄運作", Toast.LENGTH_SHORT).show()
        }
    }

    private fun doLogout() {
        val token = TokenManager(requireContext()).accessToken
        if (!token.isNullOrEmpty()) {
            // Best-effort：不等待回應即導航離開，避免網路延遲卡住登出流程
            ApiClient.authApi.logout("Bearer $token").enqueue(object : Callback<MessageResponse> {
                override fun onResponse(call: Call<MessageResponse>, response: Response<MessageResponse>) {}
                override fun onFailure(call: Call<MessageResponse>, t: Throwable) {}
            })
        }
        TokenManager(requireContext()).clear()
        val intent = Intent(requireContext(), LoginActivity::class.java)
        intent.flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
        startActivity(intent)
    }

    /**
     * 文字大小：單選對話框，選項對應 [FontScaleManager.OPTIONS]。
     * 選定後寫入 SharedPreferences 並呼叫 recreate() 讓當前畫面立即套用新倍率
     * （[com.frauddetector.ui.BaseActivity] 會在下次 attachBaseContext 時讀取新值）。
     */
    private fun showFontSizeDialog(view: View) {
        val ctx = requireContext()
        val options = FontScaleManager.OPTIONS
        val labels = options.map { it.first }.toTypedArray()
        val currentIndex = options.indexOfFirst { it.second == FontScaleManager.getScale(ctx) }
            .let { if (it == -1) 1 else it } // 找不到就預設「標準」

        AlertDialog.Builder(ctx)
            .setTitle("文字大小")
            .setSingleChoiceItems(labels, currentIndex) { dialog, which ->
                FontScaleManager.setScale(ctx, options[which].second)
                setupItem(view, R.id.settingFontSize, android.R.drawable.ic_menu_zoom,
                    "文字大小", "目前：${options[which].first}")
                dialog.dismiss()
                activity?.recreate()
            }
            .setNegativeButton("取消", null)
            .show()
    }

    /** 更改密碼：簡易對話框輸入舊密碼／新密碼，呼叫 POST /api/v1/auth/change-password */
    private fun showChangePasswordDialog() {
        val context = requireContext()
        val dp = resources.displayMetrics.density
        val pad = (20 * dp).toInt()

        val etOld = EditText(context).apply {
            hint = "目前密碼"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        }
        val etNew = EditText(context).apply {
            hint = "新密碼（至少 8 碼）"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        }
        val container = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad / 2, pad, 0)
            addView(etOld)
            addView(etNew)
        }

        AlertDialog.Builder(context)
            .setTitle(getString(R.string.change_password))
            .setView(container)
            .setPositiveButton("確定") { _, _ ->
                val oldPw = etOld.text.toString()
                val newPw = etNew.text.toString()
                if (oldPw.isEmpty() || newPw.length < 8) {
                    Toast.makeText(context, "請填寫完整，新密碼至少 8 碼", Toast.LENGTH_SHORT).show()
                    return@setPositiveButton
                }
                submitChangePassword(oldPw, newPw)
            }
            .setNegativeButton("取消", null)
            .show()
    }

    private fun submitChangePassword(oldPw: String, newPw: String) {
        val token = TokenManager(requireContext()).accessToken
        if (token.isNullOrEmpty()) return

        ApiClient.authApi.changePassword("Bearer $token", ChangePasswordRequest(oldPw, newPw))
            .enqueue(object : Callback<MessageResponse> {
                override fun onResponse(call: Call<MessageResponse>, response: Response<MessageResponse>) {
                    if (!isAdded) return
                    if (response.isSuccessful) {
                        Toast.makeText(requireContext(), "密碼已更新", Toast.LENGTH_SHORT).show()
                    } else {
                        val msg = ApiClient.parseError(response.errorBody()?.string())
                        Toast.makeText(requireContext(), "更改失敗：$msg", Toast.LENGTH_SHORT).show()
                    }
                }

                override fun onFailure(call: Call<MessageResponse>, t: Throwable) {
                    if (!isAdded) return
                    Toast.makeText(requireContext(), "網路錯誤：${t.message}", Toast.LENGTH_SHORT).show()
                }
            })
    }

    // ══════════════════════════════════════════════════════════
    // 設定開關同步（GET/PUT /api/v1/users/me/settings）
    // ══════════════════════════════════════════════════════════

    private fun loadSettingsToggles(view: View) {
        val token = TokenManager(requireContext()).accessToken ?: return
        ApiClient.userApi.getSettings("Bearer $token").enqueue(object : Callback<UserSettingsOut> {
            override fun onResponse(call: Call<UserSettingsOut>, response: Response<UserSettingsOut>) {
                if (!isAdded) return
                val s = response.body() ?: return
                if (!response.isSuccessful) return

                TokenManager(requireContext()).quickLoginEnabled = s.quickLogin

                wireToggle(view, R.id.settingMsgMonitor, s.messageMonitoring) { checked ->
                    pushSettingsUpdate(UserSettingsUpdateRequest(messageMonitoring = checked))
                }
                wireToggle(view, R.id.settingEmailScan, s.emailScanning) { checked ->
                    pushSettingsUpdate(UserSettingsUpdateRequest(emailScanning = checked))
                }
                wireToggle(view, R.id.settingCallerId, s.callDetection) { checked ->
                    pushSettingsUpdate(UserSettingsUpdateRequest(callDetection = checked))
                }
                wireToggle(view, R.id.settingQuickLogin, s.quickLogin) { checked ->
                    onQuickLoginToggled(view, checked)
                }
                wireToggle(view, R.id.settingHighRiskAlert, s.highRiskAlert) { checked ->
                    pushSettingsUpdate(UserSettingsUpdateRequest(highRiskAlert = checked))
                }
                wireToggle(view, R.id.settingDailyReport, s.dailyReport) { checked ->
                    pushSettingsUpdate(UserSettingsUpdateRequest(dailyReport = checked))
                }
            }

            override fun onFailure(call: Call<UserSettingsOut>, t: Throwable) {
                // 靜默失敗：開關維持預設關閉狀態即可，不阻斷設定頁使用
            }
        })
    }

    private fun wireToggle(view: View, itemId: Int, current: Boolean, onChanged: (Boolean) -> Unit) {
        val sw = view.findViewById<View>(itemId).findViewById<SwitchMaterial>(R.id.settingsToggle)
        setCheckedSilently(sw, current, onChanged)
    }

    /** 設定 Switch 狀態但不觸發（避免用資料庫初始值回填時誤觸 PUT），並重新掛上監聽器供之後手動切換使用 */
    private fun setCheckedSilently(switchView: SwitchMaterial, checked: Boolean, listener: (Boolean) -> Unit) {
        switchView.setOnCheckedChangeListener(null)
        switchView.isChecked = checked
        switchView.setOnCheckedChangeListener { _, isChecked -> listener(isChecked) }
    }

    private fun onQuickLoginToggled(view: View, checked: Boolean) {
        if (checked) {
            val canAuth = BiometricManager.from(requireContext())
                .canAuthenticate(BiometricManager.Authenticators.BIOMETRIC_WEAK)
            if (canAuth != BiometricManager.BIOMETRIC_SUCCESS) {
                Toast.makeText(requireContext(), "此裝置尚未設定生物辨識，請先至系統設定新增指紋或臉部辨識", Toast.LENGTH_LONG).show()
                val sw = view.findViewById<View>(R.id.settingQuickLogin).findViewById<SwitchMaterial>(R.id.settingsToggle)
                setCheckedSilently(sw, false) { c -> onQuickLoginToggled(view, c) }
                return
            }
        }
        TokenManager(requireContext()).quickLoginEnabled = checked
        pushSettingsUpdate(UserSettingsUpdateRequest(quickLogin = checked))
    }

    private fun pushSettingsUpdate(update: UserSettingsUpdateRequest) {
        val token = TokenManager(requireContext()).accessToken ?: return
        ApiClient.userApi.updateSettings("Bearer $token", update).enqueue(object : Callback<UserSettingsOut> {
            override fun onResponse(call: Call<UserSettingsOut>, response: Response<UserSettingsOut>) {
                if (isAdded && !response.isSuccessful) {
                    Toast.makeText(requireContext(), "設定同步失敗，稍後會再試", Toast.LENGTH_SHORT).show()
                }
            }

            override fun onFailure(call: Call<UserSettingsOut>, t: Throwable) {
                // 靜默失敗：本地畫面已是使用者期望的狀態，下次開啟設定頁會重新從伺服器讀取
            }
        })
    }

    private fun insertTestData() {
        val ctx = context?.applicationContext ?: return
        executor.execute {
            val dao = AppDatabase.getInstance(ctx).capturedNotificationDao()

            if (dao.getTestDataCount() > 0) {
                activity?.runOnUiThread {
                    Toast.makeText(ctx, "測試資料已存在，未重複插入", Toast.LENGTH_SHORT).show()
                }
                return@execute
            }

            val now = System.currentTimeMillis()
            val hour = 3600_000L

            val testData = listOf(
                // ── LINE 私訊 ──
                CapturedNotification(app = "LINE", sender = "陳大富", content = "你好，我是投資顧問陳大富，最近有個很好的投資機會想跟你分享",
                    timestamp = now - 48 * hour, type = "message", packageName = "jp.naver.line.android"),
                CapturedNotification(app = "LINE", sender = "陳大富", content = "我們的平台年化報酬率超過30%，目前已有上千位客戶加入",
                    timestamp = now - 47 * hour, type = "message", packageName = "jp.naver.line.android"),
                CapturedNotification(app = "LINE", sender = "陳大富", content = "只要先匯入5萬元就能開始操作，我會手把手教你",
                    timestamp = now - 24 * hour, type = "message", packageName = "jp.naver.line.android"),
                CapturedNotification(app = "LINE", sender = "陳大富", content = "這是我今天的獲利截圖，你看看，一天就賺了8萬",
                    timestamp = now - 23 * hour, type = "message", packageName = "jp.naver.line.android"),
                CapturedNotification(app = "LINE", sender = "陳大富", content = "趕快把握機會，名額有限喔！匯款帳號：812-XXXXXXXX",
                    timestamp = now - 2 * hour, type = "message", packageName = "jp.naver.line.android"),

                // ── LINE 群組 ──
                CapturedNotification(app = "LINE", sender = "Jessica", content = "大家快看老師的分析，今天又賺翻了！",
                    timestamp = now - 10 * hour, type = "message", packageName = "jp.naver.line.android", groupName = "投資理財交流群"),
                CapturedNotification(app = "LINE", sender = "小美", content = "我跟著操作已經賺了20萬，真的很感謝老師",
                    timestamp = now - 9 * hour, type = "message", packageName = "jp.naver.line.android", groupName = "投資理財交流群"),
                CapturedNotification(app = "LINE", sender = "阿明", content = "新人報到！請問要怎麼開始？",
                    timestamp = now - 5 * hour, type = "message", packageName = "jp.naver.line.android", groupName = "投資理財交流群"),

                // ── 簡訊 ── packageName 用 test_seed_sms 而非 sms_history，
                // 避免跟 SmsHelper 真實簡訊匯入的防重複判斷（getSmsHistoryCount）搞混
                CapturedNotification(app = "簡訊", sender = "0900-000-123", content = "【台灣銀行】您的帳戶有異常交易，請立即點擊連結驗證身份：https://tw-bank.cc/verify",
                    timestamp = now - 6 * hour, type = "message", packageName = "test_seed_sms"),
                CapturedNotification(app = "簡訊", sender = "0912-345-678", content = "恭喜您中獎100萬元！請於三日內回撥領取，逾期作廢。",
                    timestamp = now - 30 * hour, type = "message", packageName = "test_seed_sms"),
                CapturedNotification(app = "簡訊", sender = "中華電信", content = "您的本期帳單金額為 $498，繳費期限 07/15。",
                    timestamp = now - 72 * hour, type = "message", packageName = "test_seed_sms"),

                // ── WhatsApp ──
                CapturedNotification(app = "WhatsApp", sender = "Unknown +44-7911-123456", content = "Hi, I found your number online. I have a great business opportunity for you.",
                    timestamp = now - 12 * hour, type = "message", packageName = "com.whatsapp"),
                CapturedNotification(app = "WhatsApp", sender = "Unknown +44-7911-123456", content = "You can earn $5000 per day from home! Just invest $200 to start.",
                    timestamp = now - 11 * hour, type = "message", packageName = "com.whatsapp"),

                // ── Gmail ──
                CapturedNotification(app = "Gmail", sender = "service@cathay-bk.com.tw(偽)", content = "【緊急通知】您的國泰世華銀行帳戶出現異常登入，請立即驗證您的身份以避免帳戶被凍結。",
                    timestamp = now - 4 * hour, type = "email", packageName = "com.google.android.gm"),
                CapturedNotification(app = "Gmail", sender = "noreply@google.com", content = "Your Google Account security alert: New sign-in from Windows device in Taipei.",
                    timestamp = now - 20 * hour, type = "email", packageName = "com.google.android.gm"),
                CapturedNotification(app = "Gmail", sender = "newsletter@medium.com", content = "Top stories for you this week: AI trends, programming tips, and more.",
                    timestamp = now - 50 * hour, type = "email", packageName = "com.google.android.gm"),

                // ── Outlook ──
                CapturedNotification(app = "Outlook", sender = "admin@microsoft-verify.cc(偽)", content = "您的 Microsoft 365 訂閱即將到期，請點擊以下連結更新付款資訊，否則將失去所有資料存取權限。",
                    timestamp = now - 3 * hour, type = "email", packageName = "com.microsoft.office.outlook"),
                CapturedNotification(app = "Outlook", sender = "hr@company.com", content = "提醒：本月薪資單已上傳至系統，請登入 EIP 查閱。",
                    timestamp = now - 36 * hour, type = "email", packageName = "com.microsoft.office.outlook")
            )

            dao.insertAll(testData)

            activity?.runOnUiThread {
                Toast.makeText(ctx, "已插入 ${testData.size} 筆測試資料，請切換分頁查看", Toast.LENGTH_LONG).show()
            }
        }
    }
}
