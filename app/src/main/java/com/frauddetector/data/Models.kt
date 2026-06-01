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
 * - [SampleData] 範例資料的結構定義
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
 * 包含來源、風險等級、所屬應用程式與標籤等資訊，
 * 並透過 [threadId] 關聯到完整的對話線程 [ThreadData]。
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
    val threadId: String      // 對應 Thread ID，點擊後導航用
) : Serializable

// ══════════════════════════════════════════════════════════
// 對話線程 (Thread Detail)
// ══════════════════════════════════════════════════════════

/**
 * 對話線程資料 — 代表一個完整的詐騙對話線程。
 *
 * 包含風險評分、可疑訊息數量、對話天數等統計資訊，
 * 以及按詐騙階段（[ChatPhase]）分組的完整聊天記錄。
 * 用於 ThreadDetailActivity 的詳細對話檢視頁面。
 */
data class ThreadData(
    /** 線程唯一識別碼，例如 "invest"、"phish"、"romance" */
    val id: String,
    /** 訊息來源的應用程式名稱，例如 "LINE"、"簡訊" */
    val app: String,
    /** 整體風險等級："high"（高風險）、"mid"（中風險） */
    val riskLevel: String,    // "high", "mid"
    /** 群組名稱，若為私訊則為 null */
    val group: String?,
    /** 發送者名稱或號碼 */
    val sender: String,
    /** 風險評分，範圍 0–100，數值越高代表風險越大 */
    val riskScore: Int,
    /** 被標記為可疑的訊息總數 */
    val suspectMsgs: Int,
    /** 對話持續天數 */
    val days: Int,
    /** 詐騙手法標籤列表，例如 ["引導匯款", "投資詐騙"] */
    val tags: List<String>,
    /** 對話階段列表，將聊天記錄按詐騙手法分期呈現 */
    val phases: List<ChatPhase>
) : Serializable

/**
 * 聊天階段 — 將對話線程中的訊息依詐騙手法分成不同階段。
 *
 * 例如「建立信任期」、「引導匯款」等階段，
 * 每個階段包含一組 [ChatMessage] 以及對應的視覺風格類別。
 */
data class ChatPhase(
    /** 階段名稱標籤，例如 "建立信任期"、"引導匯款（核心詐騙行為）" */
    val label: String,
    /** 階段的風格類別："r"（紅色/高危）、"a"（琥珀色/中危）、"b"（藍色/一般） */
    val phaseClass: String,   // "r", "a", "b"
    /** 該階段中的聊天訊息列表 */
    val messages: List<ChatMessage>
) : Serializable

/**
 * 聊天訊息 — 代表對話線程中的單一訊息氣泡。
 *
 * 記錄了訊息的發送方、內容、時間，以及 AI 分析後標記的
 * 風險旗標與可疑原因說明。
 */
data class ChatMessage(
    /** 訊息發送方："them"（對方/可疑方）、"me"（使用者自己） */
    val who: String,          // "them", "me"
    /** 發送者顯示名稱 */
    val name: String,
    /** 訊息時間標記，例如 "Day 1"、"08:31" */
    val time: String,
    /** 訊息文字內容 */
    val text: String,
    /** 風險旗標：null（無標記）、"high"（高風險）、"mid"（中風險） */
    val flag: String?,        // null, "high", "mid"
    /** AI 分析的可疑原因說明，例如 "⚠ 引導匯款 · 高危"；無風險時為 null */
    val reason: String?,
    /** 可疑原因的風格類別："r"（紅色/高危）、"a"（琥珀色/中危）；無風險時為 null */
    val reasonClass: String?  // "r", "a"
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
    val tags: List<String>
) : Serializable

// ══════════════════════════════════════════════════════════
// 帳號威脅檔案 (Account Detail)
// ══════════════════════════════════════════════════════════

/**
 * 帳號威脅檔案 — 代表某個可疑帳號的完整風險評估報告。
 *
 * 彙整了帳號的風險評分、觸發的詐騙規則，
 * 以及 AI 分析後整理的具體證據項目列表。
 * 用於 AccountDetailActivity 的帳號詳情頁面。
 */
data class AccountProfile(
    /** 關聯的對話線程 ID，用於交叉查詢對應的 [ThreadData] */
    val threadId: String,
    /** 帳號顯示名稱，例如 "陳大富"、"Jessica Lin" */
    val name: String,
    /** 帳號識別碼，例如 "LINE: @chen_dafu_invest"、"SMS: +886-912-000-999" */
    val identifier: String,
    /** 風險評分，範圍 0–100，數值越高代表風險越大 */
    val riskScore: Int,
    /** 被標記為可疑的訊息總數 */
    val suspectMsgs: Int,
    /** 與使用者互動的天數 */
    val days: Int,
    /** 威脅等級："high"（高威脅）、"mid"（中威脅） */
    val threatLevel: String,
    /** 觸發的詐騙規則列表，例如 ["引導匯款", "假獲利截圖"] */
    val rules: List<String>,
    /** AI 分析後整理的證據項目列表 */
    val evidences: List<EvidenceItem>
) : Serializable

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
