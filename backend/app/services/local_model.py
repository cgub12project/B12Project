"""地端模型分發服務（App 離線模式的 GGUF 模型下載）。

這條路徑刻意**不接**任何推論流程：模型檔只是一份 1.93 GB 的靜態檔案，後端在
這裡的角色是「驗身分 → 發短效簽章網址 → 授權後放行檔案」，訊息內容不會經過
後端。詳細部署方式見 `docs/local_model_deployment.md`。

**一共兩顆模型**（`MODEL_IDS`），對應手機上的兩段判定：

    detect  flash-v5.gguf      判「是不是詐騙」          LOCAL_MODEL_*
    stage   flash-stage-v2.gguf  判「詐騙演進到哪一階段」  LOCAL_MODEL_STAGE_*

兩顆各自獨立部署、獨立換版、獨立發簽章，彼此不擋路：階段那顆沒部署時偵測那條線
完全照舊（catalog 少列一項、`?model=stage` 回 503）。理由與後端把階段做成獨立第二段
判定的理由相同——一顆換版不該動到另一顆。

刻意**不做**的事：不提供「一次下載兩顆」的打包檔。手機端兩顆各 1.93 GB，使用者
可能只要偵測那顆；打包後 Range 續傳與 SHA-256 核對也都得整包重來。

本模組負責四件事：

1. 讀出部署狀態（路徑、大小、SHA-256），並在「設定與實際檔案對不上」時擋下
   manifest——寧可回 503，也不要發一份 sha256 永遠核對不過的 manifest，
   讓使用者白下載 1.93 GB 才在最後一步失敗。
2. SHA-256 快取：正式環境應在 .env 直接填好；沒填時才自行讀滿一次磁碟計算，
   並以（路徑, mtime, 大小）為鍵快取，換檔會自動失效。
3. 組出對外的短效下載網址。
4. X-Accel-Redirect 標頭：交給 Nginx 送檔，1.93 GB 不經 Python 應用層。
"""

import asyncio
import hashlib
import logging
import os
import re
import stat as stat_module
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import anyio

from app.core.config import settings

logger = logging.getLogger(__name__)

# 計算 SHA-256 時的讀取區塊大小（1 MB：大檔用大區塊可明顯減少系統呼叫次數）
_HASH_CHUNK_SIZE = 1024 * 1024

# SHA-256 快取：以（路徑, mtime_ns, 大小）為鍵，換上新的模型檔即自動失效
_sha256_cache: dict[tuple[str, int, int], str] = {}
_sha256_lock = asyncio.Lock()


# 對外的模型代號（manifest 的 `?model=` 與 catalog 的 model_id 用的就是這兩個字串）。
# 這兩個值是 API 契約的一部分，改了 App 端就要跟著改。
DETECT_MODEL_ID = "detect"
STAGE_MODEL_ID = "stage"
MODEL_IDS = (DETECT_MODEL_ID, STAGE_MODEL_ID)


class LocalModelUnavailableError(RuntimeError):
    """模型尚未部署，或部署狀態與設定不符（端點對應 503）。"""


class UnknownLocalModelError(LookupError):
    """指定的模型代號不存在（端點對應 404）。"""


@dataclass(frozen=True)
class LocalModelSpec:
    """一顆模型在設定裡宣告的樣子（還沒去看磁碟上有沒有這個檔案）。"""

    model_id: str
    role: str  # 給 App 顯示用的一句話，不參與任何判斷
    enabled: bool
    version: str
    file_name: str
    path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class LocalModelFile:
    """目前部署中的模型檔（磁碟上的檔案已確認與設定相符）。"""

    model_id: str
    role: str
    path: Path
    file_name: str
    version: str
    size_bytes: int
    sha256: str


def model_specs() -> dict[str, LocalModelSpec]:
    """讀出兩顆模型的設定。

    每次呼叫都重讀 settings（而不是在 import 時算好一份）：測試會 monkeypatch
    這些欄位，而正式環境換版是改 .env 後重啟，兩邊都不該依賴模組載入時的快照。
    """
    return {
        DETECT_MODEL_ID: LocalModelSpec(
            model_id=DETECT_MODEL_ID,
            role="詐騙偵測（判斷訊息是不是詐騙）",
            enabled=True,  # 偵測是地端模式的必要條件，只受總開關管
            version=settings.LOCAL_MODEL_VERSION,
            file_name=settings.LOCAL_MODEL_FILE_NAME,
            path=settings.LOCAL_MODEL_PATH,
            sha256=settings.LOCAL_MODEL_SHA256,
            size_bytes=settings.LOCAL_MODEL_SIZE_BYTES,
        ),
        STAGE_MODEL_ID: LocalModelSpec(
            model_id=STAGE_MODEL_ID,
            role="詐騙階段判定（判斷對話演進到哪一階段）",
            enabled=settings.LOCAL_MODEL_STAGE_ENABLED,
            version=settings.LOCAL_MODEL_STAGE_VERSION,
            file_name=settings.LOCAL_MODEL_STAGE_FILE_NAME,
            path=settings.LOCAL_MODEL_STAGE_PATH,
            sha256=settings.LOCAL_MODEL_STAGE_SHA256,
            size_bytes=settings.LOCAL_MODEL_STAGE_SIZE_BYTES,
        ),
    }


def spec_for_file_name(file_name: str) -> LocalModelSpec | None:
    """以對外檔名反查是哪一顆模型（下載端點驗簽時用），找不到回 None。

    檔名是下載路徑的最後一段，也是簽章裡綁定的欄位。設定檢查已保證兩顆不同名
    （見 Settings._validate_local_model_settings），所以這裡不會有多重命中。
    """
    for spec in model_specs().values():
        if spec.file_name == file_name:
            return spec
    return None


def _hash_file(path: Path) -> str:
    """讀滿整個檔案計算 SHA-256（同步；呼叫端須丟到工作執行緒）。"""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(_HASH_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


async def _resolve_sha256(path: Path, stat_result: os.stat_result) -> str:
    """取得檔案的 SHA-256（優先用快取，未命中才實際計算）。"""
    key = (str(path), stat_result.st_mtime_ns, stat_result.st_size)
    if (cached := _sha256_cache.get(key)) is not None:
        return cached

    # 上鎖再確認一次：多個請求同時打進來時只計算一次，其餘等這一次的結果
    async with _sha256_lock:
        if (cached := _sha256_cache.get(key)) is not None:
            return cached
        logger.warning(
            "未設定 SHA-256 設定值，正在計算 %s 的雜湊（%.2f GB，需讀滿整個檔案）",
            path,
            stat_result.st_size / 1024**3,
        )
        digest = await anyio.to_thread.run_sync(_hash_file, path)
        _sha256_cache[key] = digest
        logger.info("模型檔 %s 的 SHA-256 = %s（已快取）", path, digest)
        return digest


async def get_model_file(model_id: str = DETECT_MODEL_ID) -> LocalModelFile:
    """讀出指定模型目前部署中的檔案資訊（預設為偵測模型）。

    Raises:
        UnknownLocalModelError: model_id 不是 MODEL_IDS 之一。
        LocalModelUnavailableError: 功能未啟用、這顆尚未部署、檔案不存在，
            或實際檔案大小與該顆設定的 SIZE_BYTES 不符。
    """
    spec = model_specs().get(model_id)
    if spec is None:
        raise UnknownLocalModelError(model_id)

    if not settings.LOCAL_MODEL_ENABLED:
        raise LocalModelUnavailableError("地端模型下載功能未啟用")
    if not spec.enabled:
        raise LocalModelUnavailableError(f"{spec.model_id} 模型目前未提供下載")

    raw_path = spec.path.strip()
    if not raw_path:
        raise LocalModelUnavailableError(f"{spec.model_id} 模型尚未部署（未設定路徑）")

    path = Path(raw_path)
    try:
        stat_result = await anyio.to_thread.run_sync(os.stat, path)
    except OSError as exc:
        logger.error("讀不到地端模型檔 %s：%s", path, exc)
        raise LocalModelUnavailableError("地端模型檔案不存在或無法讀取") from exc

    if not stat_module.S_ISREG(stat_result.st_mode):
        raise LocalModelUnavailableError(f"{spec.model_id} 模型的路徑不是一般檔案")

    size_bytes = stat_result.st_size
    expected_size = spec.size_bytes
    if expected_size and expected_size != size_bytes:
        # 檔案不是預期的那一份（傳輸未完成／換版只改了一半的設定）。
        logger.error(
            "地端模型檔（%s）大小不符：實際 %d bytes，設定為 %d bytes",
            spec.model_id,
            size_bytes,
            expected_size,
        )
        raise LocalModelUnavailableError("地端模型檔案與設定不符，請確認部署狀態")

    sha256 = spec.sha256.strip().lower()
    if not sha256:
        sha256 = await _resolve_sha256(path, stat_result)

    return LocalModelFile(
        model_id=spec.model_id,
        role=spec.role,
        path=path,
        file_name=spec.file_name,
        version=spec.version,
        size_bytes=size_bytes,
        sha256=sha256,
    )


async def get_deployed_models() -> list[LocalModelFile]:
    """讀出所有「真的部署好了」的模型（catalog 用）。

    未部署或設定不符的那顆只是不列出來，不會讓整份 catalog 失敗——否則階段模型
    換版的空窗期會連偵測模型都下載不了。但會留一則 warning：catalog 少一項在
    App 端只會顯示成「沒有這顆可下載」，不看日誌就查不出其實是設定寫錯了。
    """
    deployed: list[LocalModelFile] = []
    for model_id in MODEL_IDS:
        try:
            deployed.append(await get_model_file(model_id))
        except LocalModelUnavailableError as exc:
            logger.warning("地端模型 %s 未列入 catalog：%s", model_id, exc)
    return deployed


def download_path(file_name: str) -> str:
    """下載端點的路徑（不含網域），例：/api/v1/local-model/download/flash-v5.gguf。"""
    return f"{settings.API_V1_PREFIX}/local-model/download/{quote(file_name)}"


def build_download_url(token: str, file_name: str, request_base_url: str) -> str:
    """組出對外的短效下載網址。

    正式環境請設定 LOCAL_MODEL_PUBLIC_BASE_URL（穩定的 HTTPS 正式網域）；
    留空時退回以請求本身的 base_url 組網址，僅供本機開發使用。
    """
    base = (settings.LOCAL_MODEL_PUBLIC_BASE_URL.strip() or request_base_url).rstrip("/")
    return f"{base}{download_path(file_name)}?token={quote(token, safe='')}"


def xaccel_headers(model: LocalModelFile) -> dict[str, str] | None:
    """X-Accel-Redirect 模式的回應標頭；未設定 internal location 時回傳 None。

    設定後，後端只回一組標頭（無內容），實際的 1.93 GB 由 Nginx 從 internal
    location 送出——Range／ETag／Last-Modified 一併由 Nginx 處理，Python 這端
    不碰檔案內容，也就不會有應用層緩衝整包檔案的問題。
    """
    location = settings.LOCAL_MODEL_XACCEL_LOCATION.strip()
    if not location:
        return None

    headers = {
        "X-Accel-Redirect": f"/{location.strip('/')}/{quote(model.file_name)}",
        "Content-Type": "application/octet-stream",
        "Content-Disposition": f'attachment; filename="{model.file_name}"',
        "Accept-Ranges": "bytes",
    }
    if settings.LOCAL_MODEL_RATE_LIMIT_BYTES_PER_SEC > 0:
        # 單一連線限速，避免少數下載把整台機器的頻寬吃光
        headers["X-Accel-Limit-Rate"] = str(settings.LOCAL_MODEL_RATE_LIMIT_BYTES_PER_SEC)
    return headers


# ============================================================
# 存取日誌：遮蔽網址上的下載權杖
# ============================================================

# 需求書要求「禁止把下載 token 寫入存取日誌」。下載授權必須內嵌在網址裡
# （下載元件不會帶 Authorization 標頭），而 uvicorn 的 access log 預設會把
# 完整的 query string 寫進日誌——落地的權杖等同於一條可直接使用的下載網址，
# 所以在寫進日誌前先換掉。Nginx 那一層的對應設定見部署文件。
_TOKEN_QUERY_RE = re.compile(r"([?&]token=)[^&\s]+")

_log_filter_installed = False


class _DownloadTokenLogFilter(logging.Filter):
    """把日誌訊息參數中的 `token=...` 換成 `token=REDACTED`。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                _TOKEN_QUERY_RE.sub(r"\1REDACTED", arg) if isinstance(arg, str) else arg
                for arg in record.args
            )
        return True


def install_access_log_token_filter() -> None:
    """為 uvicorn 存取日誌掛上權杖遮蔽過濾器（重複呼叫無副作用）。"""
    global _log_filter_installed
    if _log_filter_installed:
        return
    logging.getLogger("uvicorn.access").addFilter(_DownloadTokenLogFilter())
    _log_filter_installed = True
