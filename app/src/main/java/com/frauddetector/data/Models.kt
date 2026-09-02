/**
 * Models.kt — 應用程式核心資料模型定義檔
 *
 * 所屬模組：data（資料層）
 *
 * 本檔案定義了 FLASH 詐騙偵測 App 中所有主要的資料模型（Data Class），
 * 涵蓋訊息警報、對話線程、電話號碼、郵件警報、帳號威脅檔案等功能模組。
 * 所有模型皆實作 [Serializable] 介面，以支援 Intent / Bundle 之間的資料傳遞。
 *
 * 這些模型主要用於：
 * - UI 層（Fragment / Activity / Adapter）的資料綁定與呈現
 * - 未來對接後端 API 時的回應資料映射
 */
package com.frauddetector.data

import java.io.Serializable

// ══════════════════════════════════════════════════════════
// 訊息警報 (Messages Tab)
// ══════════════════════════════════════════════════════════

/**
 * 訊息警報項目 — 代表「訊息」分頁中的單筆警報卡片。
 *
 * 每一筆 [AlertItem] 對應使用者收到的一則可疑訊息，
 * 包含來源、風險等級、所屬應用程式與標籤等資訊。
 * [threadId] 欄位為舊版設計殘留，目前對話詳情改以 (app, sender) 查詢 Room DB，未使用此欄位。
 */
data class AlertItem(
    /** 警報的唯一識別碼，例如 "a1"、"a2" */
    val id: String,
    /** 顯示名稱，例如聯絡人名稱或群組名稱 */
    val name: String,
    /** 訊息來源描述，例如 "陳大富 · 可疑帳號" */
    val source: String,
    /** 訊息內容預覽文字 */
    val message: String,
    /** 訊息時間，例如 "08:23"、"昨天"、"2天前" */
    val time: String,
    /** 風險等級："high"（高風險）、"mid"（中風險）、"safe"（安全） */
    val level: String,        // "high", "mid", "safe"
    /** 訊息來源的應用程式名稱："LINE"、"簡訊"、"WhatsApp"、"Messenger" */
    val app: String,          // "LINE", "簡訊", "WhatsApp", "Messenger"
    /** 詐騙標籤列表，例如 ["引導匯款", "投資詐騙"] */
    val tags: List<String>,
    /** 對應的對話線程 ID，點擊警報卡片後用於導航至 ThreadDetailActivity */
    val threadId: String,     // 對應 Thread ID，點擊後導航用
    /**
     * 預覽這則訊息的發話者名字，只有群組對話才有值；私訊為空字串。
     *
     * 群組卡片的內容標籤會直接顯示「陳大富:」而不是通用的「訊息內容:」——群組裡誰講的
     * 才是判讀話術的關鍵，通用標籤等於白佔一行。私訊的發話者就是卡片標題本身，
     * 沒必要重複，所以留空讓卡片顯示「訊息內容:」。
     */
    val speaker: String = "",
    /**
     * 這張卡片代表的是群組對話還是私訊。
     *
     * ★不要再從 [tags] 反推：標籤是純顯示用的，2026-08-17/18 把卡片上的
     * 「群組」標籤拿掉之後，靠 tags.contains("群組") 判斷的地方就全部失效了
     * （群組被當成私訊開啟 → 撈不到訊息 → 詳情頁永遠顯示「未分析」）。
     */
    val isGroup: Boolean = false
) : Serializable

// ══════════════════════════════════════════════════════════
// 電話號碼 (Phone Tab / Phone Detail)
// ══════════════════════════════════════════════════════════

/**
 * 電話號碼記錄 — 代表「電話」分頁中的單筆電話號碼資料。
 *
 * 包含號碼的風險評級、詐騙類型、社群舉報統計，
 * 以及社群使用者提交的舉報內容列表。
 */
data class PhoneRecord(
    /** 電話記錄的唯一識別碼，例如 "p1"、"p2" */
    val id: String,
    /** 電話號碼，例如 "+886-800-XXX-XXX" */
    val number: String,
    /** 風險等級："high"（高風險）、"mid"（中風險）、"safe"（安全） */
    val riskLevel: String,    // "high", "mid", "safe"
    /** 風險等級的中文標籤，例如 "詐騙"、"可疑"、"安全" */
    val riskLabel: String,
    /** 詐騙類型描述，例如 "假冒政府機關"、"假冒銀行客服" */
    val type: String,
    /** 累計舉報次數（字串格式，含千分位逗號），例如 "2,847" */
    val count: String,
    /** 最後一次被舉報的時間描述，例如 "2 小時前" */
    val lastReport: String,
    /** 社群使用者提交的舉報列表 */
    val reports: List<CommunityReport>
) : Serializable

/**
 * 社群舉報 — 代表某個電話號碼的單筆社群使用者舉報記錄。
 *
 * 記錄了舉報者（匿名）、舉報的詐騙類型、時間與詳細描述。
 */
data class CommunityReport(
    /** 舉報者匿名代號，例如 "用戶 A3***" */
    val user: String,
    /** 舉報的詐騙類型，例如 "假冒政府機關"、"釣魚詐騙" */
    val type: String,
    /** 詐騙類型的風格類別："r"（紅色/高危）、"a"（琥珀色/中危） */
    val typeClass: String,    // "r", "a"
    /** 舉報時間描述，例如 "2 小時前"、"1 天前" */
    val time: String,
    /** 舉報的詳細描述文字 */
    val desc: String
) : Serializable

// ══════════════════════════════════════════════════════════
// 郵件警報 (Email Tab)
// ══════════════════════════════════════════════════════════

/**
 * 郵件警報 — 代表「郵件」分頁中的單筆可疑郵件記錄。
 *
 * 包含寄件者、主旨、預覽內容、風險等級、郵件供應商
 * 以及 AI 標記的詐騙標籤。
 */
data class EmailAlert(
    /** 郵件警報的唯一識別碼，例如 "e1"、"e2" */
    val id: String,
    /** 寄件者地址，偽冒郵件會標註「(偽)」，例如 "service@cathay-bk.com.tw(偽)" */
    val sender: String,
    /** 郵件主旨 */
    val subject: String,
    /** 郵件內容預覽（截取前幾行文字） */
    val preview: String,
    /** 收件時間，例如 "09:15"、"昨天"、"2天前" */
    val time: String,
    /** 風險等級："high"（高風險）、"mid"（中風險）、"safe"（安全） */
    val level: String,        // "high", "mid", "safe"
    /** 郵件供應商名稱："Gmail"、"Outlook"、"全部"，用於分頁篩選 */
    val provider: String,     // "Gmail", "Outlook", "全部"
    /** 詐騙標籤列表，例如 ["釣魚郵件", "冒充銀行"] */
    val tags: List<String>,
    /** 已連接信箱（真實郵件）所屬的帳號 email，用來反查 account_id 做真封鎖；本機通知擷取的項目為空字串 */
    val accountEmail: String = ""
) : Serializable

// ══════════════════════════════════════════════════════════
// 帳號威脅檔案 (Account Detail)
// ══════════════════════════════════════════════════════════

/**
 * 證據項目 — 代表帳號威脅檔案中的單一具體證據。
 *
 * 每個證據包含詐騙行為類型、發生時間與詳細文字說明，
 * 用於在 UI 上逐條呈現 AI 的分析結果。
 */
data class EvidenceItem(
    /** 證據的詐騙行為類型，例如 "引導匯款"、"冒充機構" */
    val type: String,
    /** 類型的風格類別："r"（紅色/高危）、"a"（琥珀色/中危） */
    val typeClass: String,    // "r", "a"
    /** 證據發生的時間點，例如 "Day 8"、"08:31" */
    val time: String,
    /** 證據的詳細文字說明 */
    val text: String
) : Serializable
