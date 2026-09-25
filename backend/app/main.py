"""F.L.A.S.H. 後端應用程式進入點。

啟動方式（開發）：
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

API 文件（Swagger UI）：http://127.0.0.1:8000/docs
"""

# ⚠ 必須是本檔的第一個 import：先把 pyarrow 的原生程式庫（arrow.dll）載進行程。
#
# 原本 pyarrow 是在第一次呼叫 /rag/detect 時才被載入的——嵌入模型走
# FlagEmbedding → sentence-transformers → sklearn → pandas → pyarrow 這條鏈，
# 而那時行程裡已經有 aiomysql（pymysql._auth → cryptography／_ssl 的 OpenSSL）
# 與 torch 等一大票原生擴充。在 Windows 上這個載入順序會讓 arrow.dll 初始化時
# 直接 access violation（0xc0000005），整個 uvicorn 行程當場消失：本機 Swagger
# 顯示 "Failed to fetch"、走 Cloudflare Tunnel 則是 502 origin_bad_gateway，
# 兩者都不是 CORS 問題，而是後端根本沒有回應就死了。Python 例外處理救不了
# 原生層的當機，所以 RagUnavailableError 那套 503 也接不到。
#
# 實測（Python 3.12 / pyarrow 24 / pandas 3.0 / torch 2.11）：不預載必掛，
# 預載後同一條路徑穩定通過。把 pyarrow 排在所有相依套件之前載入即可避開。
import pyarrow  # noqa: F401  (必須最先載入，見上方說明)

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.endpoints import (
    accounts,
    auth,
    local_model,
    mail,
    phones,
    rag,
    reports,
    users,
)
from app.core.config import settings
from app.db.base import Base
from app.db.session import engine
from app.services.local_model import install_access_log_token_filter
from app.services.mail_sync import run_scheduled_sync_loop

# 日誌設定：開發模式輸出 INFO 等級
logging.basicConfig(
    level=logging.INFO if settings.DEBUG else logging.WARNING,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用程式生命週期：啟動時可選擇自動建表，關閉時釋放連線池。"""
    # 地端模型的下載授權內嵌在網址裡，先掛上過濾器，避免權杖被寫進存取日誌
    install_access_log_token_filter()

    # 開發便利功能：AUTO_CREATE_TABLES=true 時自動建立缺少的資料表
    # （正式環境請使用 alembic upgrade head 管理 schema）
    if settings.AUTO_CREATE_TABLES:
        import app.models  # noqa: F401  # 確保所有模型已註冊至 Base.metadata

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("已自動建立資料表（AUTO_CREATE_TABLES=true）")

    # 信箱輪詢排程：定期抓取已連接信箱的新信並做 AI 判斷
    # （決策 1 採輪詢；這條路徑是「App 沒開也持續更新」的來源）
    sync_task: asyncio.Task | None = None
    if settings.MAIL_SYNC_ENABLED:
        sync_task = asyncio.create_task(run_scheduled_sync_loop())
    else:
        logger.info("信箱輪詢排程未啟用（MAIL_SYNC_ENABLED=false）")

    logger.info("%s 啟動完成", settings.PROJECT_NAME)
    yield

    # 先停排程再關連線池，避免同步中途連線被抽掉
    if sync_task is not None:
        sync_task.cancel()
        try:
            await sync_task
        except asyncio.CancelledError:
            pass

    # 關閉時釋放資料庫連線池
    await engine.dispose()
    logger.info("資料庫連線池已釋放，服務關閉")


# OpenAPI 文件的標籤說明（Swagger UI 分組顯示）
openapi_tags = [
    {"name": "認證", "description": "登入、註冊、忘記密碼（OTP）、社交登入與權杖管理"},
    {"name": "使用者", "description": "個人資料與設定開關（跨裝置同步來源）"},
    {"name": "電話查詢", "description": "詐騙電話號碼資料庫查詢（電話頁／電話詳情頁）"},
    {"name": "可疑帳號", "description": "帳號威脅檔案：風險評分、觸發規則與證據摘要"},
    {"name": "詐騙回報", "description": "電話回報、帳號回報、完整回報與個人回報紀錄"},
    {"name": "RAG 詐騙偵測", "description": "BGE-M3 向量檢索 + 本地 LLM 的詐騙訊息偵測"},
    {
        "name": "信箱連接",
        "description": (
            "連接 Gmail／Outlook 後由後端定期抓信並做 AI 判斷；"
            "資料庫只存判定結果，信件內容不落地"
        ),
    },
    {
        "name": "地端模型",
        "description": (
            "App 離線／地端模式的 GGUF 模型分發：驗證登入後核發短效簽章下載網址，"
            "檔案支援 HTTP Range 續傳。此路徑不做任何推論"
        ),
    },
    {"name": "系統", "description": "健康檢查等系統端點"},
]

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.PROJECT_VERSION,
    description=(
        "**F.L.A.S.H.（Fraud Locator And Scam Hunter）** 詐騙感知防護系統後端 API。\n\n"
        "- 認證方式：JWT Bearer Token（`Authorization: Bearer <access_token>`）\n"
        "- 風險三級制：`high`（高危）／`mid`（可疑）／`safe`（安全）\n"
        "- RAG 偵測：BGE-M3 向量檢索 + ChromaDB + Ollama 本地 LLM"
    ),
    openapi_tags=openapi_tags,
    lifespan=lifespan,
)

# CORS：允許 App／開發工具跨來源存取
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 掛載各功能路由（統一 /api/v1 前綴）
app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(users.router, prefix=settings.API_V1_PREFIX)
app.include_router(phones.router, prefix=settings.API_V1_PREFIX)
app.include_router(accounts.router, prefix=settings.API_V1_PREFIX)
app.include_router(reports.router, prefix=settings.API_V1_PREFIX)
app.include_router(rag.router, prefix=settings.API_V1_PREFIX)
app.include_router(mail.router, prefix=settings.API_V1_PREFIX)
app.include_router(local_model.router, prefix=settings.API_V1_PREFIX)


@app.get("/health", tags=["系統"], summary="健康檢查")
async def health_check() -> dict:
    """健康檢查端點（部署監控／Cloudflare Tunnel 存活探測用）。"""
    return {"status": "ok", "service": settings.PROJECT_NAME, "version": settings.PROJECT_VERSION}
