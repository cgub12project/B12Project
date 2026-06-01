package com.frauddetector.data

import java.io.Serializable

// ── 訊息警報 (Messages Tab) ──────────────────────────────
data class AlertItem(
    val id: String,
    val name: String,
    val source: String,
    val message: String,
    val time: String,
    val level: String,        // "high", "mid", "safe"
    val app: String,          // "LINE", "簡訊", "WhatsApp", "Messenger"
    val tags: List<String>,
    val threadId: String      // 對應 Thread ID，點擊後導航用
) : Serializable

// ── 對話線程 (Thread Detail) ─────────────────────────────
data class ThreadData(
    val id: String,
    val app: String,
    val riskLevel: String,    // "high", "mid"
    val group: String?,
    val sender: String,
    val riskScore: Int,
    val suspectMsgs: Int,
    val days: Int,
    val tags: List<String>,
    val phases: List<ChatPhase>
) : Serializable

data class ChatPhase(
    val label: String,
    val phaseClass: String,   // "r", "a", "b"
    val messages: List<ChatMessage>
) : Serializable

data class ChatMessage(
    val who: String,          // "them", "me"
    val name: String,
    val time: String,
    val text: String,
    val flag: String?,        // null, "high", "mid"
    val reason: String?,
    val reasonClass: String?  // "r", "a"
) : Serializable

// ── 電話號碼 (Phone Tab / Phone Detail) ──────────────────
data class PhoneRecord(
    val id: String,
    val number: String,
    val riskLevel: String,    // "high", "mid", "safe"
    val riskLabel: String,
    val type: String,
    val count: String,
    val lastReport: String,
    val reports: List<CommunityReport>
) : Serializable

data class CommunityReport(
    val user: String,
    val type: String,
    val typeClass: String,    // "r", "a"
    val time: String,
    val desc: String
) : Serializable

// ── 郵件警報 (Email Tab) ─────────────────────────────────
data class EmailAlert(
    val id: String,
    val sender: String,
    val subject: String,
    val preview: String,
    val time: String,
    val level: String,        // "high", "mid", "safe"
    val provider: String,     // "Gmail", "Outlook", "全部"
    val tags: List<String>
) : Serializable

// ── 帳號威脅檔案 (Account Detail) ────────────────────────
data class AccountProfile(
    val threadId: String,
    val name: String,
    val identifier: String,
    val riskScore: Int,
    val suspectMsgs: Int,
    val days: Int,
    val threatLevel: String,
    val rules: List<String>,
    val evidences: List<EvidenceItem>
) : Serializable

data class EvidenceItem(
    val type: String,
    val typeClass: String,    // "r", "a"
    val time: String,
    val text: String
) : Serializable
