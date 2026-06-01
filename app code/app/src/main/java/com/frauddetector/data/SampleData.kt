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
    fun getAlertItems(): List<AlertItem> = listOf(
        AlertItem(
            id = "a1", name = "LINE 群組：台灣投資達人",
            source = "陳大富 · 可疑帳號",
            message = "把錢匯到這個帳號：玉山銀行 808-XXXXXXXX",
            time = "08:23", level = "high", app = "LINE",
            tags = listOf("引導匯款", "投資詐騙"),
            threadId = "invest"
        ),
        AlertItem(
            id = "a2", name = "+886-912-000-999",
            source = "國泰世華(偽) · 冒充機構",
            message = "【國泰世華銀行】系統偵測您的帳戶在異常 IP 登入，請立即驗證。",
            time = "08:31", level = "high", app = "簡訊",
            tags = listOf("釣魚連結", "冒充機構"),
            threadId = "phish"
        ),
        AlertItem(
            id = "a3", name = "Jessica Lin",
            source = "LINE · 私訊",
            message = "你平時有在投資嗎？我最近發現一個很好的方式，想跟你分享！",
            time = "昨天", level = "mid", app = "LINE",
            tags = listOf("交友詐騙", "情感操控"),
            threadId = "romance"
        ),
        AlertItem(
            id = "a4", name = "Shopee 客服中心(偽)",
            source = "簡訊 · +886-900-111-222",
            message = "您的包裹因地址不完整遭退回，請點擊連結補填資料：bit.ly/xxx",
            time = "昨天", level = "high", app = "簡訊",
            tags = listOf("釣魚連結", "假冒客服"),
            threadId = "phish"
        ),
        AlertItem(
            id = "a5", name = "王經理",
            source = "WhatsApp · 未知聯絡人",
            message = "你好，是朋友推薦來的，想邀請你加入我們的投資群組",
            time = "2天前", level = "mid", app = "WhatsApp",
            tags = listOf("投資詐騙", "拉群話術"),
            threadId = "invest"
        ),
        AlertItem(
            id = "a6", name = "媽媽",
            source = "LINE · 家庭群組",
            message = "週末要回來吃飯嗎？",
            time = "3天前", level = "safe", app = "LINE",
            tags = listOf("安全"),
            threadId = ""
        ),
        AlertItem(
            id = "a7", name = "同事小陳",
            source = "Messenger",
            message = "明天的會議改到下午兩點喔",
            time = "3天前", level = "safe", app = "Messenger",
            tags = listOf("安全"),
            threadId = ""
        )
    )

    // ══════════════════════════════════════════════════════
    // 對話線程 (Thread Detail)
    // ══════════════════════════════════════════════════════
    fun getThreads(): Map<String, ThreadData> = mapOf(
        "invest" to ThreadData(
            id = "invest", app = "LINE", riskLevel = "high",
            group = "台灣投資達人", sender = "陳大富",
            riskScore = 91, suspectMsgs = 14, days = 12,
            tags = listOf("引導匯款", "投資詐騙", "假獲利保證", "製造緊迫感", "要求轉帳"),
            phases = listOf(
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
        "phish" to ThreadData(
            id = "phish", app = "簡訊", riskLevel = "high",
            group = null, sender = "+886-912-000-999",
            riskScore = 88, suspectMsgs = 6, days = 1,
            tags = listOf("釣魚連結", "冒充機構", "緊急恐嚇", "要求個資"),
            phases = listOf(
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
        "romance" to ThreadData(
            id = "romance", app = "LINE", riskLevel = "mid",
            group = null, sender = "Jessica Lin",
            riskScore = 67, suspectMsgs = 9, days = 5,
            tags = listOf("交友詐騙", "情感���控", "逐步引導", "後期可能要求金援"),
            phases = listOf(
                ChatPhase("快速建立情感連結", "a", listOf(
                    ChatMessage("them", "Jessica", "Day 1",
                        "你的照片看起來好溫柔，感覺是個很有內涵的人耶",
                        "mid", "快速情感拉近", "a"),
                    ChatMessage("me", "我", "Day 2",
                        "謝謝，你也很漂亮", null, null, null),
                    ChatMessage("them", "Jessica", "Day 3",
                        "最近心情不太好，可以跟你聊聊嗎？",
                        "mid", "情感依附", "a"),
                    ChatMessage("them", "Jessica", "Day 4",
                        "你平時有在投資嗎？我最近發現一個很好的方式，想跟你分享！",
                        "high", "⚠ 開始引入投資話題", "r")
                ))
            )
        )
    )

    // ══════════════════════════════════════════════════════
    // 帳號威脅檔案 (Account Detail)
    // ═══════════════════════════════════════════════════��══
    fun getAccountProfiles(): Map<String, AccountProfile> = mapOf(
        "invest" to AccountProfile(
            threadId = "invest", name = "陳大富",
            identifier = "LINE: @chen_dafu_invest",
            riskScore = 91, suspectMsgs = 14, days = 12,
            threatLevel = "high",
            rules = listOf("引導匯款", "假獲利截圖", "保證高額報酬", "製造緊迫感", "要求銀行轉帳"),
            evidences = listOf(
                EvidenceItem("引��匯款", "r", "Day 8",
                    "要求匯款至玉山銀行 808-XXXXXXXX，戶名「台灣資產管理有限公司」。帳戶名與投資標的不符。"),
                EvidenceItem("虛假承諾", "a", "Day 2",
                    "聲稱「學員平均月獲利 30%」，此報酬率遠超合理市場預期，屬典型投資詐騙話術。"),
                EvidenceItem("假截圖", "a", "Day 2",
                    "提供 +87,000 元獲利截圖，圖片可能經修改，用於建立信任。"),
                EvidenceItem("最後通牒", "r", "Day 10",
                    "以「今天是最後期限，明天關閉入金通道」製造緊迫感，催促受害者立即匯款。")
            )
        ),
        "phish" to AccountProfile(
            threadId = "phish", name = "+886-912-000-999",
            identifier = "SMS: +886-912-000-999",
            riskScore = 88, suspectMsgs = 6, days = 1,
            threatLevel = "high",
            rules = listOf("冒充金融機構", "釣魚連結", "緊急恐嚇", "要求個人資料"),
            evidences = listOf(
                EvidenceItem("冒充機構", "r", "08:31",
                    "偽裝國泰世華銀行發送簡訊，聲稱帳戶在異常 IP 登入。"),
                EvidenceItem("釣魚連結", "r", "08:32",
                    "包含短網址 bit.ly/tw-bank-xxx，導向偽造的銀行登入頁面。"),
                EvidenceItem("恐嚇施壓", "r", "08:32",
                    "威脅 30 分鐘內不驗證將凍結帳戶，製造恐慌促使點擊。")
            )
        ),
        "romance" to AccountProfile(
            threadId = "romance", name = "Jessica Lin",
            identifier = "LINE: @jessica_lin_02",
            riskScore = 67, suspectMsgs = 9, days = 5,
            threatLevel = "mid",
            rules = listOf("快速情感拉近", "情感操控", "引入投資話題"),
            evidences = listOf(
                EvidenceItem("快速拉近", "a", "Day 1",
                    "初次接觸即以外貌稱讚拉近距離，交友詐騙典型起手式。"),
                EvidenceItem("引入投資", "r", "Day 4",
                    "第 4 天即開始引入投資話題，符合「殺豬盤」模式。")
            )
        )
    )

    // ══════════════════════════════════════════════════════
    // 電話號碼資料庫 (Phone Tab / Phone Detail)
    // ══════════════════════════════════════════════════════
    fun getPhoneRecords(): List<PhoneRecord> = listOf(
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
        PhoneRecord(
            id = "p3", number = "+886-912-000-999",
            riskLevel = "mid", riskLabel = "可疑",
            type = "簡訊詐騙", count = "312", lastReport = "3 天前",
            reports = listOf(
                CommunityReport("用戶 H4***", "釣魚詐騙", "a", "3 天前",
                    "發送含縮短網址的簡訊，聲稱包裹需補繳費用。")
            )
        ),
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
    fun getEmailAlerts(): List<EmailAlert> = listOf(
        EmailAlert(
            id = "e1", sender = "service@cathay-bk.com.tw(偽)",
            subject = "【緊急】您的帳戶存在安全風險",
            preview = "我們偵測到您的帳戶在異常位置登入，請立即點擊下方連結進行身份驗證...",
            time = "09:15", level = "high", provider = "Gmail",
            tags = listOf("釣魚郵件", "冒充銀行")
        ),
        EmailAlert(
            id = "e2", sender = "noreply@amazn-tw.com(偽)",
            subject = "您的 Amazon 訂單需要確認",
            preview = "您的訂單 #302-XXXXXX 因付款問題暫停處理，請更新您的付款資訊...",
            time = "昨天", level = "high", provider = "Gmail",
            tags = listOf("釣魚郵件", "假冒電商")
        ),
        EmailAlert(
            id = "e3", sender = "admin@company.com",
            subject = "IT 部門：密碼即將過期",
            preview = "您的企業帳號密碼將在 24 小時內過期，請點擊連結重設密碼以避免帳號鎖定...",
            time = "2天前", level = "mid", provider = "Outlook",
            tags = listOf("可疑連結", "社交工程")
        ),
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
    private val users = mutableMapOf(
        "test@example.com" to "password"
    )

    fun validateLogin(email: String, password: String): Boolean {
        return users[email] == password
    }

    fun registerUser(email: String, password: String): Boolean {
        if (users.containsKey(email)) return false
        users[email] = password
        return true
    }

    fun userExists(email: String): Boolean = users.containsKey(email)

    fun resetPassword(email: String, newPassword: String): Boolean {
        if (!users.containsKey(email)) return false
        users[email] = newPassword
        return true
    }
}
