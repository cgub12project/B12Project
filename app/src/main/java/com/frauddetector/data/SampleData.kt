/**
 * SampleData.kt — 應用程式範例資料提供者
 *
 * 所屬模組：data（資料層）
 *
 * 本檔案以單例物件（object）的形式提供所有 UI 所需的靜態範例資料，
 * 對應 fraud-detector-v7.html 的 THREADS / PHONE_DB / Email 資料。
 * 資料涵蓋訊息警報、對話線程、帳號威脅檔案、電話號碼、郵件警報等模組。
 *
 * 設計目的：
 * - 在後端 API 尚未就緒時，作為前端開發與展示的資料來源
 * - 當後端 API 或資料庫正式上線後，只需將此檔案的函式改為從 Repository 取得即可，
 *   其餘 Adapter / Fragment / Activity 不需要改動
 * - 同時提供簡易的使用者帳號管理功能（登入驗證、註冊、重設密碼）
 */
package com.frauddetector.data

/**
 * 範例資料 — 對應 fraud-detector-v7.html 的 THREADS / PHONE_DB / Email 資料。
 *
 * 當後端 API 或資料庫正式上線後，只需將此檔案的函式改為從 Repository 取得即可，
 * 其餘 Adapter / Fragment / Activity 不需要改動。
 */
object SampleData {

    // ══════════════════════════════════════════════════════
    // 訊息警報列表 (Messages Tab)
    // ══════════════════════════════════════════════════════

    /**
     * 取得訊息警報列表。
     *
     * 回傳所有訊息分頁中要顯示的 [AlertItem] 列表，
     * 包含高風險（投資詐騙、釣魚連結）、中風險（交友詐騙）、安全訊息等範例。
     * 列表已按時間由新到舊排序。
     *
     * @return 訊息警報項目列表
     */
    fun getAlertItems(): List<AlertItem> = listOf(
        // 高風險：投資詐騙 — 引導匯款至不明銀行帳戶
        AlertItem(
            id = "a1", name = "LINE 群組：台灣投資達人",
            source = "陳大富 · 可疑帳號",
            message = "把錢匯到這個帳號：玉山銀行 808-XXXXXXXX",
            time = "08:23", level = "high", app = "LINE",
            tags = listOf("引導匯款", "投資詐騙"),
            threadId = "invest"
        ),
        // 高風險：釣魚簡訊 — 冒充國泰世華銀行
        AlertItem(
            id = "a2", name = "+886-912-000-999",
            source = "國泰世華(偽) · 冒充機構",
            message = "【國泰世華銀行】系統偵測您的帳戶在異常 IP 登入，請立即驗證。",
            time = "08:31", level = "high", app = "簡訊",
            tags = listOf("釣魚連結", "冒充機構"),
            threadId = "phish"
        ),
        // 中風險：交友詐騙 — 情感操控後可能引導投資
        AlertItem(
            id = "a3", name = "Jessica Lin",
            source = "LINE · 私訊",
            message = "你平時有在投資嗎？我最近發現一個很好的方式，想跟你分享！",
            time = "昨天", level = "mid", app = "LINE",
            tags = listOf("交友詐騙", "情感操控"),
            threadId = "romance"
        ),
        // 高風險：假冒電商客服 — 以包裹退回為由誘騙點擊釣魚連結
        AlertItem(
            id = "a4", name = "Shopee 客服中心(偽)",
            source = "簡訊 · +886-900-111-222",
            message = "您的包裹因地址不完整遭退回，請點擊連結補填資料：bit.ly/xxx",
            time = "昨天", level = "high", app = "簡訊",
            tags = listOf("釣魚連結", "假冒客服"),
            threadId = "phish"
        ),
        // 中風險：投資詐騙 — 透過 WhatsApp 拉群
        AlertItem(
            id = "a5", name = "王經理",
            source = "WhatsApp · 未知聯絡人",
            message = "你好，是朋友推薦來的，想邀請你加入我們的投資群組",
            time = "2天前", level = "mid", app = "WhatsApp",
            tags = listOf("投資詐騙", "拉群話術"),
            threadId = "invest"
        ),
        // 安全：正常家庭對話
        AlertItem(
            id = "a6", name = "媽媽",
            source = "LINE · 家庭群組",
            message = "週末要回來吃飯嗎？",
            time = "3天前", level = "safe", app = "LINE",
            tags = listOf("安全"),
            threadId = ""  // 安全訊息無對應線程
        ),
        // 安全：正常工作訊息
        AlertItem(
            id = "a7", name = "同事小陳",
            source = "Messenger",
            message = "明天的會議改到下午兩點喔",
            time = "3天前", level = "safe", app = "Messenger",
            tags = listOf("安全"),
            threadId = ""  // 安全訊息無對應線程
        )
    )

    // ══════════════════════════════════════════════════════
    // 對話線程 (Thread Detail)
    // ══════════════════════════════════════════════════════

    /**
     * 取得所有對話線程資料。
     *
     * 回傳以線程 ID 為 key 的 [ThreadData] 映射表，
     * 包含投資詐騙（invest）、釣魚攻擊（phish）、交友詐騙（romance）三種情境。
     * 每個線程都包含按詐騙階段（[ChatPhase]）分組的聊天訊息。
     *
     * @return 線程 ID 到 [ThreadData] 的映射表
     */
    fun getThreads(): Map<String, ThreadData> = mapOf(
        // ── 投資詐騙線程：陳大富在 LINE 群組中引導匯款 ──
        "invest" to ThreadData(
            id = "invest", app = "LINE", riskLevel = "high",
            group = "台灣投資達人", sender = "陳大富",
            riskScore = 91, suspectMsgs = 14, days = 12,
            tags = listOf("引導匯款", "投資詐騙", "假獲利保證", "製造緊迫感", "要求轉帳"),
            phases = listOf(
                // 第一階段：建立信任期 — 以假獲利截圖取得受害者信任
                ChatPhase("建立信任期", "b", listOf(
                    ChatMessage("them", "陳大富", "Day 1",
                        "你好！我是在台股賺了第一桶金的陳大富，聽朋友說你也對投資有興趣？",
                        null, null, null),
                    ChatMessage("me", "我", "Day 1",
                        "嗯嗯，有在關注啦，不太懂", null, null, null),
                    ChatMessage("them", "陳大富", "Day 2",
                        "你看，這是我上週的獲利截圖，+87,000 元。真的不難！",
                        "mid", "假截圖話術", "a"),
                    ChatMessage("them", "陳大富", "Day 2",
                        "我帶的學員平均月獲利 30%，穩的。",
                        "mid", "保證獲利 · 不實承諾", "a")
                )),
                // 第二階段：引導匯款 — 核心詐騙行為，要求轉帳至指定帳戶
                ChatPhase("引導匯款（核心詐騙行為）", "r", listOf(
                    ChatMessage("them", "陳大富", "Day 8",
                        "把錢匯到這個帳號：玉山銀行 808-XXXXXXXX\n戶名：台灣資產管理有限公司",
                        "high", "⚠ 引導匯款 · 高危", "r"),
                    ChatMessage("them", "陳大富", "Day 10",
                        "等你匯款通知唷！今天是最後期限，明天就關閉入金通道了！",
                        "high", "最後催款", "r")
                ))
            )
        ),
        // ── 釣魚攻擊線程：冒充國泰世華銀行的簡訊詐騙 ──
        "phish" to ThreadData(
            id = "phish", app = "簡訊", riskLevel = "high",
            group = null, sender = "+886-912-000-999",
            riskScore = 88, suspectMsgs = 6, days = 1,
            tags = listOf("釣魚連結", "冒充機構", "緊急恐嚇", "要求個資"),
            phases = listOf(
                // 單一階段：冒充金融機構發送含釣魚連結的恐嚇簡訊
                ChatPhase("冒充機構 · 釣魚攻擊", "r", listOf(
                    ChatMessage("them", "國泰世華(偽)", "08:31",
                        "【國泰世華銀行】系統偵測您的帳戶在異常 IP 登入，請立即驗證。",
                        "high", "冒充金融機構", "r"),
                    ChatMessage("them", "國泰世華(偽)", "08:32",
                        "請於 30 分鐘內點擊連結，逾時將凍結帳戶：bit.ly/tw-bank-xxx",
                        "high", "⚠ 釣魚連結 + 恐嚇", "r")
                ))
            )
        ),
        // ── 交友詐騙線程：Jessica Lin 的殺豬盤模式 ──
        "romance" to ThreadData(
            id = "romance", app = "LINE", riskLevel = "mid",
            group = null, sender = "Jessica Lin",
            riskScore = 67, suspectMsgs = 9, days = 5,
            tags = listOf("交友詐騙", "情感操控", "逐步引導", "後期可能要求金援"),
            phases = listOf(
                // 第一階段：快速建立情感連結後引入投資話題（殺豬盤模式）
                ChatPhase("快速建立情感連結", "a", listOf(
                    ChatMessage("them", "Jessica", "Day 1",
                        "你的照片看起來好溫柔，感覺是個很有內涵的人耶",
                        "mid", "快速情感拉近", "a"),
                    ChatMessage("me", "我", "Day 2",
                        "謝謝，你也很漂亮", null, null, null),
                    ChatMessage("them", "Jessica", "Day 3",
                        "最近心情不太好，可以跟你聊聊嗎？",
                        "mid", "情感依附", "a"),
                    // 第 4 天即轉向投資話題，符合殺豬盤的典型時間線
                    ChatMessage("them", "Jessica", "Day 4",
                        "你平時有在投資嗎？我最近發現一個很好的方式，想跟你分享！",
                        "high", "⚠ 開始引入投資話題", "r")
                ))
            )
        )
    )

    // ══════════════════════════════════════════════════════
    // 帳號威脅檔案 (Account Detail)
    // ══════════════════════════════════════════════════════

    /**
     * 取得所有帳號威脅檔案。
     *
     * 回傳以線程 ID 為 key 的 [AccountProfile] 映射表，
     * 每個檔案彙整了可疑帳號的風險評分、觸發規則與 AI 分析的具體證據。
     * 與 [getThreads] 共用相同的線程 ID，方便交叉查詢。
     *
     * @return 線程 ID 到 [AccountProfile] 的映射表
     */
    fun getAccountProfiles(): Map<String, AccountProfile> = mapOf(
        // ── 陳大富的帳號威脅檔案：投資詐騙高風險帳號 ──
        "invest" to AccountProfile(
            threadId = "invest", name = "陳大富",
            identifier = "LINE: @chen_dafu_invest",
            riskScore = 91, suspectMsgs = 14, days = 12,
            threatLevel = "high",
            rules = listOf("引導匯款", "假獲利截圖", "保證高額報酬", "製造緊迫感", "要求銀行轉帳"),
            evidences = listOf(
                // 證據 1：直接要求匯款至指定銀行帳戶
                EvidenceItem("引導匯款", "r", "Day 8",
                    "要求匯款至玉山銀行 808-XXXXXXXX，戶名「台灣資產管理有限公司」。帳戶名與投資標的不符。"),
                // 證據 2：不切實際的獲利承諾
                EvidenceItem("虛假承諾", "a", "Day 2",
                    "聲稱「學員平均月獲利 30%」，此報酬率遠超合理市場預期，屬典型投資詐騙話術。"),
                // 證據 3：使用偽造的獲利截圖建立信任
                EvidenceItem("假截圖", "a", "Day 2",
                    "提供 +87,000 元獲利截圖，圖片可能經修改，用於建立信任。"),
                // 證據 4：以最後期限施壓催促匯款
                EvidenceItem("最後通牒", "r", "Day 10",
                    "以「今天是最後期限，明天關閉入金通道」製造緊迫感，催促受害者立即匯款。")
            )
        ),
        // ── 釣魚簡訊帳號威脅檔案：冒充銀行的高風險號碼 ──
        "phish" to AccountProfile(
            threadId = "phish", name = "+886-912-000-999",
            identifier = "SMS: +886-912-000-999",
            riskScore = 88, suspectMsgs = 6, days = 1,
            threatLevel = "high",
            rules = listOf("冒充金融機構", "釣魚連結", "緊急恐嚇", "要求個人資料"),
            evidences = listOf(
                // 證據 1：冒充國泰世華銀行
                EvidenceItem("冒充機構", "r", "08:31",
                    "偽裝國泰世華銀行發送簡訊，聲稱帳戶在異常 IP 登入。"),
                // 證據 2：包含導向偽造登入頁面的短網址
                EvidenceItem("釣魚連結", "r", "08:32",
                    "包含短網址 bit.ly/tw-bank-xxx，導向偽造的銀行登入頁面。"),
                // 證據 3：以凍結帳戶為威脅施壓
                EvidenceItem("恐嚇施壓", "r", "08:32",
                    "威脅 30 分鐘內不驗證將凍結帳戶，製造恐慌促使點擊。")
            )
        ),
        // ── Jessica Lin 帳號威脅檔案：交友詐騙（殺豬盤）中風險帳號 ──
        "romance" to AccountProfile(
            threadId = "romance", name = "Jessica Lin",
            identifier = "LINE: @jessica_lin_02",
            riskScore = 67, suspectMsgs = 9, days = 5,
            threatLevel = "mid",
            rules = listOf("快速情感拉近", "情感操控", "引入投資話題"),
            evidences = listOf(
                // 證據 1：初次接觸即以外貌稱讚拉近距離
                EvidenceItem("快速拉近", "a", "Day 1",
                    "初次接觸即以外貌稱讚拉近距離，交友詐騙典型起手式。"),
                // 證據 2：短時間內即轉向投資話題，符合殺豬盤模式
                EvidenceItem("引入投資", "r", "Day 4",
                    "第 4 天即開始引入投資話題，符合「殺豬盤」模式。")
            )
        )
    )

    // ══════════════════════════════════════════════════════
    // 電話號碼資料庫 (Phone Tab / Phone Detail)
    // ══════════════════════════════════════════════════════

    /**
     * 取得電話號碼記錄列表。
     *
     * 回傳所有電話分頁中要顯示的 [PhoneRecord] 列表，
     * 包含高風險（假冒政府機關、假冒銀行客服）、中風險（簡訊詐騙）、
     * 安全（官方客服）等不同風險等級的電話號碼範例。
     *
     * @return 電話號碼記錄列表
     */
    fun getPhoneRecords(): List<PhoneRecord> = listOf(
        // 高風險電話：假冒政府機關（健保局、法院），舉報次數極高
        PhoneRecord(
            id = "p1", number = "+886-800-XXX-XXX",
            riskLevel = "high", riskLabel = "詐騙",
            type = "假冒政府機關", count = "2,847", lastReport = "2 小時前",
            reports = listOf(
                CommunityReport("用戶 A3***", "假冒政府機關", "r", "2 小時前",
                    "自稱健保局，聲稱積欠保費，要求提供帳戶資料並轉帳到「安全帳戶」。"),
                CommunityReport("用戶 B7***", "假冒政府機關", "r", "5 小時前",
                    "聲稱法院通知，要求今日內清繳罰款，否則將凍結帳戶。"),
                CommunityReport("用戶 C1***", "騷擾電話", "a", "1 天前",
                    "接聽後無人說話，疑似自動撥號確認號碼有效性。")
            )
        ),
        // 高風險電話：假冒銀行客服，騙取 OTP 驗證碼
        PhoneRecord(
            id = "p2", number = "02-XXXX-XXXX",
            riskLevel = "high", riskLabel = "詐騙",
            type = "假冒銀行客服", count = "1,203", lastReport = "1 天前",
            reports = listOf(
                CommunityReport("用戶 E9***", "假冒銀行客服", "r", "1 天前",
                    "自稱玉山銀行，謊稱信用卡有可疑交易，要求提供 OTP 驗證碼。"),
                CommunityReport("用戶 F2***", "假冒銀行客服", "r", "2 天前",
                    "要求轉帳至「安全帳戶」以保護資金。")
            )
        ),
        // 中風險電話：簡訊詐騙，發送含釣魚連結的簡訊
        PhoneRecord(
            id = "p3", number = "+886-912-000-999",
            riskLevel = "mid", riskLabel = "可疑",
            type = "簡訊詐騙", count = "312", lastReport = "3 天前",
            reports = listOf(
                CommunityReport("用戶 H4***", "釣魚詐騙", "a", "3 天前",
                    "發送含縮短網址的簡訊，聲稱包裹需補繳費用。")
            )
        ),
        // 安全電話：電信商官方客服號碼，無舉報記錄
        PhoneRecord(
            id = "p4", number = "0800-080-995",
            riskLevel = "safe", riskLabel = "安全",
            type = "台灣大哥大官方客服", count = "0", lastReport = "無舉報記錄",
            reports = emptyList()
        )
    )

    // ══════════════════════════════════════════════════════
    // 郵件警報 (Email Tab)
    // ══════════════════════════════════════════════════════

    /**
     * 取得郵件警報列表。
     *
     * 回傳所有郵件分頁中要顯示的 [EmailAlert] 列表，
     * 包含高風險（冒充銀行、假冒電商）、中風險（社交工程）、
     * 安全（正常電子報）等不同風險等級的郵件範例。
     *
     * @return 郵件警報列表
     */
    fun getEmailAlerts(): List<EmailAlert> = listOf(
        // 高風險郵件：冒充國泰世華銀行的釣魚郵件
        EmailAlert(
            id = "e1", sender = "service@cathay-bk.com.tw(偽)",
            subject = "【緊急】您的帳戶存在安全風險",
            preview = "我們偵測到您的帳戶在異常位置登入，請立即點擊下方連結進行身份驗證...",
            time = "09:15", level = "high", provider = "Gmail",
            tags = listOf("釣魚郵件", "冒充銀行")
        ),
        // 高風險郵件：冒充 Amazon 的訂單詐騙郵件
        EmailAlert(
            id = "e2", sender = "noreply@amazn-tw.com(偽)",
            subject = "您的 Amazon 訂單需要確認",
            preview = "您的訂單 #302-XXXXXX 因付款問題暫停處理，請更新您的付款資訊...",
            time = "昨天", level = "high", provider = "Gmail",
            tags = listOf("釣魚郵件", "假冒電商")
        ),
        // 中風險郵件：社交工程攻擊，假冒 IT 部門要求重設密碼
        EmailAlert(
            id = "e3", sender = "admin@company.com",
            subject = "IT 部門：密碼即將過期",
            preview = "您的企業帳號密碼將在 24 小時內過期，請點擊連結重設密碼以避免帳號鎖定...",
            time = "2天前", level = "mid", provider = "Outlook",
            tags = listOf("可疑連結", "社交工程")
        ),
        // 安全郵件：正常的 Medium 電子報
        EmailAlert(
            id = "e4", sender = "newsletter@medium.com",
            subject = "Your Daily Digest",
            preview = "Top stories for you today: How AI is changing...",
            time = "3天前", level = "safe", provider = "Gmail",
            tags = listOf("安全")
        )
    )

    // ══════════════════════════════════════════════════════
    // 使用者帳號 (Login 驗證用)
    // ══════════════════════════════════════════════════════

    /**
     * 本地使用者帳號資料庫（記憶體暫存）。
     *
     * 以 email 為 key、密碼為 value 的可變映射表。
     * 預設包含一組測試帳號 "test@example.com" / "password"。
     * 注意：此為範例實作，資料僅存在於記憶體中，App 重啟後會重置。
     */
    private val users = mutableMapOf(
        "test@example.com" to "password"
    )

    /**
     * 驗證使用者登入。
     *
     * 比對 email 與密碼是否與本地帳號資料庫中的記錄相符。
     *
     * @param email 使用者的電子郵件地址
     * @param password 使用者輸入的密碼
     * @return 若 email 存在且密碼正確則回傳 true，否則回傳 false
     */
    fun validateLogin(email: String, password: String): Boolean {
        return users[email] == password
    }

    /**
     * 註冊新使用者。
     *
     * 將新的 email/password 組合加入本地帳號資料庫。
     * 若 email 已存在則註冊失敗。
     *
     * @param email 新使用者的電子郵件地址
     * @param password 新使用者的密碼
     * @return 註冊成功回傳 true；若 email 已存在則回傳 false
     */
    fun registerUser(email: String, password: String): Boolean {
        // 檢查 email 是否已被註冊
        if (users.containsKey(email)) return false
        // 將新帳號加入資料庫
        users[email] = password
        return true
    }

    /**
     * 檢查使用者是否已存在。
     *
     * @param email 要檢查的電子郵件地址
     * @return 若 email 已存在於本地帳號資料庫則回傳 true
     */
    fun userExists(email: String): Boolean = users.containsKey(email)

    /**
     * 重設使用者密碼。
     *
     * 將指定 email 的密碼更新為新密碼。
     * 若 email 不存在則重設失敗。
     *
     * @param email 使用者的電子郵件地址
     * @param newPassword 新的密碼
     * @return 重設成功回傳 true；若 email 不存在則回傳 false
     */
    fun resetPassword(email: String, newPassword: String): Boolean {
        // 確認帳號存在才允許重設
        if (!users.containsKey(email)) return false
        // 更新密碼
        users[email] = newPassword
        return true
    }
}
