# F.L.A.S.H. 後端系統

**Fraud Locator And Scam Hunter** — 詐騙感知防護系統的 FastAPI 後端，提供認證、詐騙情報查詢、社群回報，以及 **RAG 詐騙訊息偵測**（EmbeddingGemma 向量檢索 + ChromaDB + Ollama 本地 LLM）。

> 📌 **[docs/VERSIONS.md](docs/VERSIONS.md)** — 版本紀錄：後端 commit／alembic、模型（sha256、
> 大小、成績、換版理由）、提示詞、資料集、向量庫與門檻參數的對照表，含「哪些東西必須一起換」
> 與各種換版 checklist。**動任何一顆模型、提示詞或資料集之前先看這份。**
>
> 📄 **[docs/flash_backend_overview.html](docs/flash_backend_overview.html)** — 系統總覽網頁版：
> 偵測／階段管線圖、API 地圖、現行模型成績，以及 `scripts/` 全部 38 支程式的用途、指令與注意事項
> （可直接用瀏覽器開啟，附關鍵字篩選）。本 README 仍是設定與決策脈絡的正本。

## 目錄

**先讀這裡** · [技術棧](#技術棧) · [專案結構](#專案結構) · [資料庫設計](#資料庫設計後端負責的-11-張資料表) · [API 端點總覽](#api-端點總覽)

**核心功能** · [RAG 詐騙偵測](#rag-詐騙偵測rag-新增功能) · [相似度一致性閘門](#相似度一致性閘門可於-env-調整) · [詐騙階段判定](#詐騙階段判定post-ragdetect-conversation) · [信箱連接](#信箱連接mail-新增功能) · [地端模型下載](#地端模型下載local-model-新增功能)

**跑起來** · [安裝與執行](#安裝與執行) · [執行測試](#執行測試) · [GPU 效能設計](#gpu-效能設計說明)

**調校與評測** · [現行模型與成績](#現行模型與成績) · [換／比較嵌入模型](#更換比較嵌入模型ab) · [有無 RAG 的 A/B](#有無-rag-的-ab-比較rag_enabled) · [風險分數校準](#風險分數校準risk_score) · [向量庫維護](#向量庫維護) · [scripts 總覽](#scripts-目錄總覽)

**其他** · [安全設計摘要](#安全設計摘要)

## 技術棧

| 分類 | 技術 |
|------|------|
| 語言 | Python 3.12 |
| Web 框架 | FastAPI（完全非同步架構） |
| 資料庫 | MySQL 8（驅動：aiomysql） |
| ORM | SQLAlchemy 2.0（async + Mapped 型別宣告） |
| 遷移 | Alembic（非同步 env） |
| 認證 | JWT（access_token + refresh_token，PyJWT + bcrypt） |
| 向量嵌入 | google/embeddinggemma-300m（sentence-transformers，**GPU / BF16 加速**） |
| 向量資料庫 | ChromaDB（本地持久化，餘弦相似度） |
| 本地 LLM | Ollama：偵測 `flash_v6`（Breeze2 微調）、階段 `flash_stage_v5`（可於 `.env` 調整） |
| 測試 | pytest + pytest-asyncio + aiosqlite（免 MySQL） |

## 專案結構

```
flash_backend/
├── app/
│   ├── main.py                  # FastAPI 進入點（路由掛載、CORS、lifespan）
│   ├── api/
│   │   ├── dependencies.py      # 共用相依性（DB Session、JWT 使用者、RAG 金鑰）
│   │   └── endpoints/           # auth / users / phones / accounts / reports / rag /
│   │                            # mail / local_model
│   ├── core/
│   │   ├── config.py            # pydantic-settings 設定（讀取 .env）
│   │   ├── crypto.py            # 信箱 refresh_token 的對稱加密（Fernet）
│   │   └── security.py          # bcrypt、JWT、OTP、案件編號
│   ├── crud/                    # 資料存取層（全部 async）
│   ├── db/                      # Base、非同步 engine / session
│   ├── models/                  # SQLAlchemy 2.0 ORM 模型（11 張資料表）
│   ├── schemas/                 # Pydantic 請求／回應 Schema
│   ├── prompts/                 # LLM 提示詞資源檔（偵測＝微調契約、詐騙階段）
│   ├── services/                # Email(OTP)、OAuth、RAG（EmbeddingGemma+Chroma+Ollama）、
│   │                            # 詐騙階段判定（stage_service）、共用 Ollama 呼叫、
│   │                            # 信箱連接（mail_oauth / mail_provider / mail_sync）、
│   │                            # 地端模型分發（local_model）
│   └── tests/                   # 單元測試（SQLite 記憶體資料庫）
├── alembic/                     # 資料庫遷移（0001 初始、0002 信箱連接）
├── rag_worker.py                # ★ RAG 向量入庫程式（獨立長駐程序；--once/--prune 可手動重新同步）
├── risk_calibration.json        # risk_score 校準表（app 執行期讀取，由腳本擬合產生）
├── scripts/                     # 離線工具共 4 支，一律以 `python -m scripts.xxx` 在專案根目錄執行
├── data/                        # 資料集（進 git）
│   ├── vector_db.jsonl              # RAG 知識庫來源，rag_worker 由此入庫
│   ├── test.jsonl                   # 帶標籤測試集
│   ├── stage_finetune.jsonl         # 詐騙對話階段模型微調訓練資料
│   └── finetune.jsonl               # 詐騙判斷模型微調訓練資料
├── eval/                        # 評測／稽核產出
│                                # 只有指標摘要 .txt 保留為實驗紀錄
├── models/                      # GGUF 權重與 LoRA 產出（不進 git，見 .gitignore）
├── alembic.ini / .env.example / requirements.txt / pytest.ini
└── README.md
```

> **模型要從專案根目錄建**：`ollama create flash_v6 -f modelfiles/Modelfile.v6`。
> Modelfile 裡的 `FROM ../models/…` 是相對於 **Modelfile 自己的目錄**解析的
> （已實測），所以 `modelfiles/` 與 `models/` 必須維持同一層的相對位置。

> `scripts/` 下的工具都 `from app.core.config import settings`，因此必須用
> `python -m scripts.xxx` 形式在 **專案根目錄** 執行；直接 `python scripts/xxx.py`
> 會找不到 `app` 套件。各腳本的預設輸入／輸出路徑都錨定在專案根目錄，
> 不受當下工作目錄影響。

## 資料庫設計（後端負責的 11 張資料表）

依系統規劃，**messages、message_threads、thread_messages、emails、blocked_contacts、share_logs 為 App 端純 SQLite**，後端不處理。後端資料表如下：

| 資料表 | 用途 |
|--------|------|
| `users` | 使用者主檔（密碼 bcrypt 雜湊，僅存 Server） |
| `user_auth_providers` | 社交登入綁定（Google / Facebook） |
| `password_reset_tokens` | 忘記密碼 OTP（SHA-256+pepper 雜湊）與一次性重設權杖 |
| `user_settings` | 設定頁 6 個開關（App SQLite 雙寫的同步來源） |
| `phone_numbers` | 詐騙電話號碼共享情報（風險等級、舉報次數） |
| `phone_reports` | 電話社群回報 |
| `suspect_accounts` | 可疑帳號檔案（風險評分 0-100、觸發規則、AI 摘要） |
| `evidence_items` | 帳號威脅檔案的證據摘要 |
| `fraud_reports` | 帳號回報（AC-案件編號）與完整回報（FR-案件編號） |
| `mail_accounts` | 已連接的 Gmail／Outlook 信箱（refresh_token **加密**儲存） |
| `mail_analysis` | 每封信的 AI 判定結果（**不含**主旨／寄件者／內文，見下） |

## API 端點總覽

原始文件僅列出認證 6 端點與回報 3 端點；以下 **粗體** 為依功能需求自行補齊的端點。所有端點統一掛載於 `/api/v1`，完整互動文件見 Swagger UI（`/docs`）。

### 認證（`/auth`）

| 方法 | 路徑 | 認證 | 說明 |
|------|------|------|------|
| POST | `/auth/register` | — | 註冊，回傳 JWT |
| POST | `/auth/login` | — | 登入，回傳 JWT |
| POST | `/auth/forgot-password` | — | 發送 6 位 OTP 到 Email |
| POST | `/auth/verify-otp` | — | 驗證 OTP，核發一次性 reset_token |
| POST | `/auth/reset-password` | — | 以 reset_token 重設密碼 |
| POST | `/auth/oauth` | — | 社交登入（Google id_token / Facebook access_token） |
| **POST** | **`/auth/refresh`** | — | 以 refresh_token 換發新權杖組 |
| **POST** | **`/auth/change-password`** | Bearer | 設定頁「更改密碼」 |
| **POST** | **`/auth/logout`** | Bearer | 登出（JWT 無狀態，用戶端刪除權杖） |

### 使用者（`/users`）— 設定頁功能

| 方法 | 路徑 | 認證 | 說明 |
|------|------|------|------|
| **GET** | **`/users/me`** | Bearer | 個人資料（名稱、Email） |
| **PATCH** | **`/users/me`** | Bearer | 更新名稱／頭像 |
| **GET** | **`/users/me/settings`** | Bearer | 取得 6 個設定開關 |
| **PUT** | **`/users/me/settings`** | Bearer | 更新設定開關（部分更新） |

### 電話查詢（`/phones`）— 電話頁／電話詳情頁

| 方法 | 路徑 | 認證 | 說明 |
|------|------|------|------|
| **GET** | **`/phones`** | Bearer | 號碼列表（`search` 即時搜尋、`risk_level` 篩選、分頁） |
| **GET** | **`/phones/{phone_number}`** | Bearer | 電話詳情 + 社群回報列表（回報者已遮罩） |

### 可疑帳號（`/accounts`）— 帳號威脅檔案頁

| 方法 | 路徑 | 認證 | 說明 |
|------|------|------|------|
| **GET** | **`/accounts`** | Bearer | 可疑帳號列表（`platform` 篩選、`search`、分頁） |
| **GET** | **`/accounts/{account_id}`** | Bearer | 威脅檔案：風險評分環形圖、觸發規則、證據摘要 |

### 詐騙回報（`/reports`）

| 方法 | 路徑 | 認證 | 說明 |
|------|------|------|------|
| POST | `/reports/phone/{phone_number}` | Bearer | 回報詐騙電話（自動建檔並更新風險等級） |
| POST | `/reports/account` | Bearer | 回報可疑帳號（回傳 AC- 案件編號） |
| **POST** | **`/reports/full`** | Bearer | 完整回報（ReportFullActivity，回傳 FR- 案件編號） |
| GET | `/reports/mine` | Bearer | 個人回報紀錄（合併三種回報） |

### RAG 詐騙偵測（`/rag`）— 新增功能

| 方法 | 路徑 | 認證 | 說明 |
|------|------|------|------|
| **GET** | **`/rag/reports`** | X-API-Key | 供 `rag_worker.py` 輪詢新使用者回報（`since` 增量查詢） |
| **POST** | **`/rag/detect`** | Bearer | 偵測訊息：EmbeddingGemma 向量化 → ChromaDB 取相似候選 → 一致性閘門 →（閘門放行時）Ollama LLM 判斷 |
| **POST** | **`/rag/detect-conversation`** | Bearer | 對話級偵測：同上 + 判斷對話演進到哪個**詐騙階段**（見下） |

`/rag/detect` 回應範例：

```json
{
  "is_scam": true,
  "risk_level": "high",
  "scam_type": "假投資詐騙",
  "confidence": 0.93,
  "risk_score": 0.95,
  "reasons": ["假獲利保證", "引導加入群組"],
  "advice": "請勿依對方指示匯款，可撥打 165 反詐騙專線查證。",
  "similar_cases": [
    {"content": "恭喜您獲得投資群組免費名額...", "scam_type": "投資詐騙", "similarity": 0.91}
  ],
  "model": "flash_v6"
}
```

> **`confidence` 與 `risk_score` 不是同一件事，前端要顯示風險請用 `risk_score`。**
> `confidence` 是「模型對這個判斷的把握」——`is_scam: false` 搭配 `confidence: 0.95`
> 的意思是「很確定安全」，拿去畫風險條會變成滿格紅色。`risk_score` 才是校準過的
> 詐騙機率（0-1，可當機率解讀、可跨判定來源排序），由 `fit_risk_calibration.py`
> 從評測結果以等張迴歸擬合而得。校準表與特定模型綁定，換模型後未重新擬合時
> 此欄位為 `null`（詳見 `app/services/risk_calibration.py`）。

> **`similar_cases` 的門檻與提示詞注入分開。** 注入提示詞用的是
> `RAG_CASE_SIMILARITY_THRESHOLD`（0.559，釘在訓練契約上不可亂動），回應呈現則在
> 注入那組為空時改用 `RAG_DISPLAY_SIMILARITY_THRESHOLD`（0.35，與閘門判定門檻同級）。
> 兩者共用一個門檻時，判定成立（只要 0.35）而佐證案例卻被 0.559 卡掉，使用者會收到
> 「高風險 + 空陣列」——1,983 筆實測有 31.7% 落在這個空窗，其中 508 筆還是閘門直接
> 判定的。只有庫中確實找不到超過顯示門檻的案例（或 `RAG_ENABLED=false`）才會是 `[]`。

`scam_type` 保證是教科書 22 類之一或 `null`：類別清單由 system prompt 解析後
灌進 Ollama structured outputs 的 `enum`，在解碼階段就擋掉模型自創的類別
（未加 `enum` 前，2000 筆評測會出現 12 種教科書外的名稱如「假新聞/謠言」共 14 次）。

> **不要在推論端單方面加提示詞。** 推論輸入必須與 `data/finetune.jsonl` 的訓練輸入逐字
> 一致。曾試著在【任務說明】後補一段「判定邊界」（謠言／防詐提醒／合法交易通知都
> 不是詐騙）想壓低誤報，在 347 筆同型態子集上實測反而更糟：誤報 54 → 67、準確率
> 0.789 → 0.736。要教這類邊界就得寫進微調資料重新訓練，讓訓練與推論一致
> （`app/tests/test_rag.py` 有測試釘住提示詞結尾，避免再被加回去）。

#### 相似度一致性閘門（可於 `.env` 調整）

為節省 LLM 推論成本並加快回應，偵測時先讓「最相似的 N 個鄰居」投票，
只有票不一致的訊息才交給 LLM：

| 最相似的 `RAG_GATE_TOP_N` 筆（預設 3） | 行為 | 回應 `model` 欄位 |
|------|------|------|
| 全部 `> RAG_GATE_SIMILARITY`（預設 0.35）且全為詐騙 | 直接判定 `high`（類型取最相似案例），不呼叫 LLM | `similarity-gate` |
| 全部 `> RAG_GATE_SIMILARITY` 且全為一般訊息 | 直接判定 `safe`，不呼叫 LLM | `similarity-gate` |
| 其餘（票數不齊、有一筆沒過門檻、兩類並存） | 交由 Ollama LLM 綜合判斷 | 如 `flash_v6` |

**這道閘門的準確率是投票給的，不是相似度給的。** 實測兩類樣本的 top-1 相似度
分佈重疊得很嚴重（詐騙中位數 0.641、正常 0.563），單看相似度分不出來；真正
有判別力的是「最相似的幾個鄰居是否一面倒」。在 1,983 筆快取上：

| 規則 | F1 | 準確率 | 閘門覆蓋 | 閘門子集準確 | 漏判 | 誤報 | LLM 呼叫 |
|---|---|---|---|---|---|---|---|
| **N=3, x=0.35（現行）** | **0.9564** | **0.9571** | **77.3%** | 0.978 | **54** | **31** | **450** |
| 舊 LOW=.40/HIGH=.50 區間閘門 | 0.9360 | 0.9370 | 43.6% | 0.978 | 72 | 53 | 1,118 |
| 閘門全關（純 LLM） | 0.8844 | 0.8815 | 0% | — | 87 | 148 | 1,983 |

> ⚠ 「閘門子集準確」的分母是閘門自己判定的那批（不是全體），**不可**與整體
> 準確率或 LLM 的成績直接比大小——閘門挑走的本來就是簡單的那一半。它回答的
> 是「閘門敢判的時候有多準」。

- `N` 是主要變因（2→3 動 F1 0.006），`x` 幾乎是擺設（0.25~0.45 只動 0.003）。
  換嵌入模型時 `x` 可沿用，`N` 請重跑 `--sweep` 確認
- 啟動時檢查 `N ≥ 1`、`0 ≤ x ≤ 1`，且 `N ≤ RAG_RETRIEVE_CANDIDATES`
  （否則閘門永遠湊不齊票、等同被無聲關閉），不合法即啟動失敗
- 候選不足 N 筆時（向量庫太小或剛建好）一律交由 LLM 判斷
- **短訊息的「直接判詐騙」另有一條加嚴規則**（2026-09-19 加入）：去除空白後不超過
  `RAG_GATE_SHORT_MESSAGE_CHARS`（預設 20）字的訊息，要讓閘門直接判詐騙，top-N 必須
  全部嚴格大於 `RAG_GATE_SHORT_SCAM_SIMILARITY`（預設 0.65）；**判安全那一側不變**。
  短句的向量幾乎只由一兩個詞決定，很容易和詐騙話術撞在一起。實測全面拉高門檻會讓
  漏報 41 → 57，所以只套在短訊息這一段；`RAG_GATE_SHORT_MESSAGE_CHARS=0` 即停用此規則
- **沒有**「相似度太低就直接判安全」的分支。那條分支攔下的正是「庫裡沒見過」
  的訊息，而那是最該交給 LLM 的一批（實測它攔下 25 筆、其中 1 筆是真詐騙，
  且完全沒有後手），已於 2026-09-09 移除
- `RAG_ENABLED=false` 時整段檢索與閘門都會跳過（見
  [有無 RAG 的 A/B 比較](#有無-rag-的-ab-比較rag_enabled)）
- LLM 提示詞已針對 3B 等級小模型（如 `qwen2.5:3b`）最佳化：短句條列指令、
  few-shot 範例，並以 Ollama structured outputs（JSON Schema）於解碼階段
  強制回應格式，欄位不會漏填或給錯型別

#### 詐騙階段判定（`POST /rag/detect-conversation`）

偵測回答「是不是詐騙、哪一類」，階段回答第三題：**這段對話演進到哪裡了**。
類型說的是「這是什麼手法」，階段說的是「你現在有多危險、對方下一步要做什麼」——
同一段假投資對話，在「培養信任」只需要提醒，到了「索取財物」就該擋下匯款。

| # | `stage` | 中文 | 話術特徵 |
|---|---------|------|----------|
| 1 | `contact` | 接觸建立 | 陌生來訊、「打錯了」、「我是某某我換號碼了」、自稱客服／專員 |
| 2 | `grooming` | 培養信任 | 閒聊噓寒問暖、曬生活、自稱檢警／老師／分析師建立權威 |
| 3 | `baiting` | 鋪陳誘餌 | 保證獲利、高薪職缺、中獎補助、帳戶異常，邀入群組／導去指定平台 |
| 4 | `extraction` | 索取財物 | 要匯款／提款卡存摺／OTP／個資／點連結登入／買點數／寄件 |
| 5 | `closing` | 收尾拖延 | 出金要保證金稅金、帳戶凍結需解凍、要第二筆以後的款項、事後假冒協助追款 |

請求帶整串對話（`sender` 為 `them` / `me`）與 `previous_stage`；回應是
`/rag/detect` 的全部欄位再加上 `stage` / `stage_label` / `stage_confidence` /
`stage_reasons` / `next_step_warning` / `stage_model`。

##### 這是**獨立的第二段判定**，不是在偵測的提示詞上多加欄位

| 為什麼不改偵測那條線 | |
|---|---|
| `scam_detection_system.txt` 是微調模型的訓練契約 | 推論輸入必須與 `data/finetune.jsonl` 逐字一致（[實測加料反而掉分](#rag-詐騙偵測rag-新增功能)），且有測試釘住 |
| 相似度閘門會完全跳過 LLM | 就算改了提示詞，閘門判定的那些訊息也產不出階段 |
| 階段是「對話」的屬性 | 偵測管線的輸入是單則訊息 |

因此 `/rag/detect` **一行未動**；階段走 `app/prompts/scam_stage_system.txt` 與
`app/services/stage_service.py`，Ollama 呼叫共用抽出的 `app/services/ollama_client.py`。

流程：取**最後一則對方訊息**原文跑既有 `rag.detect()`（結果與直接打 `/rag/detect`
一致，App 可無痛切換）→ 非詐騙且無 `previous_stage` 就不呼叫階段模型（`stage` 回
`null`，省一次推論）→ 關鍵詞規則掃出階段**下界** → 階段模型判定 → 單調性調和 →
取兩者較高者。

##### 三個容易踩的設計點

1. **對話狀態由 App 攜帶，後端不存。** `messages` / `message_threads` 依系統規劃是
   App 端 SQLite，這支端點與 `/rag/detect` 一樣是純 passthrough、不寫任何資料表
   （**不需要 migration**）。把對話存進 DB 等於讓所有有 phpMyAdmin 權限的人
   看得到別人的 LINE 對話，與 `mail_analysis` 不存信件內容是同一條原則。
2. **階段只前進。** 模型只看得到最近 `RAG_STAGE_MAX_MESSAGES` 則，視窗一旦把
   「先匯 30000」那幾則滑掉就會退回「培養信任」，使用者眼中就是風險自己降下來了。
   故只有信心達 `RAG_STAGE_REGRESS_CONFIDENCE` 的回退才採信——這也是 App 必須
   回傳 `previous_stage` 的原因。
3. **`OLLAMA_STAGE_MODEL` 不要指向偵測模型（`flash_v6`／`flash_v4.1`）。** 那些是在「單則訊息 →
   五個固定中文鍵」的窄格式上微調的；structured outputs 鎖得住輸出形狀，鎖不住內容品質。
   目前應指向專屬的階段模型 `flash_stage_v5`；留空則沿用 `OLLAMA_MODEL`（等於踩上面這個坑）。
   **模型與提示詞是綁死的一組**：`flash_stage_v5` 只認訓練時那一份
   `app/prompts/scam_stage_system.txt`，換模型時提示詞檔要一起換。

##### `stage_model` 的四種值

| 值 | 意思 |
|---|---|
| 模型名稱 | 正常判定 |
| `stage-rule` | 階段模型不可用，改由關鍵詞規則／前次階段推估 |
| `stage-unavailable` | 階段模型不可用且無退路，`stage` 為 `null`——**偵測結果照常回傳** |
| `null` | 非詐騙，不需要判階段 |

`stage-unavailable` 與 `null` 刻意分開：否則 `OLLAMA_STAGE_MODEL` 指到一顆沒 pull
的模型時，外部看到的只會是「所有對話都沒有階段」。

##### 設定（`.env`）

| 設定 | 預設 | 說明 |
|---|---|---|
| `RAG_STAGE_ENABLED` | `true` | `false` 時階段一律 `null`，偵測結果照常回傳 |
| `OLLAMA_STAGE_MODEL` | （空） | 判階段的模型；留空沿用 `OLLAMA_MODEL` |
| `RAG_STAGE_MAX_MESSAGES` | 30 | 進提示詞的訊息則數上限（超過由最舊的捨棄）|
| `RAG_STAGE_MAX_CHARS` | 4000 | 進提示詞的對話總字數上限（同上）|
| `RAG_STAGE_REGRESS_CONFIDENCE` | 0.8 | 採信「階段回退」所需的最低信心 |

> **關鍵詞規則只作為下界**，不覆蓋模型往上判的結果，且只掃**對方**的訊息——
> 使用者說「我不會匯款給你」不代表對方索取過。收錄標準是高精確度，刻意排除
> 「帳號」（互留 LINE 帳號是接觸階段的正常行為）與「保證金」（六合彩／假推銷
> 一開口就要保證金，那是索取而非收尾）這類高誤判字眼。

##### 訓練專屬的階段模型

`OLLAMA_STAGE_MODEL` 已指向專屬模型 `flash_stage_v5`（Breeze2 微調，成績見
[現行模型與成績](#現行模型與成績)）。要再訓一顆，**完整的資料管線、腳本順序與
各步驟的理由見 [`docs/stage_model_training.md`](docs/stage_model_training.md)**
（含 Cofacts 取材、版面重建判發送者、不雅照片過濾、弱標註與人工覆核）。

那份文件裡有四件**不照做就會得到假數字**的事，在此列出以免有人只看 README：

1. **要前綴切片，不能只用整段對話。** 對話級標籤有 86% 是「索取財物」，
   用整段訓練等於訓練一個常數輸出。
2. **同一段對話的所有前綴必須落在同一側。** 前綴之間高度重疊，以樣本切分等於洩題。
3. **訓練的 user 訊息由 `StageService.format_user_prompt()` 產生**，不是自己拼字串
   ——本專案已經為「訓練與推論不一致」付過學費（見上方誤報 54→67 那段）。
4. **測試集沒有人工標籤時，數字是假的。** 拿規則去評測產生這些標籤的同一套規則，
   實測 `--rules-only` 是 exact 1.0000；人工答案一進來就掉到 0.41。

### 信箱連接（`/mail`）— 新增功能

連接使用者的 Gmail／Outlook 後，**由後端直接呼叫 Gmail API／Microsoft Graph API 抓信**，
不再依賴手機端攔截系統通知，因此拿得到信件全文，且 App 沒開也會持續更新。

| 方法 | 路徑 | 認證 | 說明 |
|------|------|------|------|
| **GET** | **`/mail/connect/{provider}`** | Bearer | 取得授權網址（App 用瀏覽器／Custom Tab 開啟）|
| **GET** | **`/mail/callback/{provider}`** | — | OAuth 轉址回呼（Google／Microsoft 呼叫，不對 App 開放）|
| **GET** | **`/mail/accounts`** | Bearer | 已連接的信箱列表（含上次同步時間與錯誤）|
| **DELETE** | **`/mail/accounts/{account_id}`** | Bearer | 中斷連接（權杖與判定紀錄一併刪除）|
| **POST** | **`/mail/sync`** | Bearer | 立即同步（打開郵件分頁時呼叫）|
| **GET** | **`/mail/messages`** | Bearer | 已分析的信件列表（`risk_level` 篩選、分頁）|
| **GET** | **`/mail/messages/{analysis_id}/content`** | Bearer | 單封信的完整內容（回報詐騙信時取用）|
| **POST** | **`/mail/accounts/{account_id}/block-sender`** | Bearer | 封鎖寄件人（在 Gmail 端建過濾規則）|
| **GET** | **`/mail/accounts/{account_id}/blocked-senders`** | Bearer | 查詢封鎖名單 |
| **DELETE** | **`/mail/accounts/{account_id}/blocked-senders/{sender}`** | Bearer | 解除封鎖 |

`provider` 為 `gmail` 或 `outlook`。

#### 授權範圍（scope）

| Scope | 用途 |
|-------|------|
| `gmail.readonly` | 讀取收件匣信件（抓信、判定、回報時取全文）|
| `gmail.settings.basic` | 建立／刪除過濾規則（寄件人真封鎖）|

> ⚠️ `gmail.settings.basic` 是後來才加的。在那之前連接的信箱，手上的
> refresh_token 只涵蓋 `gmail.readonly`，封鎖端點會回 **403** 並提示重新連接。
> Google Cloud Console 的 OAuth 同意畫面也要把這個 scope 一併登記，否則
> 授權頁會直接拒絕。

#### 抓信方式：輪詢（決策 1）

| 觸發 | 說明 |
|------|------|
| App 打開郵件分頁 | 呼叫 `POST /mail/sync` 立即同步一次 |
| 背景排程 | 後端每 `MAIL_SYNC_INTERVAL_SECONDS`（預設 300 秒）自動輪詢全體信箱 |

排程是「App 沒開也持續更新」的來源，於 `app/main.py` 的 lifespan 建立為背景工作，
關閉服務時會先停排程再釋放連線池。單一信箱每輪最多分析 `MAIL_SYNC_MAX_MESSAGES` 封。

> 之後若要升級成推播（Gmail Pub/Sub、Outlook webhook），
> `mail_sync.sync_account()` 可直接沿用，只需換掉觸發來源。

##### 增量抓取的時間游標

每次同步只向提供者要「上次同步之後」的信，游標存在 `mail_accounts.last_synced_at`。
這條路徑漏一封信是沒有聲音的（同步照樣回報成功），所以規則寫死在
`mail_sync.resolve_sync_window()` 一處：

| 游標狀態 | 查詢起點 |
|----------|----------|
| `NULL`（首次連接、剛重新授權）| `now - MAIL_SYNC_INITIAL_LOOKBACK_HOURS` |
| 比現在還晚（時鐘或資料異常）| 同上，並記一筆 warning |
| 正常 | `游標 - MAIL_SYNC_OVERLAP_MINUTES` |

三件事分別擋掉三種漏信：**重新授權後沿用舊游標**（斷線期間的信永遠補不回來）、
**游標跑到未來**（`fetched` 永遠是 0、`error` 永遠是 null，看起來像「沒有新信」）、
以及**提供者列表的延遲**（信已送達但還沒進搜尋索引，游標一推進就永久跳過）。
重疊區間重複列到的信由 `provider_message_id` 去重，不會重複分析也不會重複耗 LLM。

Gmail 那邊還多一層：`q=after:` 用的是**日期**（`YYYY/MM/DD`）而非 epoch 秒數，
且再往回退一天。Gmail 的搜尋是以信箱自己設定的時區換算日期的，後端只有 UTC，
用秒級時間戳等於把一個不精確的比較假裝成精確——寧可多列一些舊信讓去重去擋。

`POST /mail/sync` 的每個帳號結果都會回傳 `synced_since`（本次查詢的起點）。
`fetched` 是 0 時先看這一欄，就能分辨「真的沒新信」與「游標壞掉」，
不必連進資料庫查。

##### 失敗分級：什麼情況才停用信箱

| 級別 | 觸發 | 處理 |
|------|------|------|
| 確定失效 | 提供者回 `invalid_grant`、API 回 401 | `is_active=false`，等使用者重新授權 |
| 暫時失敗 | 連不上、5xx、429、權杖解密失敗 | 只記 `last_sync_error`，下一輪自己重試 |

這條界線不能含糊：排程每 5 分鐘打一次 Google 的權杖端點，把所有失敗都當成
「授權失效」的話，跑幾小時就必然撞上一次網路抖動或對方 5xx，外部看到的症狀
就是「Gmail 授權每隔幾小時自己失效、使用者要一直重新連接」。

> Google OAuth 同意畫面若停在 **Testing** 發布狀態，refresh token 只有 7 天效期，
> 這是 Google 端的限制，不是後端能修的。要長期穩定就得把應用送審發布。

#### 資料落地原則（決策 2）：只存判定，不存信件

資料庫是全組（含教授）都連得進去的 phpMyAdmin，因此 `mail_analysis` **刻意不存**
主旨、寄件者、內文與附件——存進去等於任何有 DB 存取權的人都看得到別人的真實信件。

| 存進 `mail_analysis` | 不存 |
|------|------|
| `provider_message_id`（提供者端信件 ID）、`received_at` | 內文 / HTML / 附件 |
| `is_scam`、`risk_level`、`scam_type`、`confidence` | 主旨、寄件者、收件者 |
| `reasons`、`advice`、`model`、`analyzed_at` | — |

列表要顯示的主旨／寄件者／預覽，由 `GET /mail/messages` **當下**呼叫
Gmail API／Graph API 取回（passthrough，只經過記憶體），與資料庫的判定結果
合併後回傳；取不到時該三欄為 `null`、`preview_available` 為 `false`，
判定結果照常顯示。不需要顯示欄位時帶 `include_preview=false` 可省下這段往返。

#### 回報詐騙信：`GET /mail/messages/{analysis_id}/content`

使用者要把一封詐騙信回報進向量資料庫時，光有列表的 200 字預覽片段不夠——
證據是信件全文。這個端點以列表項目的 `id` 取回**該封信的完整內文**，
同樣是即時 passthrough、同樣不落地：

| 欄位 | 說明 |
|------|------|
| `body` / `body_truncated` | 完整純文字內文（HTML 已去標籤）；超過 `MAIL_CONTENT_MAX_CHARS`（預設 20000）時截斷並標記 |
| `report_text` | 已組好「寄件者／主旨／內文」，可直接當 `POST /reports/full` 的 `content` 送出 |
| `scam_type` / `risk_level` / `is_scam` | 資料庫中的判定結果，供回報表單預填 |

`report_text` 的格式刻意對齊 `mail_sync.build_detect_text()`：入庫的案例要和偵測時
餵給模型的文字同結構，之後檢索比對到的才是同一種東西。

與列表端點不同，這裡**取不到內容就回錯誤**（不做欄位留空的降級）——
回報少了信件全文就失去意義：404 找不到紀錄／409 授權失效／502 提供者暫時取不到／
503 後端未設定該提供者憑證。其中 409 只回報不停用信箱，
停用是同步流程（`sync_account`）的職責，避免一次回報就讓使用者的信箱整個斷線。

完整回報鏈路：

    GET /mail/messages/{id}/content  → 拿到 report_text
      → POST /reports/full           → 寫進 reports 資料表
      → GET /rag/reports（rag_worker 輪詢）→ 入 ChromaDB 向量庫

要回報的是**寄件人**而不是這封信時，走既有的 `POST /reports/account`：
`platform` 帶 `"Gmail"`、`account_name` 帶寄件位址。寄件位址是提供者回傳的
真實 email，不像 LINE 顯示名稱可能重複，所以沿用社群帳號那條路不會有
「同名不同人被合併成同一個可疑帳號」的問題。

#### 寄件人真封鎖：Gmail Filters API

App 端的封鎖清單只是把信藏起來，Gmail 信箱本身照收不誤。真封鎖走
`POST /mail/accounts/{account_id}/block-sender`，在 Gmail 端建一條過濾規則：

    criteria: { from: "壞人@example.com" }
    action:   { removeLabelIds: ["INBOX"] }

之後這個寄件人的信不再進收件匣，`list_message_ids` 列不到，也就不會再耗一次
AI 判定。信件本身仍留在「所有郵件」，使用者事後查得到，**不會被刪掉**。

| 設計點 | 理由 |
|--------|------|
| 只認位址、轉小寫（`normalize_sender_address`）| 顯示名稱是寄件人自己填的，改一個字就繞過去了 |
| 先建規則、成功了才落地 | 反過來寫會留下「以為封鎖了、其實沒有」的紀錄 |
| 重複封鎖回 409 | 否則 Gmail 端堆出多條規則，而我們只留得住最後一條的 ID |
| 解除封鎖時 Gmail 端刪失敗就不刪紀錄 | 刪了紀錄＝規則 ID 遺失，使用者以為解除了但信照樣被擋 |
| 同步時比對 `mail_blocked_senders` 先跳過 | 過濾規則從建立到生效有空窗，這段期間的信不該再打擾使用者 |

Outlook 的對應功能是 Graph 的 `messageRules`，尚未實作，該端點會回 **501**。

> ⚠️ `reasons`／`advice` 依專案決定一併儲存。LLM 產生的「分析原因」很可能引述
> 信件原文片段，因此這兩欄實務上要當成「可能含少量信件內容」看待。真的要做到
> 零內容落地，就只存 `risk_level`／`scam_type`，理由於讀取時再生成。
>
> 這個約束由 `app/tests/test_mail.py::test_mail_analysis_stores_no_message_content`
> 把關：日後有人為了方便顯示而加上 `subject`／`body` 欄位，測試會直接失敗。

#### 信件如何進入 AI 判斷

抓到的信件由 `mail_sync.build_detect_text()` 整理成「寄件者 + 主旨 + 內文」
（截斷至 `MAIL_DETECT_MAX_CHARS`），送進與 `/rag/detect` **完全相同**的偵測流程
（向量檢索 → 相似度閘門 →（區間內）Ollama LLM），判定結果寫入 `mail_analysis`。

判斷是**逐封序列**執行的：本機只有一份 Ollama 與一份嵌入模型，且嵌入模型冷啟動
時的併發競爭曾造成相似度全部塌成 ~1.0、每封信都被判成高風險。手動同步與排程同步
共用一把全域鎖，全系統同一時間只會有一次同步在跑。

### 地端模型下載（`/local-model`）— 新增功能

App 的「地端模式」會把 GGUF 模型下載到手機、在手機本機推論；模型不包進 APK，
訊息內容也不會回到後端。後端在這條路徑上**不做任何推論**，只負責驗身分、
核發短效簽章下載網址，以及授權後放行檔案。

| 方法 | 路徑 | 認證 | 說明 |
|------|------|------|------|
| **GET** | **`/local-model/manifest`** | Bearer | 版本、檔名、大小、SHA-256 與短效簽章下載網址 |
| **GET/HEAD** | **`/local-model/download/{file_name}`** | 簽章網址 | 下載模型（支援 Range 續傳、ETag／Last-Modified）|
| **GET** | **`/local-model/authorize`** | 簽章網址 | 只驗簽章回 204，供 Nginx `auth_request`／Caddy `forward_auth` 使用 |

```jsonc
// GET /api/v1/local-model/manifest
{
  "version": "5.0",
  "file_name": "flash-v5.gguf",
  "size_bytes": 2019377248,
  "sha256": "1e4db059dc6398762701d8ab528efe26bea09e314524a376f464fea38285bafa",
  "download_url": "https://models.example.com/api/v1/local-model/download/flash-v5.gguf?token=...",
  "expires_at": "2026-08-19T12:00:00Z"
}
```

#### 為什麼下載授權放在網址裡，而不是 Bearer

下載是 Android 的下載元件發出的請求，App 可能早已被系統回收，那條請求**不會帶
`Authorization` 標頭**（1.93 GB 的下載也不該綁在 30 分鐘就過期的 access token 上）。
所以授權改以簽章內嵌在網址中，並用三件事收斂風險：

- **短效**：預設 24 小時（`LOCAL_MODEL_URL_EXPIRE_HOURS`），足以容納慢速與中斷續傳
- **不可猜測**：JWT 簽章，且 `type=local_model` 與 access token 互不相通——
  拿使用者的 access token 當下載簽章會被擋，反之亦然
- **綁定檔名與版本**：換版後舊網址自動失效，不會下載到已下架的模型

簽章有效期內帳號可能被停用，因此每次下載仍會回資料庫確認帳號狀態（停用回 403）。
網址過期只要重新呼叫 manifest 換一組，**已下載的部分不必重來**（續傳靠 `Range`
+ `ETag`，與簽章無關）。

#### 1.93 GB 不經過 Python

設定 `LOCAL_MODEL_XACCEL_LOCATION` 後，後端驗完簽章只回一組 `X-Accel-Redirect`
標頭，檔案本體由 Nginx 從 internal location 送出（Range／ETag／限速都由 Nginx 處理）；
未設定時退回由 Starlette 的 `FileResponse` 分塊串流——一樣支援 Range、一樣不會把
檔案整包讀進記憶體，但吞吐與併發遠不如 Nginx，只建議開發用。

下載授權內嵌在網址裡，就不能讓它落進存取日誌：後端啟動時會為 `uvicorn.access`
掛上過濾器把 `token=` 換成 `token=REDACTED`，Nginx／Caddy 那層的對應設定見部署文件。

> 部署步驟、Nginx／Caddy 設定範例與逐項驗收指令：**`docs/local_model_deployment.md`**

## 現行模型與成績

數字全部取自 `docs/metrics.json` 與 `eval/` 下的逐筆結果（由 `scripts/collect_eval_metrics.py`
在同一批 id 上重算），不是手打的。

### 偵測（`data/test.jsonl` 1,983 筆，閘門開啟，embeddinggemma-300m）

| 模型 | 準確率 | 精確率 | 召回率 | F1 | 漏報 | 誤報 |
|---|---|---|---|---|---|---|
| **`flash_v6`（Breeze2 微調・現行）** | **0.9637** | 0.9598 | **0.9675** | **0.9636** | **32** | 40 |
| `flash_v4.1`（Qwen2.5-3B 微調） | 0.9592 | 0.9709 | 0.9462 | 0.9584 | 53 | 28 |
| `flash_v5`（Llama3.2 微調） | 0.9561 | 0.9668 | 0.9442 | 0.9554 | 55 | 32 |
| gemma-4-12B（未微調，661 筆子集） | 0.9516 | 0.9574 | 0.9459 | 0.9517 | 18 | 14 |

> **換到 `flash_v6` 的理由不是準確率。** 0.9592 → 0.9612 的差距小到不值得換模型，
> 真正的理由是**漏報 55 → 39**：漏抓會讓使用者被騙，誤報只是多一則提醒，兩種錯的代價不對等。
> 另外 gemma-4-12B 未微調的成績與 3B 微調打平，但推論慢 10–15 倍——這條對照線就是
> 「微調 3B 值不值得」的答案。

當次評測的執行面數字：閘門判定 1,534 筆、LLM 判定 449 筆（準確率 0.9131）、
檢索 61.9 ms/筆、LLM 2.66 秒/筆，全跑完 21.9 分鐘。

> 現行成績含 2026-09-25 給 schema 字串欄位加的長度上限。**那不是準確率改善**
> （對上一版 0.9612 的差異 McNemar p＝0.40，不顯著），它修的是「模型在無界的
> `分析原因` 裡退化成重複 → 吃光 num_predict → 回應不是合法 JSON → 被後備方案
> 吞成 safe」這條靜默漏報路徑：解析失敗 18 次（4.01%）→ 0 次，其中 5 筆是真詐騙。

### 階段（`data/stage_test.jsonl` 444 個前綴）

| 模型 | exact | ±1 | MAE | 判晚（危險） | 判早（保守） |
|---|---|---|---|---|---|
| **`flash_stage_v5`（Breeze2 微調・現行）** | **0.5518** | 0.8288 | **0.6554** | 0.2230 | 0.2252 |
| `flash_stage_v2`（Qwen2.5-3B 微調） | 0.4775 | 0.8288 | 0.6937 | **0.0811** | 0.4414 |
| breeze2-3b（未微調基底） | 0.3532 | 0.7936 | 0.9633 | 0.4725 | 0.1743 |
| `flash_stage_v4`（微調失敗） | 0.3083 | 0.6019 | 1.3010 | 0.5728 | 0.1189 |
| gemma-4-12B（未微調，148 筆子集） | 0.5541 | 0.8581 | 0.6622 | 0.2432 | 0.2027 |

v2 → v5 的 exact 上升主要來自把 v2 過度保守的判早（0.44）拉回來，代價是判晚從 0.08 升到 0.22。
階段是**序數**分類，所以主要看 MAE 與判晚率而不是 accuracy——判晚是「對方已經開口要錢、
系統還說在培養信任」，判早只是提早示警。

> ⚠ **`flash_stage_v5` 只認訓練時那一份 system prompt**（`app/prompts/scam_stage_system.txt`）。
> 上線時提示詞檔要跟模型一起換，帶到別的版本會整顆壞掉——不是掉幾個百分點，是壞掉。

> ⚠ **地端分發的版本落後線上一代。** 伺服器 Ollama 跑 `flash_v6` / `flash_stage_v5`，
> 但 `.env` 的 `LOCAL_MODEL_*` 仍指向 `flash-v5.gguf`（v5.0）與 `flash-stage-v2.gguf`（v2.0），
> 也就是 App 離線模式拿到的是舊一代模型。要跟上得重新匯出 GGUF、跑
> `python -m scripts.check_local_model` 更新三行設定並升版號。

## 安裝與執行

### 1. 環境需求

- Python 3.12
- MySQL 8.0+
- （RAG 功能）NVIDIA GPU + CUDA 驅動、[Ollama](https://ollama.com)

### 2. 安裝相依套件

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows（Linux/macOS：source .venv/bin/activate）

# 先安裝 GPU 版 PyTorch
# 查看 CUDA 版本：nvidia-smi 第一行右上角
# 依版本替換 cu128（CUDA 12.8）為 cu121 / cu124 / cu126 等
pip install torch --index-url https://download.pytorch.org/whl/cu128

pip install -r requirements.txt
```

### 3. 建立資料庫與設定 `.env`

```sql
CREATE DATABASE flash_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'flash'@'%' IDENTIFIED BY 'flash_password';
GRANT ALL PRIVILEGES ON flash_db.* TO 'flash'@'%';
```

編輯 `.env`：至少更換 `DATABASE_URL`、`JWT_SECRET_KEY`、`RAG_API_KEY`。

### 4. 執行資料庫遷移

```bash
alembic upgrade head
```

（開發期也可在 `.env` 設 `AUTO_CREATE_TABLES=true`，啟動時自動建表。）

### 5. 啟動後端

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- Swagger UI：<http://127.0.0.1:8000/docs>
- 健康檢查：<http://127.0.0.1:8000/health>

### 6. 啟動 RAG（偵測功能需要）

```bash
# (a) 啟動 Ollama 並建立兩顆微調模型（模型名稱可於 .env 的 OLLAMA_MODEL / OLLAMA_STAGE_MODEL 調整）
ollama serve
ollama create flash_v6 -f modelfiles/Modelfile.v6              # 偵測
ollama create flash_stage_v5 -f modelfiles/Modelfile.stage.v5  # 階段
#  ★ 不要加 --quantize：FROM 指的已經是量化好的 GGUF（q4_K_M），再量化一次只會掉分
#  ★ 行動裝置版的 Modelfile 為 *.mobile（較小的上下文視窗）

# (b) 啟動 RAG 向量入庫程式（獨立終端機，長駐執行）
python rag_worker.py
```

`rag_worker.py` 啟動後會：

1. 載入嵌入模型（`EMBEDDING_MODEL`，預設 embeddinggemma-300m；自動偵測 CUDA GPU，半精度推論；首次執行自動下載模型）
2. 讀取 `data/vector_db.jsonl` 全量向量化存入 ChromaDB（`./chroma_data`）
3. 每 60 秒呼叫 `GET /api/v1/rag/reports` 拉取新使用者回報並增量入庫

> **冪等保證**：所有向量以確定性 ID upsert，程式重啟或重複拉取不會造成重複資料。
> **注意**：`rag_worker.py` 與後端共用同一個 ChromaDB 目錄，請於同一台機器執行；
> 若需跨機器部署，建議改用 `chroma run` 伺服器模式並將兩端改為 HttpClient。

### 7. 設定信箱連接（`/mail` 功能需要）

沒設定憑證也不影響其他功能，只是 `GET /mail/connect/{provider}` 會回 503。

**(a) 建立 OAuth 用戶端**

| 提供者 | 主控台 | 要開啟的 API／權限 |
|--------|--------|------------------|
| Gmail | Google Cloud Console → API 和服務 → 憑證 → OAuth 用戶端 ID（網頁應用程式） | 啟用 Gmail API，scope `gmail.readonly` |
| Outlook | Azure 入口網站 → 應用程式註冊 → 憑證與祕密 | Microsoft Graph 委派權限 `Mail.Read`、`User.Read`、`offline_access` |

兩邊都要把**轉址網址**登記為（須與 `MAIL_OAUTH_REDIRECT_BASE` 組出來的完全一致）：

```
{MAIL_OAUTH_REDIRECT_BASE}/api/v1/mail/callback/gmail
{MAIL_OAUTH_REDIRECT_BASE}/api/v1/mail/callback/outlook
```

> **Cloudflare Tunnel 換網址時**：`.env` 的 `MAIL_OAUTH_REDIRECT_BASE` 與
> Google／Azure 主控台上登記的轉址網址都要一起改，否則授權會被擋在
> `redirect_uri_mismatch`。已經連好的信箱不受影響（refresh_token 已在手上）。

**(b) 產生 refresh_token 加密金鑰**

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**(c) 寫進 `.env`**

```ini
GMAIL_CLIENT_ID=...
GMAIL_CLIENT_SECRET=...
OUTLOOK_CLIENT_ID=...
OUTLOOK_CLIENT_SECRET=...
OUTLOOK_TENANT=common              # 個人 + 公司帳號都能連

MAIL_OAUTH_REDIRECT_BASE=https://your-tunnel.example.com
MAIL_OAUTH_SUCCESS_REDIRECT=       # 填 App 深層連結可在授權後自動跳回 App
MAIL_TOKEN_ENCRYPTION_KEY=         # 上一步產生的金鑰；留空則由 JWT_SECRET_KEY 衍生

MAIL_SYNC_ENABLED=true             # 背景輪詢排程總開關
MAIL_SYNC_INTERVAL_SECONDS=300     # 輪詢間隔
MAIL_SYNC_MAX_MESSAGES=20          # 單一信箱每輪最多分析封數
MAIL_SYNC_INITIAL_LOOKBACK_HOURS=24 # 首次連接往回抓的範圍
```

> **Google restricted scope**：`gmail.readonly` 屬於 restricted scope。App 停在
> testing 模式（≤100 個測試帳號）不需要額外驗證；要送 production 驗證時，
> 「是否在伺服器儲存 restricted scope 資料」會影響是否需要第三方安全評估——
> 本專案不儲存信件內容，正是為了讓這題維持在最單純的狀態。

### 8. 部署地端模型（App 離線模式需要）

沒部署也不影響其他功能，只是 `/local-model/manifest` 會回 503。

```bash
# 把 GGUF 放上伺服器後，確認檔案完整並取得要貼進 .env 的設定
python -m scripts.check_local_model /srv/flash/models/flash-v5.gguf \
    --expect-sha256 1e4db059dc6398762701d8ab528efe26bea09e314524a376f464fea38285bafa
```

```ini
LOCAL_MODEL_PATH=/srv/flash/models/flash-v5.gguf
LOCAL_MODEL_SIZE_BYTES=2019377248   # 與實際檔案不符時 manifest 直接回 503
LOCAL_MODEL_SHA256=1e4d...bafa      # 留空後端會自己讀滿 1.88 GiB 算一次，請填好
LOCAL_MODEL_PUBLIC_BASE_URL=https://models.example.com
LOCAL_MODEL_XACCEL_LOCATION=/protected-models   # 交給 Nginx 送檔；留空則後端自己串流
```

Nginx／Caddy 設定範例與驗收指令見 **`docs/local_model_deployment.md`**。

## GPU 效能設計說明

RAG 的 PyTorch 相關程式（`app/services/rag_service.py`）已針對 GPU 最佳化：

- `EMBEDDING_DEVICE=auto`：偵測到 CUDA 自動使用 GPU，否則退回 CPU
- **FP16 半精度推論**（`use_fp16=True`）：速度約為 FP32 的 2 倍、顯存減半
- **TF32 matmul + cuDNN benchmark**：Ampere 以上顯卡再提速
- **批次編碼**（`EMBEDDING_BATCH_SIZE`，預設 32）：訓練資料入庫時充分利用 GPU 平行度
- 嵌入運算透過 `asyncio.to_thread` 移出事件迴圈，不阻塞其他 API 請求

## 更換／比較嵌入模型（A/B）

嵌入模型已抽象為可抽換後端（`app/services/embedding.py`），改 `.env` 即可切換，
無須改動 `rag_service.py` 或 `rag_worker.py`：

> **2026-09-05：預設由 `BAAI/bge-m3` 換成 `google/embeddinggemma-300m`。**
> 原因是比賽規則禁用中國開源模型，而先前比較過的四顆（bge-m3、bge-large-zh＝智源；
> Qwen3-Embedding、gte-multilingual＝阿里）全在禁用範圍。
>
> | 嵌入模型 | 來源 | 維度 | accuracy | F1 | 檢索 ms/筆 |
> |---|---|---|---|---|---|
> | BAAI/bge-m3 | 智源 | 1024 | 0.9242 | 0.9264 | 102.2 |
> | BAAI/bge-large-zh-v1.5 | 智源 | 1024 | 0.9238 | 0.9259 | 135.3 |
> | **google/embeddinggemma-300m** | **Google** | **768** | **0.9173** | **0.9207** | **66.1** |
> | Qwen/Qwen3-Embedding-0.6B | 阿里 | 1024 | 0.9164 | 0.9199 | 174.1 |
> | intfloat/multilingual-e5-large | Microsoft | 1024 | 0.9137 | 0.9166 | 125.2 |
> | Alibaba-NLP/gte-multilingual-base | 阿里 | 768 | 0.9054 | 0.9051 | 55.9 |
>
> 條件：閘門讓開、案例注入門檻 0、LLM 一律 `flash_v4.1`。配對檢定（取共同樣本 id，
> 因測試集在八月後由 2,000 筆調整為 1,983 筆）：Gemma vs bge-m3 p=0.26、
> vs e5-large p=0.60、vs Qwen3 p=1.00——**三顆小模型分不出高下，與 bge-m3 的差距
> 也不顯著**。既然分數打平，取血統零爭議、檢索快一倍、向量小 25% 的那顆。
>
> ⚠ 兩個換過去才會踩到的坑：(1) EmbeddingGemma 是 **gated repo**，要先在 HF 網頁
> 接受授權並 `hf auth login`；(2) 它在 **float16 下整條輸出 NaN 且不報錯**，必須
> bfloat16（已由 `MODEL_PRESETS` 指定，並在載入時加了探針檢查）。
> 明細：`eval/embedding_model_comparison.csv`、`eval/embedding_compare/*.json`。

| 設定 | 說明 |
| --- | --- |
| `EMBEDDING_MODEL` | HuggingFace 模型名稱，例：`google/embeddinggemma-300m`（預設，**gated repo，需先在 HF 接受授權並登入**）、`intfloat/multilingual-e5-large`、`sentence-transformers/paraphrase-multilingual-mpnet-base-v2` |
| `EMBEDDING_BACKEND` | `auto`（依模型名自動判斷）/ `flagembedding`（BGE-M3 專用）/ `sentence_transformers`（通用） |
| `EMBEDDING_QUERY_PREFIX`／`EMBEDDING_PASSAGE_PREFIX` | 查詢／文件前綴。留空未設定時採用模型預設值（見 `MODEL_PRESETS`） |
| `EMBEDDING_TRUST_REMOTE_CODE` | 需載入 repo 自訂程式碼的模型（如 gte-multilingual-base）設為 `true` |
| `EMBEDDING_DIMENSION` | `>0` 時做 MRL 降維截斷（僅限 Matryoshka 訓練的模型，如 Qwen3-Embedding） |

**非對稱檢索**：E5、Qwen3-Embedding、bge-zh 等模型的「查詢」與「被檢索文件」
須使用不同前綴，漏加會顯著掉分。前綴由模型名稱自動套用，查詢端（`rag_service`）
以 `is_query=True`、入庫端（`rag_worker`）以 `is_query=False` 呼叫。

### A/B 比較步驟

```bash
# 1. 每個模型各用一個獨立集合（可並存，切換 .env 即可比較，免重複入庫）
#    .env：
#      EMBEDDING_MODEL=google/embeddinggemma-300m
#      CHROMA_COLLECTION=scam_messages__google_embeddinggemma_300m

# 2. 以新模型全量重建向量庫
python rag_worker.py

# 3. 掃描門檻網格，找出新模型的最佳 LOW / HIGH（見下節）
python -m scripts.eval_scam_detection --sweep --cache eval/cache_embgemma.jsonl

# 4. 將建議門檻寫入 .env 後，跑一般評測確認
python -m scripts.eval_scam_detection
```

### 門檻掃描（`--sweep`）

換模型後用來重新校準 `RAG_GATE_TOP_N` / `RAG_GATE_SIMILARITY`。

```bash
# 完整掃描（需 Ollama）：結果涵蓋全部樣本
python -m scripts.eval_scam_detection --sweep --limit 300 --cache eval/cache_bgem3.jsonl

# 只比嵌入模型的檢索品質，不需 Ollama
python -m scripts.eval_scam_detection --sweep --sweep-no-llm --cache eval/cache_bgem3_nollm.jsonl

# 有快取後改網格重掃是瞬間完成的（不需 GPU / Ollama）
python -m scripts.eval_scam_detection --sweep --cache eval/cache_bgem3.jsonl --sweep-step 0.01
```

**為何掃描很快**：檢索結果與 LLM 提示詞只受 `RAG_CASE_*` 影響，與 LOW/HIGH 兩個
閘門門檻無關。因此階段一（嵌入檢索 + 每筆各一次 LLM 推論）只需做一次並快取，
階段二對每組門檻重播 `RagService._similarity_gate()`（直接呼叫正式函式，
不另外複製一份判斷邏輯），閘門放行時取用快取的 LLM 判定。掃描上千組門檻的結果
與「每組都完整重跑一次」等價，但只付一次推論成本。

> ⚠ 此等價性僅適用於 LOW/HIGH。若要改 `RAG_CASE_SIMILARITY_THRESHOLD` 或
> `RAG_CASE_MAX_PER_GROUP`，LLM 提示詞會改變、快取失效，必須換快取檔名重跑階段一。

輸出包含：

- **top-1 相似度分佈**（詐騙 vs 正常各自的 p05/p25/中位數/p75/p95）— 能一眼看出
  換模型後相似度尺度平移了多少。注意兩類分佈重疊嚴重，這張表**不是**用來挑出
  一個能分開兩類的 `x` 的（沒有那種 x），而是用來確認 `x` 落在讓票投得出來的位置
- **三份榜單**：F1 最高／精確率達標下召回率最高（漏報代價高時採用）／
  F1 幾乎不掉但閘門覆蓋率最高（LLM 呼叫最少、延遲最低）
- **完整網格 CSV**（`--sweep-out`，預設 `eval/threshold_sweep.csv`）— 供畫 P/R 曲線與跨模型比較

`--sweep-no-llm` 模式下，閘門放行的樣本無判定可用而被排除，指標只涵蓋閘門自行判定的
子集（表中 `樣本` 欄會小於總數），數值會明顯偏高且**不可跨門檻直接比大小**（分母不同），
須連同 `閘門覆蓋` 一起看。此模式適合比較不同嵌入模型的檢索品質，正式定案請跑完整掃描。

> ⚠️ **換模型必讀**
> 1. **門檻須重新校準**：`RAG_GATE_TOP_N` / `RAG_GATE_SIMILARITY` /
>    `RAG_CASE_SIMILARITY_THRESHOLD` 是依當前模型（embeddinggemma-300m）的餘弦分佈訂出來的，不同模型
>    分佈不同，沿用舊值會讓相似度閘門大量誤判。
> 2. **向量庫須重建**：不同模型的向量空間不相容。維度不同時
>    `check_collection_dimension()` 會在啟動時直接報錯；**維度剛好相同時不會報錯，
>    但比對結果無意義**，故務必為每個模型使用不同的 `CHROMA_COLLECTION`。

## 有無 RAG 的 A/B 比較（`RAG_ENABLED`）

`.env` 的 `RAG_ENABLED=false` 會讓偵測整段跳過「嵌入 → 向量檢索 → 相似度閘門」，
直接把訊息交給 LLM 判斷，用來量測 RAG 對準確度的實際貢獻。此模式**不需 GPU 與
ChromaDB**（也不會載入嵌入模型）。

| 設定 | 說明 |
| --- | --- |
| `RAG_ENABLED` | `true`（預設）走完整 RAG 流程；`false` 走純 LLM 路徑 |
| `NO_RAG_PROMPT_HEADER` | 關閉 RAG 時 user 訊息是否保留 `【待偵測訊息】` 標頭（預設 `true`）。請對齊該版微調資料的 user 格式 |

關閉 RAG 時提示詞自動切換為「無 RAG 契約」：

| | `RAG_ENABLED=true` | `RAG_ENABLED=false` |
| --- | --- | --- |
| system | `app/prompts/scam_detection_system.txt` | `..._no_rag.txt`（同一份，僅移除 `【相似案例參考說明】` 整段） |
| user | `【待偵測訊息】` + `【相似詐騙案例】` + `【相似正常訊息】` | 只有待偵測訊息 |
| 回應 `similar_cases` | 最多 3+3 筆 | 必為 `[]` |
| 回應 `model` | `similarity-gate` 或 LLM 名稱 | 必為 LLM 名稱（不會有閘門判定） |

兩份 system prompt 的一致性由 `test_no_rag_system_prompt_only_drops_similar_case_section`
把關：教科書與任務說明是兩版微調模型共用的訓練契約，只改一份而另一份沒跟上，
量到的就會是提示詞差異而不是 RAG 的效果。

### 比較步驟

評測腳本可用 `--rag` / `--no-rag` 與 `--ollama-model` 就地覆寫，不必來回改 `.env`：

```bash
# 有 RAG（搭配「有考慮相似案例」的微調模型）
python -m scripts.eval_scam_detection --limit 300 --rag    --ollama-model flash_v3 \
    --out eval_rag.jsonl

# 無 RAG（搭配「沒有考慮相似案例」的微調模型）
python -m scripts.eval_scam_detection --limit 300 --no-rag --ollama-model flash_v3_norag \
    --out eval_norag.jsonl
```

報表開頭固定印出當次生效的 `RAG_ENABLED` / `OLLAMA_MODEL` / `EMBEDDING_MODEL` 與
門檻值，兩次結果不會混淆。

> ⚠️ **微調模型必須成對切換**
> 有 RAG 的那版模型是**看著相似案例訓練出來的**。若拿它在無案例的輸入下評測，
> 等於讓它面對訓練分布外的輸入，掉分並非「RAG 有用」的證據；反之亦然。
> 每次比較請確認 `RAG_ENABLED` 與 `OLLAMA_MODEL` 兩者是配對的。

`--sweep` 掃的正是相似度閘門的門檻，與 `--no-rag` 互斥，同時指定會直接報錯。

## scripts 目錄總覽

38 支離線工具（不含 `__init__.py`），一律以 `python -m scripts.<name>` 在**專案根目錄**執行。
每支的模組說明（docstring）都寫了「為什麼需要這支」與踩過的坑，改動前請先讀那一段；
網頁版總覽在 **[docs/flash_backend_overview.html](docs/flash_backend_overview.html)**。

### A. 評測與報表

| 腳本 | 做什麼 | 常用指令 |
|------|--------|----------|
| `eval_scam_detection.py` | 偵測準確度評測；`--sweep` 門檻掃描、`--no-rag` A/B、`--embedding-model` 換嵌入模型 | `--limit 100`／`--sweep --cache x.jsonl` |
| `eval_stage.py` | 階段評測（序數指標）；`--rules-only` 是不需模型的基線 | `--model flash_stage_v5 --sequential` |
| `build_review_queue.py` | 把評測結果依「看了最可能改善系統」排出 P0–P5 待審清單 | `--eval eval/xxx.jsonl` |
| `rank_eval_cases.py` | 依「錯了代價多大」重排成 Excel 可開的 CSV，附對手模型的判定 | `--kind detection --opponent …` |
| `collect_eval_metrics.py` | 彙整各模型逐筆結果成 `docs/metrics.json`（同一批 id 才比得準） | 無參數 |
| `build_eval_deck.py` | 產評測簡報，數字 build 時現算 | 需 `pip install python-pptx` |
| `build_model_comparison_ppt.py` | 產模型比較簡報，數字讀 `docs/metrics.json` | 需 `pip install python-pptx` |
| `stat_source_platform.py` | 推估訊息來源平台（chat／sms／email）分佈 | `--dump eval/platform_stats` |

### B. 向量庫維護與負樣本

| 腳本 | 做什麼 | 常用指令 |
|------|--------|----------|
| `kb_label_audit.py` | 稽核會讓閘門判錯的污染條目；偵測自動、**處置一律走決策檔** | `--apply --dry-run` |
| `gen_daily_chat_negatives.py` | 產台灣日常人際訊息負樣本（庫裡原本一筆都沒有） | `--dry-run`／`--count 3000` |
| `fetch_ptt_daily_negatives.py` | 從 PTT 八卦板語料濾出真人短句候選，**人工挑過**才入庫 | `--build-candidates` |
| `probe_daily_chat_gate.py` | 用未進庫的日常訊息當探針量閘門覆蓋率 | `--verbose` |
| `gen_transactional_negatives.py` | 產合法品牌交易通知負樣本（誤報最集中的型態） | `--count 800` |
| `compare_embedding_models.py` | 嵌入模型橫向比較：各建一個集合、各跑一次評測；可中斷續跑 | `--report-only` |
| `fit_risk_calibration.py` | 由評測結果擬合 `risk_score` 校準表（四格＋llm 相似度微調） | `--eval eval/xxx.jsonl` |
| `build_sim_cache.py` | 對當前向量庫重跑檢索，產生擬合微調係數所需的特徵快取 | 無參數；**擬合前必跑** |

### C. 測試集答案與標籤清洗

| 腳本 | 做什麼 | 常用指令 |
|------|--------|----------|
| `label_scam_batch.py` | 分批重標偵測測試集的 `is_scam` / `scam_type`；`x` = 無法判斷並剔除 | `--export 60`／`--apply` |
| `export_answer_review.py` | 把測試集答案攤成人工審核頁，四份分工，含盲審抽樣 | `--dataset scam --shards 2` |
| `import_answer_review.py` | 收回審核結果；印盲審一致率（那才是原答案可信度的估計） | `--apply` |
| `clean_labels.py` | Cofacts 謠言標註 → 詐騙標籤分層（謠言 ≠ 詐騙） | `--dry-run` |
| `fix_fine_tune.py` | 修復微調資料的類別雜訊、標籤雜訊與測試集汙染（另存 `.clean.jsonl`） | `--dry-run` |

### D. 對話語料（階段模型的原料，依序執行）

| 腳本 | 做什麼 | 備註 |
|------|--------|------|
| `fetch_cofacts_conversations.py` | 從 Cofacts API 抓真實對話截圖轉錄 | 約 7 分鐘；CC BY-SA 4.0 |
| `fetch_cofacts_images.py` | 下載原始截圖（**簽名網址短效**，查完要立刻下載） | 約 30 分鐘／109 MB |
| `layout_transcribe.py` | 帶座標的 OCR：泡泡靠左＝對方、靠右＝我 | 可中斷續跑 |
| `transplant_ocr_text.py` | 座標用本機的、文字用 Cofacts 的（行級一對一指派） | 全部約 10 秒 |
| `detect_explicit_images.py` | 掃出含不雅照片的截圖；**只排序，刪除由人確認** | 掃描約 17 分鐘 |
| `export_review_page.py` | 產「左圖右表」審核頁；`--blind` 出盲測頁 | 輸出 `eval/label_review/` |
| `export_label_sheet.py` | 舊的純文字 Excel 工作表（沒有原圖時的退路） | `--shards 3` |
| `import_label_sheet.py` | 把填好的工作表收回成語料（可重複匯入） | `--dry-run` |
| `audit_sender_labels.py` | 比對機器判的發送者與人工標的，量真實準確率 | 配 `export_review_page --blind` |
| `build_stage_corpus.py` | 把既有資料整理成多輪對話（**只負責結構**） | `--source cofacts\|synthetic\|layout\|lovefraud` |
| `label_stage_turns.py` | turn-level 弱標註：規則／位置／LLM 三方投票 | `--llm --model qwen2.5:7b` |
| `label_stage_teacher.py` | 用較大的老師模型逐則重標，補弱標註標不出來的那半 | 全量約 2.7 小時，可中斷 |
| `label_stage_batch.py` | 分批交給更強的模型標**階段轉折點** | `--export 25`／`--status` |
| `build_stage_dataset.py` | 前綴切片 → `stage_finetune.jsonl` / `stage_test.jsonl` | `--test-size 250 --real-only` |

### E. 訓練與部署

| 腳本 | 做什麼 | 備註 |
|------|--------|------|
| `train_stage_lora.py` | 階段模型 QLoRA 微調；配置寫進 `run_config.json` 以利重現 | `--smoke` 先量速度與 VRAM |
| `merge_stage_lora.py` | 合併 adapter 成 safetensors，供 `ollama create` 轉 GGUF | 預設在 CPU 上合併 |
| `check_local_model.py` | 伺服器端驗證 GGUF 完整性，印出可貼進 `.env` 的三行 | `--model detect\|stage` |

> `scripts/` 下的工具都 `from app.core.config import settings`，所以必須用 `python -m` 形式
> 在專案根目錄執行；直接 `python scripts/xxx.py` 會找不到 `app` 套件。
> 各腳本的預設輸入／輸出路徑都錨定在專案根目錄，不受當下工作目錄影響。

## 向量庫維護

一致性閘門在最相似的 N 筆一面倒時會直接採用那批鄰居的 `is_scam` 標籤、完全不呼叫
LLM。這讓向量庫裡標錯的條目會被放大成系統性錯誤——被標成「非詐騙」的詐騙話術，
會讓所有與它相似的真詐騙被閘門直接放行。

改成 N 筆一致之後，單一筆標錯已不足以獨自造成誤放（還需要另外 N-1 個鄰居陪同），
但**同一個話術家族整批標錯**仍然會，而那正是實務上最常見的污染型態，所以下面
這套稽核流程照跑不誤。

```bash
# 1. 偵測污染：庫內標籤矛盾的近重複配對，以及會讓閘門放行真詐騙的負樣本
python -m scripts.kb_label_audit

# 2. 覆核 eval/kb_label_audit.csv，把處置寫進 data/kb_label_fixes.jsonl（每筆含 id/動作/理由）
python -m scripts.kb_label_audit --apply --dry-run   # 先看會改什麼
python -m scripts.kb_label_audit --apply             # 套用（原檔自動備份為 .bak）

# 3. 讓 ChromaDB 跟上（--prune 會刪掉訓練資料檔中已不存在的向量；upsert 不會刪）
python rag_worker.py --once --prune
```

清理標籤是迭代的：改掉一筆污染會讓同族的另一筆浮出來，所以決策檔逐輪累積、整份
重跑（已達目標狀態的條目記為 noop 而非錯誤）。反覆跑到偵測器 B 歸零為止。

補特定型態的負樣本（目前針對誤報最集中的短交易通知簡訊）：

```bash
python -m scripts.gen_transactional_negatives --dry-run   # 先看樣例
python -m scripts.gen_transactional_negatives             # 附加到 data/vector_db.jsonl
python rag_worker.py --once --prune
python -m scripts.kb_label_audit                          # 確認沒有新增閘門漏抓
```

> 補負樣本一定要回頭跑 `kb_label_audit.py`：新負樣本若與真釣魚簡訊相似度超過閘門
> 危險門檻，就會製造出新的漏抓，這時要調整樣板而不是硬加。

### 向量庫組成（`data/vector_db.jsonl`，12,394 筆）

| 來源 | 筆數 | 是什麼 |
|------|------|--------|
| `cofacts` | 5,674 | 使用者轉傳進查核平台的真實訊息 |
| `synthetic` | 4,325 | 合成詐騙話術（多階段壓縮成一則） |
| `synthetic-daily-chat` | 1,758 | 台灣日常人際訊息負樣本（2026-09-19 補） |
| `synthetic-legit-notice` | 500 | 合法品牌交易通知負樣本 |
| `ptt-gossiping` | 137 | PTT 八卦板真人短句，人工挑過 |
| **合計** | **12,394** | 詐騙 6,012 ／ 非詐騙 6,382 |

### 補日常對話負樣本（2026-09-19）

庫裡原本**沒有任何一筆**是人傳給人的日常訊息，但使用者丟進 App 的大宗正是這一類
（「媽我今天晚點回去」）。缺口直接打在閘門上：找不到同類鄰居時 top-N 會混進詐騙樣本，
閘門湊不齊票、整批退給 LLM——既慢又吃 GPU，而 LLM 對這種短閒聊本來就容易誤報。

```bash
python -m scripts.gen_daily_chat_negatives --count 2000     # 樣板產生器（情境齊、可控）
python -m scripts.fetch_ptt_daily_negatives --build-candidates  # 真人語料候選
#  ★ 人工審閱候選，合格的貼進 data/ptt_daily_curated.txt
python -m scripts.fetch_ptt_daily_negatives                 # 依決策檔附加到向量庫
python -m scripts.kb_label_audit                            # 偵測器 B：會不會製造新漏抓
python rag_worker.py --once --prune
python -m scripts.probe_daily_chat_gate                     # 量效果（見下）
```

> **這批樣本的效果 `data/test.jsonl` 量不到。** 測試集全是轉傳訊息與詐騙話術，
> 一則真正的日常對話都沒有，補完重跑 acc 0.9581 → 0.9576，看起來像沒用。
> 要量的是「使用者傳『媽我晚點回去』時閘門能不能直接判安全」，所以用
> `probe_daily_chat_gate.py` 的**未進庫探針**：日常訊息被閘門直接判安全 19% → 81%、
> 真實聊天 13 則誤報 3 → 0、8 則短詐騙仍全部抓到。
>
> PTT 那批**必須人工挑**：關鍵字過濾把 77 萬句砍到 7,796 句後，抽樣仍有約一成是
> 性暗示、政治嘲諷或需要前文才看得懂的殘句；換本地 LLM 當篩選器也沒用
> （3B 判不準、12B 直接回空字串且 20 句要跑 1–2 分鐘）。最危險的是「推文本身在講詐騙」
> ——那種句子與真詐騙向量很近卻標成 `is_scam=0`，等於直接在庫裡埋一顆漏抓。

## 風險分數校準（`risk_score`）

`confidence` **不能拿來畫風險條**。它在兩條路徑上是兩種完全不同的量：閘門的
`confidence` 是 top-1 餘弦相似度（不是機率），LLM 的是模型自報的分數——而後者與
真實標籤**反向**（AUC 0.3317）。要呈現風險請一律用 `risk_score`。

`risk_score` 是查一張四格表，LLM 判的那兩格再用檢索鄰域微調：

| | 判詐騙 | 判正常 |
|---|---|---|
| 閘門判定 | 0.9783 | 0.0235 |
| LLM 判定 | 0.9205（＋相似度微調）| 0.1287（＋相似度微調）|

四個數字是 1,983 筆評測的實測詐騙率（Laplace 平滑）。微調用兩個特徵：最相似 3 筆的
「相似度加權詐騙票佔比」與「平均相似度」。**閘門那兩格不微調**——閘門的觸發條件
本身就是相似度，訊號已經被花掉了（實測增益 0.0000）。推導與各方案的對照見
[`docs/VERSIONS.md` §6.1](docs/VERSIONS.md)。

`risk_level` 由 `risk_score` 與 `RISK_HIGH_SCORE`（0.90）決定：實測 `high` 898 筆
（真實詐騙率 0.977）、`mid` 96 筆（0.802）、`safe` 989 筆。

**校準表與整條管線綁定**：`model` / `embedding_model` / `gate_top_n` / `gate_similarity`
任一欄不符就整個停用、`risk_score` 回 `null`——寧可前端沒這個欄位，也不給一個看起來
合理的錯機率。換模型或改閘門參數後要重擬合：

```bash
python -m scripts.eval_scam_detection --ollama-model flash_v7 --out eval/eval_flash_v7.jsonl --concurrency 1
python -m scripts.build_sim_cache                    # 對當前向量庫重跑檢索
python -m scripts.fit_risk_calibration --eval eval/eval_flash_v7.jsonl
```

擬合腳本各格自己做 5 折交叉驗證，微調沒贏過常數就不寫係數並印出原因。

> ⚠ **向量庫內容沒有自動保護。** `rag_worker` 每分鐘把使用者回報灌進 ChromaDB，
> 四格的純度會隨 KB 慢慢漂移，而沒有任何欄位察覺得到。大幅改動向量庫後請重跑評測
> 與擬合。

> **量閘門相關數字時請加 `--concurrency 1`。** 併發跑偵測時嵌入模型的冷啟動會發生競爭，
> 曾整批被判成詐騙；暖機修正已經加上，但量測仍以單併發為準。

## 執行測試

測試使用 SQLite 記憶體資料庫並以測試替身取代 RAG 服務，**不需 MySQL / GPU / Ollama**：

```bash
pytest -v
```

涵蓋：註冊／登入／OTP 忘記密碼三步驟／權杖換發／更改密碼、個人資料與設定、
電話／帳號／完整回報與風險升級規則、RAG 回報查詢（X-API-Key）與偵測端點、
詐騙階段判定（單調性調和、關鍵詞下界、對話截斷、階段名稱與提示詞的一致性），
以及信箱連接（OAuth state 驗證、refresh_token 加密落地、輪詢去重、授權失效停用、
Gmail／Graph 回應解析、以及「不得儲存信件內容」的欄位約束），
以及地端模型下載（401／403 授權、manifest 欄位契約、SHA-256、Range 206 續傳、
HEAD、X-Accel 標頭與存取日誌的權杖遮蔽）。

## 安全設計摘要

- 密碼以 **bcrypt**（隨機 salt）雜湊；OTP 以 SHA-256 + pepper 雜湊，皆不存明碼
- 登入與忘記密碼回應**不洩漏帳號是否存在**（防帳號列舉）
- OTP 限時 10 分鐘、最多錯 5 次；reset_token 一次性使用
- JWT 區分 access（30 分）／refresh（14 天）類型，不可互換使用
- OAuth 權杖一律向 Google / Facebook 官方端點驗證（Google 並核對 audience）
- 電話詳情的社群回報**遮罩回報者名稱**保護隱私
- `/rag/reports` 為內部端點，以 `X-API-Key`（常數時間比較）隔離於使用者認證之外
- 信箱 `refresh_token` 以 **Fernet 加密**後才落地；`client_secret` 只存在伺服器端，
  手機從頭到尾拿不到任何信箱權杖，即使 App 被反編譯也偷不走信箱存取權
- 信箱授權的 `state` 為短效簽章 JWT（綁定發起者、含 `jti`），防止他人把信箱掛到
  別的帳號下或重放舊授權連結；`access_token` 用完即丟，不落地
- 地端模型的下載網址是短效簽章（`type=local_model`，綁定檔名與版本），與 access
  token 互不相通；模型檔沒有匿名可取得的網址，實體路徑只能由 Nginx internal
  導向或通過 `auth_request` 取用，且權杖不會寫進存取日誌
- **信件內容一律不寫入資料庫**，只存判定結果（見
  [資料落地原則](#資料落地原則決策-2只存判定不存信件)），並以測試把關
