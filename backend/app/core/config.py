"""系統設定模組。

使用 pydantic-settings 讀取 `.env` 檔與環境變數，
所有模組皆應透過本模組的 `settings` 單例取得設定值。
"""

import re
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """應用程式設定（欄位值可由 .env 或環境變數覆寫）。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ----- 一般設定 -----
    PROJECT_NAME: str = "F.L.A.S.H. 詐騙感知防護系統 API"
    PROJECT_VERSION: str = "1.0.0"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = False
    # 開發模式下啟動時自動建立資料表（正式環境請使用 alembic 遷移）
    AUTO_CREATE_TABLES: bool = False
    # CORS 允許來源（JSON 陣列格式，例如 ["https://app.example.com"]）
    BACKEND_CORS_ORIGINS: list[str] = ["*"]

    # ----- 資料庫 -----
    DATABASE_URL: str = (
        "mysql+aiomysql://flash:flash_password@127.0.0.1:3306/flash_db?charset=utf8mb4"
    )
    DB_ECHO: bool = False  # 是否輸出 SQL 日誌（除錯用）

    # ----- JWT -----
    JWT_SECRET_KEY: str = "CHANGE_ME_TO_A_LONG_RANDOM_SECRET_STRING"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30  # access_token 有效時間（分鐘）
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14  # refresh_token 有效時間（天）

    # ----- OTP / 密碼重設 -----
    OTP_EXPIRE_MINUTES: int = 10  # OTP 有效時間（分鐘）
    OTP_MAX_ATTEMPTS: int = 5  # OTP 最大嘗試次數，超過即失效
    RESET_TOKEN_EXPIRE_MINUTES: int = 15  # OTP 驗證成功後 reset_token 的有效時間

    # ----- SMTP（寄送 OTP Email）-----
    # SMTP_HOST 留空時為「開發模式」：不實際寄信，OTP 直接輸出到後端日誌
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "no-reply@flash.local"
    SMTP_TLS: bool = True

    # ----- 社交登入（OAuth）-----
    GOOGLE_CLIENT_ID: str = ""  # 用於驗證 Google ID Token 的 audience
    FACEBOOK_APP_ID: str = ""
    FACEBOOK_APP_SECRET: str = ""

    # ----- 信箱連接（Gmail API / Microsoft Graph）-----
    # OAuth 用戶端憑證：未設定的提供者，其「連接」端點會回 503（不影響其他功能）
    GMAIL_CLIENT_ID: str = ""
    GMAIL_CLIENT_SECRET: str = ""
    OUTLOOK_CLIENT_ID: str = ""
    OUTLOOK_CLIENT_SECRET: str = ""
    # Microsoft 租戶：common（個人 + 公司帳號）／consumers／organizations／租戶 GUID
    OUTLOOK_TENANT: str = "common"
    # 後端對外基底網址，用來組 OAuth redirect_uri
    # （須與 Google Cloud Console／Azure 應用程式註冊登記的轉址網址「逐字相同」；
    #   Cloudflare Tunnel 換網址時這裡與兩邊主控台都要一起改）
    MAIL_OAUTH_REDIRECT_BASE: str = "http://127.0.0.1:8000"
    MAIL_OAUTH_STATE_EXPIRE_MINUTES: int = 10  # 授權 state 權杖有效時間
    # 授權完成後導回 App 的深層連結；留空則顯示一頁「可以關閉視窗」的完成畫面
    MAIL_OAUTH_SUCCESS_REDIRECT: str = ""
    # refresh_token 的對稱加密金鑰（Fernet，urlsafe base64 的 32 bytes）。
    # 留空時由 JWT_SECRET_KEY 衍生（開發便利），正式環境請明確設定並獨立保管：
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    MAIL_TOKEN_ENCRYPTION_KEY: str = ""

    # ----- 信箱輪詢同步 -----
    # 背景排程總開關（false 時仍可由 App 呼叫 POST /mail/sync 手動同步）
    MAIL_SYNC_ENABLED: bool = True
    MAIL_SYNC_INTERVAL_SECONDS: int = 300  # 排程輪詢間隔（秒）
    MAIL_SYNC_MAX_MESSAGES: int = 20  # 單一信箱每次同步最多分析幾封（避免塞爆本地 LLM）
    MAIL_SYNC_INITIAL_LOOKBACK_HOURS: int = 24  # 首次同步往回抓的時間範圍（小時）
    # 增量抓取時往回多退的分鐘數：提供者列出新信不是即時一致的（Gmail 搜尋索引
    # 尤其明顯），沒有重疊區間的話，剛好落在空窗的信會被游標永久跳過。
    # 重複列出的信由 provider_message_id 去重，不會重複分析。
    MAIL_SYNC_OVERLAP_MINUTES: int = 10
    MAIL_DETECT_MAX_CHARS: int = 4000  # 送進偵測的信件文字上限（對齊 RagDetectRequest）
    MAIL_PREVIEW_CONCURRENCY: int = 8  # 列表 passthrough 取回信件 metadata 的併發數
    # 回報用的完整內文上限：比偵測寬得多（回報要保留完整證據），但仍設上限，
    # 避免夾帶大量 HTML 的行銷信把單次回應撐到數 MB
    MAIL_CONTENT_MAX_CHARS: int = 20000

    # ----- RAG：向量資料庫與嵌入模型 -----
    # RAG 總開關：false 時跳過「嵌入 → 檢索 → 閘門」直接交給 LLM（A/B 用）。
    # ⚠ 必須同時把 OLLAMA_MODEL 換成「未使用相似案例訓練」的版本，否則比較不具意義。
    #   步驟見 README「有無 RAG 的 A/B 比較」。
    RAG_ENABLED: bool = True
    # 關閉 RAG 時是否保留【待偵測訊息】標頭；須對齊該版微調資料的 user 欄位格式。
    NO_RAG_PROMPT_HEADER: bool = True
    RAG_API_KEY: str = "CHANGE_ME_RAG_INTERNAL_KEY"  # RAG Worker 內部 API 金鑰
    CHROMA_DIR: str = "./chroma_data"  # ChromaDB 本地儲存目錄
    CHROMA_COLLECTION: str = "scam_messages"  # 向量集合名稱
    # 嵌入模型：可換成任一 HuggingFace 模型（後端抽象見 app/services/embedding.py）。
    # 2026-09-05 由 BAAI/bge-m3 換成這顆——六顆並排的成績與選它的理由見
    # docs/VERSIONS.md §4.4 與 README「更換／比較嵌入模型」。
    # ⚠ 換模型必須重建向量庫並重新校準下面所有 RAG_*_SIMILARITY 門檻。
    # ⚠ 這顆必須 bfloat16（float16 會整條輸出 NaN 且不報錯），已由 MODEL_PRESETS 釘死。
    EMBEDDING_MODEL: str = "google/embeddinggemma-300m"
    # 推論後端：auto 依模型名稱自動判斷 / flagembedding（BGE-M3 專用）
    # / sentence_transformers（通用）
    EMBEDDING_BACKEND: str = "auto"
    EMBEDDING_DEVICE: str = "auto"  # auto / cuda / cuda:0 / cpu
    EMBEDDING_BATCH_SIZE: int = 32  # 批次編碼大小（GPU 記憶體足夠可調大）
    EMBEDDING_MAX_LENGTH: int = 512  # 最大 token 長度
    # 查詢／文件前綴：None 表示採用模型預設（MODEL_PRESETS），
    # 設為空字串則明確不加前綴。非對稱模型（E5、Qwen3、bge-zh）漏加會顯著掉分
    EMBEDDING_QUERY_PREFIX: str | None = None
    EMBEDDING_PASSAGE_PREFIX: str | None = None
    # 部分模型（gte-multilingual-base 等）需載入 repo 內自訂程式碼才能運作
    EMBEDDING_TRUST_REMOTE_CODE: bool = False
    # >0 時做 MRL 降維截斷（僅限以 Matryoshka 訓練的模型，如 Qwen3-Embedding）
    EMBEDDING_DIMENSION: int = 0
    # ⚠ 程式中沒有任何地方讀這個值，保留只為相容既有 .env；要調閘門請改 RAG_GATE_TOP_N。
    RAG_TOP_K: int = 5  # （未使用，保留相容）
    # 提示詞相似案例檢索：先取回較多候選，再依 is_scam 分成「相似詐騙案例／相似正常訊息」
    # 兩組，每組各留 similarity > 門檻、最多 N 筆（對齊 fine_tune.jsonl 的注入契約）
    RAG_RETRIEVE_CANDIDATES: int = 40  # 檢索候選筆數（供分組挑選）
    # 隨模型的餘弦尺度變動（0.7 在 BGE-M3 ＝ 第 31.7 分位，embeddinggemma 的同分位數
    # 是 0.559）。用錯只會讓注入的案例變多變少，不會報錯。★ 這個值釘在訓練契約上。
    RAG_CASE_SIMILARITY_THRESHOLD: float = 0.559  # 相似案例入選門檻（嚴格大於）
    RAG_CASE_MAX_PER_GROUP: int = 3  # 詐騙／正常各組最多納入的案例數
    # 回應 similar_cases 的顯示門檻，只在「注入那組為空」時才用得到，不影響提示詞。
    # 2026-09-20 加：兩者共用一個門檻時，判定只要 0.35 就成立、佐證案例卻被 0.559
    # 卡掉，使用者會收到「高風險 ＋ 空陣列」（1,983 筆有 31.7% 落在這個空窗）。
    RAG_DISPLAY_SIMILARITY_THRESHOLD: float = 0.35
    # 相似度一致性閘門：最相似的 N 筆若**全部**超過門檻且 is_scam **完全一致**，
    # 就直接依該類判定，不呼叫 LLM；其餘情況（票不齊、有一筆沒過、兩類並存）交給 LLM。
    #
    # 2026-09-09 取代舊的 LOW/HIGH 區間閘門。實測（1,983 筆）F1 0.9360→0.9564、
    # 覆蓋 43.6%→77.3%、LLM 呼叫 1,118→450，McNemar p=1.1e-04。完整對照表、
    # 留出驗證與「為什麼不保留低相似度直接判 safe 的分支」見 README 的閘門章節。
    #
    # 調參時：N 是主要變因（2→3 動 F1 0.006），x 幾乎是擺設（0.25~0.45 只動 0.003）。
    # 換嵌入模型時 x 可沿用，但 N 請重跑 `--sweep` 確認。
    RAG_GATE_TOP_N: int = 3  # 需要一致同意的最相似候選筆數（主要變因）
    RAG_GATE_SIMILARITY: float = 0.35  # 這 N 筆都必須嚴格大於的相似度門檻

    # 短訊息的「直接判詐騙」另設較高門檻（判安全那側不變；沒過是交給 LLM，不是放行）。
    # 2026-09-19 加：短句的向量幾乎只由一兩個詞決定，實測 13 則日常訊息有 3 則
    # （7~10 字）被閘門直接判成詐騙。全面拉高門檻會讓漏報 41→57，所以只套短訊息。
    # ⚠ 評測集驗證不到這條規則（1,983 筆中 ≤20 字的只有 3 筆），要用
    #   scripts/probe_daily_chat_gate.py 量。
    RAG_GATE_SHORT_MESSAGE_CHARS: int = 20  # 去除空白後不超過此字數視為短訊息
    RAG_GATE_SHORT_SCAM_SIMILARITY: float = 0.65  # 短訊息直接判詐騙須 top-N 全部嚴格大於此值

    # 判為詐騙時，risk_score（校準後的詐騙機率）達到此值才算 high，否則 mid。
    # 校準表不可用時退回舊規則（模型自填的「可信度評分」>= 70）。
    # 0.90 是 2026-09-16 掃出來的：0.70 會讓 mid 這一級消失、0.95 會把 358 筆真詐騙
    # 標成 mid。舊規則失真的原因（Ollama 送 schema 時會排序鍵）見 rag_service._ask_ollama。
    RISK_HIGH_SCORE: float = 0.90

    # ----- 詐騙階段判定（對話級，POST /rag/detect-conversation）-----
    # 獨立於偵測管線的第二段判定：不動偵測的 system prompt 與微調契約，
    # 另以專屬 prompt 判斷對話演進到「接觸建立／培養信任／鋪陳誘餌／索取財物／收尾拖延」
    RAG_STAGE_ENABLED: bool = True  # false 時階段一律回 null，偵測結果照常回傳
    # 判階段用的模型。⚠ 預設刻意留空＝沿用 OLLAMA_MODEL，但正式環境請指向一顆
    #   「通用 instruct 模型」而非偵測用的微調模型：後者是在「單則訊息 → 五個固定
    #   中文鍵」的窄格式上微調的，structured outputs 只鎖得住輸出形狀、鎖不住內容品質。
    OLLAMA_STAGE_MODEL: str = ""
    RAG_STAGE_MAX_MESSAGES: int = 30  # 進入提示詞的最近訊息則數上限（超過由最舊的捨棄）
    RAG_STAGE_MAX_CHARS: int = 4000  # 進入提示詞的對話總字數上限（同上）
    # 模型判出比 previous_stage 更早的階段時，要採信它所需的最低信心。
    # 詐騙腳本幾乎不倒退，回退多半是「索取那幾則被滑出視窗」造成的假象——
    # 放行等於讓使用者看到風險自己降下來，故預設訂得高。
    RAG_STAGE_REGRESS_CONFIDENCE: float = 0.8
    # 階段模型要不要「思考」。預設關掉：思考型模型（gemma4）會把推理放在
    # message.thinking 而非 content，實測 6 秒變 27 秒，且思考沒結束時 content 是空的。
    OLLAMA_STAGE_THINK: bool = False

    # ----- Ollama 本地 LLM -----
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    OLLAMA_MODEL: str = "gemma4"  # 本地 LLM 模型名稱
    OLLAMA_TIMEOUT: int = 120  # LLM 推論逾時秒數

    # ----- 地端模型下載（App 離線模式的 GGUF 模型分發）-----
    # 使用者選了「地端模式」才把 GGUF 下載到手機，推論全在手機本機做。後端只負責
    # 驗身分、發短效簽章網址、授權後放行檔案；傳輸本體交給 Nginx（見 XACCEL_LOCATION）。
    # 部署細節見 docs/local_model_deployment.md。兩顆模型各自獨立部署與換版：
    #   detect（LOCAL_MODEL_*）        flash-v5.gguf       判「是不是詐騙」
    #   stage （LOCAL_MODEL_STAGE_*）  flash-stage-v2.gguf 判「詐騙到哪一階段」
    # 兩顆共用下方的 PUBLIC_BASE_URL／URL_EXPIRE_HOURS／XACCEL_LOCATION／RATE_LIMIT。
    LOCAL_MODEL_ENABLED: bool = True  # false 時 manifest／下載端點一律回 503（兩顆一起關）
    LOCAL_MODEL_VERSION: str = "5.0"  # 模型版本（換版時與下面三個欄位一起改）
    LOCAL_MODEL_FILE_NAME: str = "flash-v5.gguf"  # 對外檔名（下載路徑的最後一段）
    # 模型檔在伺服器上的路徑（絕對路徑）。留空＝尚未部署，端點回 503。
    LOCAL_MODEL_PATH: str = ""
    # 期望的 SHA-256（App 下載完會自行核對）。留空則後端首次請求時自行計算並快取，
    # 但要讀滿一次磁碟（數十秒），正式環境請用 scripts/check_local_model.py 填好。
    LOCAL_MODEL_SHA256: str = ""
    # 期望的檔案大小；>0 且與實際檔案不符時回 503（寧可發不出 manifest，
    # 也不要讓 App 白下載 2 GB 才發現 sha256 對不上）。
    LOCAL_MODEL_SIZE_BYTES: int = 0
    # 對外 HTTPS 基底網址（例：https://models.example.com）。留空則以請求本身的
    # base_url 組出下載網址；正式環境請明確設定，避免反向代理標頭讓網址組錯。
    LOCAL_MODEL_PUBLIC_BASE_URL: str = ""
    LOCAL_MODEL_URL_EXPIRE_HOURS: int = 24  # 下載簽章有效時數（容納慢速／中斷續傳）
    # 設定後改由 Nginx 以 X-Accel-Redirect 送檔（值為 nginx 的 internal location）。
    # 留空則由本後端串流——功能相同（含 Range），但吞吐遠不如 Nginx，僅適合開發用。
    LOCAL_MODEL_XACCEL_LOCATION: str = ""
    # X-Accel 模式下的單一連線限速（bytes/sec，0＝不限）。對應 nginx 的 X-Accel-Limit-Rate。
    LOCAL_MODEL_RATE_LIMIT_BYTES_PER_SEC: int = 0

    # 階段判定模型（第二顆，選配）。欄位語意與上面那組相同，只是指到另一個檔案；
    # 沒部署時只是 manifest?model=stage 回 503，偵測那條線不受影響。
    LOCAL_MODEL_STAGE_ENABLED: bool = True  # false＝暫時只提供偵測模型
    LOCAL_MODEL_STAGE_VERSION: str = "2.0"
    LOCAL_MODEL_STAGE_FILE_NAME: str = "flash-stage-v2.gguf"  # 不可與偵測模型同名
    LOCAL_MODEL_STAGE_PATH: str = ""  # 留空＝尚未部署
    LOCAL_MODEL_STAGE_SHA256: str = ""
    LOCAL_MODEL_STAGE_SIZE_BYTES: int = 0

    # ----- RAG Worker（獨立入庫程式）-----
    RAG_BACKEND_URL: str = "http://127.0.0.1:8000"  # Worker 輪詢的後端位址
    RAG_POLL_INTERVAL_SECONDS: int = 60  # 輪詢間隔（秒）
    TRAINING_DATA_PATH: str = "./data/vector_db.jsonl"  # RAG 知識庫來源（JSON Lines）
    RAG_WORKER_STATE_PATH: str = "./rag_worker_state.json"  # Worker 同步狀態檔

    @model_validator(mode="after")
    def _validate_gate_settings(self) -> "Settings":
        """啟動時即檢查一致性閘門設定，避免執行期才發現配置錯誤。"""
        if self.RAG_GATE_TOP_N < 1:
            raise ValueError("RAG_GATE_TOP_N 須至少為 1")
        if not 0.0 <= self.RAG_GATE_SIMILARITY <= 1.0:
            raise ValueError("RAG_GATE_SIMILARITY 須介於 0 與 1 之間")
        if not 0.0 <= self.RAG_DISPLAY_SIMILARITY_THRESHOLD <= 1.0:
            raise ValueError("RAG_DISPLAY_SIMILARITY_THRESHOLD 須介於 0 與 1 之間")
        if not 0.0 <= self.RAG_GATE_SHORT_SCAM_SIMILARITY <= 1.0:
            raise ValueError("RAG_GATE_SHORT_SCAM_SIMILARITY 須介於 0 與 1 之間")
        if self.RAG_GATE_SHORT_MESSAGE_CHARS < 0:
            raise ValueError("RAG_GATE_SHORT_MESSAGE_CHARS 不可為負數（0 表示停用短訊息規則）")
        if not 0.0 <= self.RISK_HIGH_SCORE <= 1.0:
            raise ValueError("RISK_HIGH_SCORE 須介於 0 與 1 之間（它是機率，不是 0-100 分）")
        # 投票人數不能超過檢索回來的候選數，否則閘門永遠湊不齊票、等同關閉——
        # 那是無聲的失效（沒有錯誤、只是每筆都走 LLM），必須在啟動時就擋下。
        if self.RAG_GATE_TOP_N > self.RAG_RETRIEVE_CANDIDATES:
            raise ValueError(
                f"RAG_GATE_TOP_N（{self.RAG_GATE_TOP_N}）不可大於 "
                f"RAG_RETRIEVE_CANDIDATES（{self.RAG_RETRIEVE_CANDIDATES}），"
                "否則閘門永遠無法湊齊票數，等同被無聲關閉"
            )
        return self

    @model_validator(mode="after")
    def _validate_stage_settings(self) -> "Settings":
        """啟動時即檢查階段判定設定（同上，不留到執行期才炸）。"""
        if not 0.0 <= self.RAG_STAGE_REGRESS_CONFIDENCE <= 1.0:
            raise ValueError("RAG_STAGE_REGRESS_CONFIDENCE 須介於 0 與 1 之間")
        if self.RAG_STAGE_MAX_MESSAGES < 1:
            raise ValueError("RAG_STAGE_MAX_MESSAGES 須至少為 1")
        if self.RAG_STAGE_MAX_CHARS < 1:
            raise ValueError("RAG_STAGE_MAX_CHARS 須至少為 1")
        return self


    @model_validator(mode="after")
    def _validate_local_model_settings(self) -> "Settings":
        """啟動時即檢查地端模型分發設定（同上，不留到執行期才炸）。"""
        if self.LOCAL_MODEL_URL_EXPIRE_HOURS < 1:
            raise ValueError("LOCAL_MODEL_URL_EXPIRE_HOURS 須至少為 1 小時")
        if self.LOCAL_MODEL_RATE_LIMIT_BYTES_PER_SEC < 0:
            raise ValueError("LOCAL_MODEL_RATE_LIMIT_BYTES_PER_SEC 不可為負數")

        # 兩顆模型的檔案欄位逐組檢查（偵測、階段）
        for sha_field, size_field in (
            ("LOCAL_MODEL_SHA256", "LOCAL_MODEL_SIZE_BYTES"),
            ("LOCAL_MODEL_STAGE_SHA256", "LOCAL_MODEL_STAGE_SIZE_BYTES"),
        ):
            sha256 = str(getattr(self, sha_field)).strip().lower()
            if sha256 and not re.fullmatch(r"[0-9a-f]{64}", sha256):
                raise ValueError(f"{sha_field} 須為 64 位十六進位字串")
            if getattr(self, size_field) < 0:
                raise ValueError(f"{size_field} 不可為負數")

        # 下載端點是以「檔名」反查模型的（簽章綁定檔名），兩顆同名就會互相蓋掉：
        # 拿階段模型的簽章會下載到偵測模型，而且沒有任何錯誤訊息。
        if self.LOCAL_MODEL_FILE_NAME == self.LOCAL_MODEL_STAGE_FILE_NAME:
            raise ValueError(
                "LOCAL_MODEL_FILE_NAME 與 LOCAL_MODEL_STAGE_FILE_NAME 不可相同"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """取得設定單例（lru_cache 確保整個程序只解析一次 .env）。"""
    return Settings()


# 全域設定單例，供各模組直接匯入使用
settings = get_settings()
