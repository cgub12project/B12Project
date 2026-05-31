# F.L.A.S.H. — 詐騙感知防護系統

![Android](https://img.shields.io/badge/Android-API_26%2B-green)
![Kotlin](https://img.shields.io/badge/Kotlin-1.9-blue)
![Version](https://img.shields.io/badge/Version-6.0-orange)

**Fraud Linked Alert System Hub** — 一款 AI 驅動的 Android 詐騙防護 App，能即時監控使用者的訊息、郵件及來電，透過後端 AI 引擎分析詐騙風險，並提供社群情報共享、詐騙回報與警告分享功能。

## 目錄

- [系統概述](#系統概述)
- [核心功能](#核心功能)
- [系統架構](#系統架構)
- [技術棧](#技術棧)
- [畫面總覽](#畫面總覽)
- [後端 API](#後端-api)
- [資料庫設計](#資料庫設計)
- [專案結構](#專案結構)
- [安裝與執行](#安裝與執行)
- [實作進度](#實作進度)
- [UML 分析文件](#uml-分析文件)
- [作者](#作者)

---

## 系統概述

近年來詐騙手法日益多元，從假冒政府機關、投資詐騙到交友詐騙（殺豬盤），受害者遍及各年齡層。現有的防詐工具大多僅提供被動式的電話號碼查詢，缺乏對訊息內容的即時分析與社群協作機制。

**F.L.A.S.H.** 針對此問題提出整合式解決方案：

- **即時偵測** — AI 分析來自 LINE、簡訊、WhatsApp、Messenger 的訊息及 Gmail、Outlook 的郵件，自動判定詐騙風險等級（高危／可疑／安全）
- **社群防護** — 用戶可回報詐騙電話號碼與可疑社群帳號，建立共享情報資料庫
- **主動預警** — 來電辨識、高危警報通知、每日安全報告
- **證據追溯** — 對話時序分析、詐騙階段標記（建立信任期→引導匯款）、AI 證據摘要

### 風險三級制

| 等級 | 顏色 | 說明 |
|------|------|------|
| **高危（high）** | 紅色 `#FF3B30` | 明確詐騙行為（引導匯款、釣魚連結等） |
| **可疑（mid）** | 橘色 `#FF9500` | 疑似詐騙（情感操控、可疑話術等） |
| **安全（safe）** | 綠色 `#34C759` | 正常訊息 |

---

## 核心功能

### 認證模組

- **Email 登入／註冊** — 密碼強度即時指示器（弱／中／強三段式視覺化）、條款同意勾選
- **忘記密碼** — 三步驟流程：輸入 Email → 6 位 OTP 驗證（自動跳欄）→ 設定新密碼
- **社交登入** — Google Credential Manager 整合、Facebook OAuth 入口
- **Token 管理** — JWT（access_token + refresh_token）儲存於 SharedPreferences，支援保持登入

### 訊息警報（Messages）

- 顯示所有監控訊息的詐騙警報列表，含高危／可疑／安全統計摘要
- **雙重篩選**：依風險等級（high / mid / safe）+ 依來源平台（LINE / 簡訊 / WhatsApp / Messenger）
- 未讀計數 Badge + 全部已讀按鈕
- 點擊進入對話詳情頁，查看 AI 分析結果

### 郵件警報（Email）

- 監控 Gmail、Outlook 的釣魚郵件與詐騙郵件
- 顯示寄件人、主旨、預覽、風險等級
- 依郵件供應商篩選

### 電話查詢（Phone）

- 電話號碼詐騙資料庫，即時搜尋過濾
- 顯示風險等級、詐騙類型、社群舉報次數
- 點擊查看詳情頁：社群回報列表 + 撥打／封鎖／回報／分享操作

### 對話詳情分析

- **階段式聊天呈現** — 訊息依詐騙階段分組（如「建立信任期」→「引導匯款」），階段分隔線以紅色（高危）、橘色（可疑）區分
- **AI 風險標記** — 每條可疑訊息標注風險原因（如「假獲利保證」「製造緊迫感」）
- **風險評分** — 0-100 分的風險環形進度條，搭配顏色編碼
- **觸發規則** — 列出 AI 偵測到的詐騙模式標籤

### 帳號威脅檔案

- 可疑帳號的風險環形圖（0-100 分）
- 觸發規則列表（紅色標籤）
- 證據摘要：每項證據含類型、嚴重度、時間標記、描述
- 操作按鈕：封鎖並回報、分享警告

### 詐騙回報

- **電話號碼回報**（ReportBottomSheet）— 7 種詐騙類型 Chip 選擇 + 描述文字（至少 10 字）→ API 提交
- **帳號回報**（MessageReportBottomSheet）— 詐騙類型 + 5 種平台選擇（LINE / Facebook / Instagram / WhatsApp / Telegram）+ 帳號資訊 → API 提交
- **完整回報**（ReportFullActivity）— 詐騙類型 + 附加證據 + 事件描述 → 產生案件編號

### 分享警告

- 自動產生警告文字（含號碼、詐騙類型、舉報次數）
- 一鍵分享到 LINE、WhatsApp、Messenger、SMS
- 複製到剪貼簿

### 設定

- 個人資料顯示（名稱、Email）
- 9 項設定開關：訊息監控、郵件掃描、來電辨識、快速登入（生物辨識）、高危警報、每日報告、更改密碼、隱私與數據、登出

---

## 系統架構

```
┌─────────────────────────────────────────────────────┐
│                  Android App (Kotlin)                │
│  ┌───────────┐  ┌───────────┐  ┌──────────────────┐ │
│  │  UI Layer │  │  Adapters │  │ Network (Retrofit)│ │
│  │ Activity/ │  │ Message/  │  │ AuthApi / Report- │ │
│  │ Fragment/ │  │ Email/    │  │ Api / ApiClient / │ │
│  │ Dialog    │  │ Phone/    │  │ TokenManager      │ │
│  │           │  │ Chat/     │  │                   │ │
│  │           │  │ Evidence  │  │                   │ │
│  └─────┬─────┘  └─────┬─────┘  └────────┬─────────┘ │
│        │              │                 │            │
│  ┌─────▼──────────────▼───┐  ┌──────────▼─────────┐ │
│  │   Data Layer           │  │  Local Storage     │ │
│  │   (Models / SampleData)│  │  (SharedPreferences │ │
│  │                        │  │   / SQLite 快取)    │ │
│  └────────────────────────┘  └────────────────────┘ │
└────────────────────┬────────────────────────────────┘
                     │ HTTPS (JWT Bearer Token)
                     ▼
         ┌───────────────────────────┐
         │   FastAPI 後端伺服器       │
         │   (Cloudflare Tunnel)     │
         │  ┌─────────────────────┐  │
         │  │ Auth API (6 端點)   │  │
         │  │ Report API (2 端點) │  │
         │  │ AI 分析引擎         │  │
         │  └──────────┬──────────┘  │
         │             │             │
         │  ┌──────────▼──────────┐  │
         │  │   Database          │  │
         │  │   (15 張資料表)     │  │
         │  └─────────────────────┘  │
         └───────────────────────────┘
```

---

## 技術棧

### 前端（Android App）

| 分類 | 技術 | 版本 |
|------|------|------|
| 語言 | Kotlin | 1.9+ |
| 最低 SDK | Android 8.0 (API 26) | — |
| 目標 SDK | Android 14 (API 34) | — |
| JVM | Java 17 | — |
| UI 框架 | Material Design 3 | 1.11.0 |
| 佈局綁定 | View Binding | — |
| 導航 | AndroidX Navigation | 2.7.6 |
| 列表元件 | RecyclerView | 1.3.2 |
| 網路層 | Retrofit 2 + OkHttp 4 | 2.9.0 / 4.12.0 |
| JSON 序列化 | Gson | 2.9.0 |
| 生物辨識 | AndroidX Biometric | 1.1.0 |
| Google 登入 | Credential Manager + Google ID | 1.3.0 / 1.1.1 |

### 後端

| 分類 | 技術 |
|------|------|
| 框架 | FastAPI (Python) |
| 認證 | JWT (access_token + refresh_token) |
| 部署 | Cloudflare Tunnel |

---

## 畫面總覽

本 App 包含 **10 個 Activity**、**4 個 Fragment**、**5 個 Dialog/BottomSheet**，共 **28 個 XML 佈局檔**。

### 認證流程

| 畫面 | 說明 |
|------|------|
| SplashActivity | 啟動畫面，動畫進度條（0→100%）後導向登入頁 |
| LoginActivity | Email/密碼登入 + 保持登入開關 + Google/Facebook OAuth 入口 |
| RegisterActivity | 註冊表單，含密碼強度即時指示器（三段式視覺化） |
| ForgotPasswordActivity | 三步驟忘記密碼（ViewFlipper 切換）：Email → OTP → 新密碼 |
| GooglePickerActivity | Google Credential Manager 整合 |
| FacebookPickerActivity | Facebook 帳號選擇頁 |

### 主要頁面（底部導航四頁籤）

| 頁籤 | Fragment | 功能 |
|------|----------|------|
| 訊息警報 | MessagesFragment | 詐騙訊息警報列表 + 統計摘要 + 雙重篩選 |
| 郵件警報 | EmailFragment | 郵件威脅警報 + 供應商篩選 |
| 電話 | PhoneFragment | 電話號碼資料庫 + 即時搜尋 |
| 設定 | SettingsFragment | 個人資料 + 9 項設定開關 + 登出 |

### 詳情與操作頁面

| 畫面 | 說明 |
|------|------|
| ThreadDetailActivity | 對話詳情：階段式聊天氣泡 + AI 風險標記 + 模式標籤 |
| AccountDetailActivity | 帳號威脅檔案：風險環形圖 + 觸發規則 + 證據摘要 |
| PhoneDetailActivity | 電話詳情：社群回報列表 + 撥打/封鎖/回報/分享 |
| ShareWarningActivity | 警告分享：自動生成警告文字 + 多平台一鍵分享 |
| ReportBottomSheet | 電話號碼回報表單（BottomSheet） |
| MessageReportBottomSheet | 帳號/訊息回報表單（BottomSheet） |
| ResultDialog | 通用結果對話框（成功/失敗回饋） |

---

## 後端 API

### 認證端點

| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/api/v1/auth/login` | 登入，回傳 JWT |
| POST | `/api/v1/auth/register` | 註冊，回傳 JWT |
| POST | `/api/v1/auth/forgot-password` | 發送 OTP 到 Email |
| POST | `/api/v1/auth/verify-otp` | 驗證 6 位 OTP |
| POST | `/api/v1/auth/reset-password` | 重設密碼 |
| POST | `/api/v1/auth/oauth` | 社交登入（Google / Facebook） |

### 回報端點

| 方法 | 路徑 | 認證 | 說明 |
|------|------|------|------|
| POST | `/api/v1/reports/phone/{phone_number}` | Bearer Token | 回報詐騙電話號碼 |
| POST | `/api/v1/reports/account` | Bearer Token | 回報可疑社群帳號 |
| GET | `/api/v1/reports/mine` | Bearer Token | 查詢個人回報紀錄 |

### 回報請求欄位

**電話回報（PhoneReportRequest）**：

| 欄位 | 必填 | 說明 |
|------|------|------|
| `fraud_type` | 是 | 詐騙類型（7 種之一，或自訂） |
| `content` | 是 | 回報內容（至少 10 字） |
| `description` | 否 | 補充說明 |

**帳號回報（MessageReportBody）**：

| 欄位 | 必填 | 說明 |
|------|------|------|
| `fraud_type` | 是 | 詐騙類型 |
| `content` | 是 | 回報內容（至少 10 字） |
| `platform` | 是 | 平台（LINE / Facebook / Instagram / WhatsApp / Telegram） |
| `account_name` | 是 | 帳號名稱 |
| `account_id` | 否 | 帳號 ID |
| `description` | 否 | 補充說明 |

---

## 資料庫設計

系統共規劃 **15 張資料表**，依存放位置分類如下：

| 分類 | 數量 | 資料表 |
|------|------|--------|
| **純 Server** | 7 張 | users、user_auth_providers、password_reset_tokens、suspect_accounts、evidence_items、phone_numbers、phone_reports |
| **SQLite + Server 雙寫** | 6 張 | user_settings、messages、message_threads、thread_messages、emails、blocked_contacts |
| **純 SQLite** | 1 張 | share_logs |
| **Server + SQLite 草稿** | 1 張 | fraud_reports |

### 存放位置設計原則

- **純 Server** — 核心認證資料（密碼雜湊不可存本地）、跨用戶共享情報（多用戶共享的詐騙資料庫）、需後台審核的資料
- **SQLite + Server 雙寫** — 離線可用的快取資料（訊息、郵件、設定偏好），有網路時從 Server 同步
- **純 SQLite** — 個人操作紀錄（分享記錄），不涉及跨用戶共享

### 各頁面與資料表對應

| 介面頁面 | 主要使用資料表 | 存放位置 |
|---------|---------------|---------|
| 登入 / 註冊 | users, user_auth_providers | Server |
| 忘記密碼 | users, password_reset_tokens | Server |
| 訊息主頁 | messages | SQLite + Server |
| 對話詳情 | message_threads, thread_messages | SQLite + Server |
| 帳號威脅檔案 | suspect_accounts, evidence_items | Server |
| 郵件頁 | emails | SQLite + Server |
| 電話頁 / 電話詳情 | phone_numbers, phone_reports | Server |
| 設定頁 | users, user_settings | Server / SQLite + Server |
| 回報功能 | phone_reports, fraud_reports | Server |
| 分享警告 | share_logs | SQLite |

---

## 專案結構

```
FLASH-App/
├── README.md                          # 本文件
├── build.gradle.kts                   # 專案層級 Gradle 配置
├── settings.gradle.kts                # Gradle 設定
├── gradle/                            # Gradle Wrapper
├── 資料庫需求規劃.txt                   # 15 張資料表完整欄位定義
├── 後端api.txt                         # 後端 API 文件位址
└── app/
    ├── build.gradle.kts               # App 模組 Gradle 配置（依賴項宣告）
    ├── proguard-rules.pro             # ProGuard 混淆規則
    └── src/main/
        ├── AndroidManifest.xml        # 應用程式清單（10 Activity、權限宣告）
        ├── java/com/frauddetector/
        │   ├── ui/
        │   │   ├── auth/              # 認證模組
        │   │   │   ├── SplashActivity.kt          # 啟動畫面（進度條動畫）
        │   │   │   ├── LoginActivity.kt           # 登入頁（Email + OAuth）
        │   │   │   ├── RegisterActivity.kt        # 註冊頁（密碼強度指示器）
        │   │   │   ├── ForgotPasswordActivity.kt  # 忘記密碼（3 步驟 ViewFlipper）
        │   │   │   ├── GooglePickerActivity.kt    # Google Credential Manager
        │   │   │   └── FacebookPickerActivity.kt  # Facebook 帳號選擇
        │   │   ├── main/              # 主畫面模組
        │   │   │   ├── MainActivity.kt            # 主畫面（底部導航容器）
        │   │   │   ├── MessagesFragment.kt        # 訊息警報頁籤
        │   │   │   ├── EmailFragment.kt           # 郵件警報頁籤
        │   │   │   ├── PhoneFragment.kt           # 電話查詢頁籤
        │   │   │   └── SettingsFragment.kt        # 設定頁籤
        │   │   ├── detail/            # 詳情模組
        │   │   │   ├── ThreadDetailActivity.kt    # 對話詳情（階段式聊天）
        │   │   │   ├── AccountDetailActivity.kt   # 帳號威脅檔案（風險環形圖）
        │   │   │   ├── PhoneDetailActivity.kt     # 電話詳情（社群回報）
        │   │   │   ├── ReportFullActivity.kt      # 完整回報表單
        │   │   │   └── ShareWarningActivity.kt    # 分享警告（多平台）
        │   │   └── dialog/            # 彈窗模組
        │   │       ├── ReportBottomSheet.kt       # 電話回報表單（API 串接）
        │   │       ├── MessageReportBottomSheet.kt # 帳號回報表單（API 串接）
        │   │       ├── ResultDialog.kt            # 結果對話框（成功/失敗）
        │   │       ├── QuickSetupDialog.kt        # 快速登入設定引導
        │   │       └── QuickLoginBottomSheet.kt   # 生物辨識快速登入
        │   ├── adapter/               # RecyclerView 適配器
        │   │   ├── MessageAdapter.kt              # 訊息列表（色彩編碼邊框 + 標籤）
        │   │   ├── EmailAdapter.kt                # 郵件列表（供應商篩選）
        │   │   ├── PhoneAdapter.kt                # 電話列表（風險等級樣式）
        │   │   ├── ChatAdapter.kt                 # 聊天氣泡（階段分隔 + 原因標籤）
        │   │   ├── ReportAdapter.kt               # 社群回報列表
        │   │   └── EvidenceAdapter.kt             # 證據摘要列表
        │   ├── network/               # 網路層
        │   │   ├── ApiClient.kt                   # Retrofit 單例（OkHttp + Gson）
        │   │   ├── ApiConfig.kt                   # API 基礎 URL 配置
        │   │   ├── AuthApi.kt                     # 認證 API 介面（6 端點）
        │   │   ├── ReportApi.kt                   # 回報 API 介面（2 端點）
        │   │   ├── AuthModels.kt                  # 認證請求/回應模型
        │   │   ├── ReportModels.kt                # 回報請求模型
        │   │   └── TokenManager.kt                # JWT Token 管理（SharedPreferences）
        │   └── data/                  # 資料層
        │       ├── Models.kt                      # 核心資料類別（9 個 data class）
        │       └── SampleData.kt                  # 模擬資料（開發/展示用）
        └── res/
            ├── layout/                # 28 個 XML 佈局檔
            ├── drawable/              # 圖示與 Drawable 資源
            ├── menu/                  # 底部導航選單
            ├── navigation/            # 導航圖
            ├── values/                # 字串、色彩、主題定義
            └── mipmap-*/              # 各解析度 App 圖示
```

---

## 安裝與執行

### 環境需求

- Android Studio Hedgehog (2023.1) 或以上
- JDK 17
- Android SDK 34
- 實體裝置或模擬器（API 26+）

### 建置步驟

```bash
git clone <repository-url>
cd FLASH-App
```

以 Android Studio 開啟專案，等待 Gradle Sync 完成後，選擇裝置並點擊 **Run**。

### 測試帳號

App 內建模擬資料（`SampleData.kt`），可直接瀏覽所有功能畫面。如需測試 API 串接，可透過後端 API 註冊帳號。

### 權限

| 權限 | 用途 |
|------|------|
| `INTERNET` | 網路存取（API 通訊） |
| `USE_BIOMETRIC` | 生物辨識快速登入 |

---

## 實作進度

### 已完成功能

| 模組 | 功能 | API 串接 |
|------|------|----------|
| 認證 | 登入 / 註冊 / 忘記密碼（3 步驟）/ OAuth 入口 | ✅ 已串接 |
| 訊息頁 | 警報列表 + 統計摘要 + 雙重篩選 + 全部已讀 | 模擬資料 |
| 對話詳情 | 階段式聊天氣泡 + AI 風險標記 + 模式標籤 | 模擬資料 |
| 帳號威脅檔案 | 風險環形圖 + 觸發規則 + 證據摘要 | 模擬資料 |
| 郵件頁 | 警報列表 + 供應商篩選 | 模擬資料 |
| 電話頁 | 號碼資料庫 + 即時搜尋 | 模擬資料 |
| 電話詳情 | 社群回報列表 + 操作按鈕 | 模擬資料 |
| 電話回報 | 詐騙類型 + 描述 → 提交 | ✅ 已串接 |
| 帳號回報 | 詐騙類型 + 平台 + 帳號資訊 → 提交 | ✅ 已串接 |
| 分享警告 | 警告文字生成 + 多平台分享 + 剪貼簿 | ✅ 本地完成 |
| 設定頁 | 個人資料 + 9 項設定 + 登出 | 部分完成 |

### 待實作功能

| 功能 | 說明 |
|------|------|
| 訊息即時監控 | 後台 Service 監控 LINE/SMS/WhatsApp/Messenger |
| 來電辨識 | CallScreeningService 整合 |
| 生物辨識快速登入 | AndroidX Biometric 完整整合 |
| SQLite 離線快取 | Room 取代 SampleData，實現離線瀏覽 |
| 郵件搜尋 | EmailFragment 搜尋功能 |
| 證據上傳 | 完整回報表單的附件上傳 |
| 儲存警告圖片 | ShareWarningActivity 截圖儲存 |

### 成果說明

本專題已完成 **完整的前端 UI 實作**，涵蓋 10 個 Activity、4 個 Fragment、5 個 Dialog/BottomSheet，共 36 個 Kotlin 原始碼檔案與 28 個 XML 佈局檔。認證模組（登入、註冊、忘記密碼）及回報模組（電話回報、帳號回報）已與 FastAPI 後端完成 API 串接，可實際運作。其餘畫面以模擬資料呈現完整的使用者體驗流程，資料層設計上採用可替換架構，待後端 AI 分析引擎就緒後，可直接將 SampleData 替換為真實 API 呼叫而無需修改 UI 層程式碼。

---

## UML 分析文件

本專題附有完整的 UML 軟體分析報告，涵蓋以下圖形：

| UML 圖 | 說明 |
|---------|------|
| 使用案例圖（Use Case Diagram） | 系統功能總覽，識別 4 個 Actor 與所有 Use Case |
| 活動圖（Activity Diagram） | 登入流程、密碼重設流程、訊息調查流程、電話查詢流程 |
| 類別圖（Class Diagram） | 系統領域問題類別圖（認證、訊息/郵件、電話/回報、總覽） |

---

## 作者

- **B1229003** — UI/UX開發（Android App / UI）
- **B1229026** — 後端開發（API / Server）
- **B1229042** — AI開發（AI 相關）
- **B1229067** — 介面開發（Android App / UI / API 串接）

---

## 指導教授

- **李春良 教授** —

