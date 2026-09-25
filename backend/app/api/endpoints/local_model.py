"""地端模型下載端點（新增功能，供 App 的離線／地端模式使用）。

- GET  /local-model/catalog               列出所有可下載的地端模型（各自附簽章網址）
- GET  /local-model/manifest[?model=]     取得單一模型的版本、大小、SHA-256 與下載網址
- GET|HEAD /local-model/download/{檔名}    以簽章網址下載模型（支援 Range 續傳）

**目前提供兩顆模型**（`app/services/local_model.py` 的 `MODEL_IDS`）：

    detect  flash-v5.gguf      判「是不是詐騙」          ← `?model=` 的預設值
    stage   flash-stage-v2.gguf  判「詐騙演進到哪一階段」

`/manifest` 不帶 `?model=` 時回的仍是偵測模型、欄位一個沒動——第二顆是**加**上來的，
不是改出來的，已上架的 App 版本不必跟著改就能繼續運作。

設計重點（詳見 `docs/local_model_deployment.md`）：

- **這裡不做推論**。模型檔只是靜態檔案，使用者選擇地端模式後下載到手機，
  訊息內容一律留在手機本機，不會回到後端。
- **manifest 用 Bearer、下載用簽章網址**。下載是 Android 下載元件發出的請求
  （App 可能已被系統回收），那條請求不會帶 Authorization 標頭，所以授權必須
  內嵌在網址裡：短效（預設 24 小時）、不可猜測、綁定檔名與版本。
- **1.93 GB 不經應用層**。設定 LOCAL_MODEL_XACCEL_LOCATION 後，後端只回一組
  標頭，檔案本體由 Nginx 從 internal location 送出；未設定時退回由 Starlette
  的 FileResponse 分塊串流（同樣支援 Range，但吞吐不如 Nginx，僅適合開發）。
- **簽章綁定的是檔名與版本，不是模型代號**。所以拿偵測模型的網址要不到階段模型，
  反之亦然；某一顆換版時也只有那一顆的舊網址失效。
"""

import logging
from typing import Annotated

import jwt
from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUser, DbSession
from app.core.config import settings
from app.core.security import create_local_model_token, decode_local_model_token
from app.crud import crud_user
from app.schemas.local_model import (
    LocalModelCatalog,
    LocalModelCatalogEntry,
    LocalModelManifest,
)
from app.services.local_model import (
    DETECT_MODEL_ID,
    MODEL_IDS,
    LocalModelFile,
    LocalModelUnavailableError,
    UnknownLocalModelError,
    build_download_url,
    get_deployed_models,
    get_model_file,
    spec_for_file_name,
    xaccel_headers,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/local-model", tags=["地端模型"])

# 簽章網址一律不進快取：網址本身就是授權，不該被中間層留存
_NO_STORE = "private, no-store"


async def _require_model_file(model_id: str = DETECT_MODEL_ID) -> LocalModelFile:
    """取得部署中的模型檔；代號不存在回 404，未部署／設定不符回 503。"""
    try:
        return await get_model_file(model_id)
    except UnknownLocalModelError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"沒有這個模型代號，可用的是：{'、'.join(MODEL_IDS)}",
        ) from exc
    except LocalModelUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


def _issue_manifest(model: LocalModelFile, user_id: int, base_url: str) -> dict:
    """為一顆模型核發簽章並組出 manifest 的欄位（manifest 與 catalog 共用）。

    每顆模型各發各的簽章：權杖綁定檔名與版本，所以一顆換版不會讓另一顆的
    下載網址失效，App 也不會拿著偵測模型的網址去要階段模型。
    """
    token, expires_at = create_local_model_token(
        user_id,
        file_name=model.file_name,
        version=model.version,
        expire_hours=settings.LOCAL_MODEL_URL_EXPIRE_HOURS,
    )
    return {
        "version": model.version,
        "file_name": model.file_name,
        "size_bytes": model.size_bytes,
        "sha256": model.sha256,
        "download_url": build_download_url(token, model.file_name, base_url),
        "expires_at": expires_at,
    }


@router.get(
    "/catalog",
    response_model=LocalModelCatalog,
    summary="列出所有可下載的地端模型",
    description=(
        "一次取得目前提供的**每一顆**地端模型（各自附自己的短效簽章下載網址）。\n\n"
        "目前有兩顆：`detect`（詐騙偵測）與 `stage`（詐騙階段判定）。兩顆各約 1.93 GB，"
        "可以只下載其中一顆——沒有階段模型時 App 仍可正常做偵測。\n\n"
        "- 只列出**已部署完成**的模型；某一顆還沒上傳或設定不符就不會出現在清單裡"
        "（不會讓整份 catalog 失敗）\n"
        "- 請依 `model_id` 取用，不要依賴陣列順序\n"
        "- 未帶 Authorization → 401；帳號停用 → 403；一顆都沒部署 → 503"
    ),
)
async def list_local_models(
    request: Request, current_user: CurrentUser
) -> LocalModelCatalog:
    models = await get_deployed_models()
    if not models:
        # 一顆都沒有時回 503（與單顆 manifest 一致），而不是一份空清單——
        # 空清單在 App 端會被當成「這個版本沒有地端模式」，而不是「伺服器還沒佈好」。
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="目前沒有可下載的地端模型",
        )

    base_url = str(request.base_url)
    return LocalModelCatalog(
        models=[
            LocalModelCatalogEntry(
                model_id=model.model_id,
                role=model.role,
                **_issue_manifest(model, current_user.id, base_url),
            )
            for model in models
        ]
    )


@router.get(
    "/manifest",
    response_model=LocalModelManifest,
    summary="取得單一地端模型的版本資訊與下載網址",
    description=(
        "回傳指定模型的版本、檔名、大小、SHA-256 與**短效簽章下載網址**"
        "（預設 24 小時有效，足以容納 1.93 GB 的慢速下載與中斷續傳）。\n\n"
        "- `model` 可填 `detect`（詐騙偵測，**預設值**）或 `stage`（詐騙階段判定）；"
        "不帶這個參數時的行為與加入階段模型之前完全相同\n"
        "- 未帶 Authorization → 401；帳號停用 → 403；"
        "代號不存在 → 404；這顆尚未部署 → 503\n"
        "- `download_url` 已內含授權，下載時不需再帶 Authorization 標頭\n"
        "- 網址過期只需重新呼叫本端點換一組，已下載的部分可繼續續傳"
    ),
)
async def get_local_model_manifest(
    request: Request,
    current_user: CurrentUser,
    model: Annotated[
        str, Query(description="模型代號：detect（預設）或 stage")
    ] = DETECT_MODEL_ID,
) -> LocalModelManifest:
    model_file = await _require_model_file(model)
    return LocalModelManifest(
        **_issue_manifest(model_file, current_user.id, str(request.base_url))
    )


async def _authorize_download(
    db: AsyncSession, token: str | None, file_name: str
) -> int:
    """驗證下載簽章，回傳使用者 ID。

    Raises:
        HTTPException 401: 未帶簽章、簽章無效／過期、或簽章對應的使用者不存在。
        HTTPException 403: 帳號已被停用。
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="請使用 /local-model/manifest 取得的下載網址",
        )

    try:
        user_id, token_file, token_version = decode_local_model_token(token)
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="下載網址無效或已過期，請重新取得 manifest",
        ) from None

    # 簽章綁定檔名與版本：
    #   - 檔名對不上 → 拿偵測模型的簽章要不到階段模型（兩顆的版本號各自獨立）
    #   - 版本對不上 → 那一顆換版後，它的舊網址失效（另一顆不受影響）
    spec = spec_for_file_name(file_name)
    if spec is None or token_file != file_name or token_version != spec.version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="下載網址與目前提供的模型版本不符，請重新取得 manifest",
        )

    # 簽章有效期長達 24 小時，這段期間帳號可能已被停用，因此仍要回資料庫確認
    user = await crud_user.get_by_id(db, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="使用者不存在"
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="帳號已被停用"
        )
    return user.id


@router.get(
    "/authorize",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="驗證下載簽章（Nginx auth_request／Caddy forward_auth 專用）",
    description=(
        "只驗證簽章、不送檔案：通過回 **204**，未通過回 401／403。\n\n"
        "供需求書第五節方案 C 使用——由 Nginx `auth_request` 或 Caddy "
        "`forward_auth` 先向後端做輕量權限檢查，確認後直接由網頁伺服器送出模型檔，"
        "1.93 GB 完全不經過本後端。"
    ),
    responses={
        204: {"description": "簽章有效"},
        401: {"description": "未帶簽章、簽章無效或已過期"},
        403: {"description": "帳號已被停用"},
    },
)
async def authorize_local_model_download(
    db: DbSession,
    token: Annotated[
        str | None, Query(description="manifest 核發的短效下載簽章")
    ] = None,
    file: Annotated[
        str | None, Query(description="要下載的檔名；不帶則以偵測模型為準")
    ] = None,
) -> Response:
    await _authorize_download(db, token, file or settings.LOCAL_MODEL_FILE_NAME)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _serve_model_file(file_name: str, db: AsyncSession, token: str | None) -> Response:
    """驗證簽章後回應模型檔（GET 與 HEAD 共用；HEAD 由回應層自行只送標頭）。"""
    # 先以檔名反查是哪一顆模型：路徑參數只用來查表、不參與檔案系統路徑組合，
    # 實際送出的永遠是設定裡那兩個路徑之一，不存在路徑穿越風險。
    spec = spec_for_file_name(file_name)
    if spec is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="找不到此模型檔")

    user_id = await _authorize_download(db, token, file_name)
    model = await _require_model_file(spec.model_id)
    logger.info(
        "使用者 %d 下載地端模型 %s（%s v%s）",
        user_id,
        model.file_name,
        model.model_id,
        model.version,
    )

    if (headers := xaccel_headers(model)) is not None:
        # X-Accel-Redirect：檔案本體交給 Nginx，這裡只回標頭。
        # 必須拿掉 Response 自動加上的 content-length: 0，否則 Nginx 會照著
        # 這個長度回應，App 只會收到 0 bytes。
        response = Response(status_code=status.HTTP_200_OK, headers=headers)
        del response.headers["content-length"]
        response.headers["Cache-Control"] = _NO_STORE
        return response

    # 後備路徑（未設定 Nginx internal location）：由 Starlette 分塊串流，
    # Range／ETag／Last-Modified／HEAD 皆由 FileResponse 處理，不會整包讀進記憶體。
    return FileResponse(
        model.path,
        media_type="application/octet-stream",
        filename=model.file_name,
        headers={"Cache-Control": _NO_STORE},
    )


@router.get(
    "/download/{file_name}",
    response_class=FileResponse,
    summary="下載地端模型（簽章網址，支援 Range 續傳）",
    description=(
        "以 manifest 提供的簽章網址下載模型檔。\n\n"
        "- 支援 `Range`：帶 `Range: bytes=0-1048575` 會回 **206 Partial Content**，"
        "並附 `Accept-Ranges: bytes`、`Content-Range`、`Content-Length`\n"
        "- 支援 `HEAD`：只回標頭（含 `Content-Length`、`ETag`、`Last-Modified`），"
        "可用來確認檔案是否換版\n"
        "- `Content-Type: application/octet-stream`、"
        "`Content-Disposition: attachment`\n"
        "- 無簽章／簽章無效或過期 → 401；帳號停用 → 403；"
        "檔名不是目前提供的任何一顆模型 → 404"
    ),
    responses={
        200: {"content": {"application/octet-stream": {}}, "description": "完整檔案"},
        206: {"description": "Range 續傳的部分內容"},
        401: {"description": "未帶簽章、簽章無效或已過期"},
        403: {"description": "帳號已被停用"},
        404: {"description": "檔名不是目前提供的任何一顆模型"},
        416: {"description": "Range 超出檔案範圍"},
        503: {"description": "模型尚未部署"},
    },
)
async def download_local_model(
    file_name: str,
    db: DbSession,
    token: Annotated[
        str | None, Query(description="manifest 核發的短效下載簽章")
    ] = None,
) -> Response:
    return await _serve_model_file(file_name, db, token)


# HEAD 與 GET 走同一份實作；分開註冊只是為了讓兩者各有自己的 operation id
# （同一個 api_route 同時掛 GET/HEAD 會讓 FastAPI 產生重複的 operation id）。
@router.head("/download/{file_name}", include_in_schema=False)
async def head_local_model(
    file_name: str,
    db: DbSession,
    token: Annotated[
        str | None, Query(description="manifest 核發的短效下載簽章")
    ] = None,
) -> Response:
    return await _serve_model_file(file_name, db, token)
