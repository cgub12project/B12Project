"""RAG 端點（新增功能，README 未列出）。

- GET  /rag/reports              供 RAG 入庫程式（rag_worker.py）輪詢新的使用者回報
- POST /rag/detect               偵測單則訊息是否為詐騙（BGE-M3 向量檢索 + 本地 LLM）
- POST /rag/detect-conversation  對話級偵測：同上 + 判斷對話演進到哪個詐騙階段
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import CurrentUser, DbSession, verify_rag_api_key
from app.core.config import settings
from app.crud import crud_report
from app.db.base import utcnow
from app.schemas.rag import (
    RagDetectConversationRequest,
    RagDetectConversationResponse,
    RagDetectRequest,
    RagDetectResponse,
    RagReportsResponse,
)
from app.services.rag_service import RagService, RagUnavailableError, get_rag_service
from app.services.stage_service import (
    STAGE_UNAVAILABLE_MODEL,
    StageService,
    StageUnavailableError,
    get_stage_service,
)

router = APIRouter(prefix="/rag", tags=["RAG 詐騙偵測"])


@router.get(
    "/reports",
    response_model=RagReportsResponse,
    dependencies=[Depends(verify_rag_api_key)],
    summary="查詢新的使用者回報（RAG 入庫程式專用）",
    description=(
        "供 RAG 向量入庫程式每分鐘輪詢：回傳 since 時間之後的使用者回報"
        "（電話／帳號／完整回報的內容與詐騙類型）。"
        "此端點以 X-API-Key 標頭驗證，僅供內部服務使用。"
    ),
)
async def list_rag_reports(
    db: DbSession,
    since: Annotated[
        datetime | None,
        Query(description="只回傳此時間（UTC，ISO 8601）之後的回報；不帶則回傳全部"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=1000, description="最大回傳筆數")] = 500,
) -> RagReportsResponse:
    items = await crud_report.list_reports_since(db, since, limit=limit)
    return RagReportsResponse(server_time=utcnow(), count=len(items), items=items)


@router.post(
    "/detect",
    response_model=RagDetectResponse,
    summary="偵測訊息是否為詐騙",
    description=(
        "以嵌入模型將訊息轉為向量，從 ChromaDB 檢索相似度最高的多筆歷史案例。"
        "若最相似的 RAG_GATE_TOP_N 筆全部超過 RAG_GATE_SIMILARITY、"
        "且同屬一類（全為詐騙或全為一般訊息），即依該類直接判定"
        "（不呼叫 LLM，回應的 model 欄位為 similarity-gate，參數可於 .env 調整）；"
        "其餘情況一律交由本地 LLM（Ollama）綜合判斷。"
        "回應包含風險等級、判定理由、防詐建議與相似案例。"
        "similar_cases 呈現的是檢索到的相似案例，門檻與提示詞注入分開"
        "（RAG_DISPLAY_SIMILARITY_THRESHOLD），只有庫中確實沒有夠相似的案例時才為空。"
        "若 .env 設定 RAG_ENABLED=false，則跳過上述檢索與閘門，"
        "直接交由 LLM 判斷，此時 similar_cases 必為空陣列。"
    ),
)
async def detect_scam(
    body: RagDetectRequest,
    current_user: CurrentUser,
    rag: Annotated[RagService, Depends(get_rag_service)],
) -> RagDetectResponse:
    try:
        return await rag.detect(body.message)
    except RagUnavailableError as exc:
        # 模型未載入、向量庫或 Ollama 連線失敗等
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )


@router.post(
    "/detect-conversation",
    response_model=RagDetectConversationResponse,
    summary="偵測整段對話：是否為詐騙 + 目前的詐騙階段",
    description=(
        "供有來回對話的情境（LINE、簡訊）使用；單則訊息請用 /rag/detect。\n\n"
        "偵測部分：取**最後一則對方訊息**走與 /rag/detect 完全相同的流程"
        "（向量檢索 → 相似度閘門 →（區間內）LLM），結果與單則偵測一致。\n\n"
        "階段部分：判斷對話演進到 接觸建立／培養信任／鋪陳誘餌／索取財物／收尾拖延 "
        "五階段中的哪一個。判定為非詐騙且未帶 previous_stage 時不呼叫階段模型，"
        "stage 回 null。\n\n"
        "後端不儲存任何對話內容——請由 App 保存上次的 stage 並以 previous_stage 回傳，"
        "階段才不會因為舊訊息滑出視窗而倒退。"
    ),
)
async def detect_conversation(
    body: RagDetectConversationRequest,
    current_user: CurrentUser,
    rag: Annotated[RagService, Depends(get_rag_service)],
    stage_svc: Annotated[StageService, Depends(get_stage_service)],
) -> RagDetectConversationResponse:
    # 偵測的輸入必須是單則訊息原文：微調模型是用單則訊息訓練的，
    # 把整串對話串接後送進去等於餵它訓練分布外的輸入。
    last_counterpart = next(
        (message for message in reversed(body.messages) if message.sender == "them"), None
    )
    if last_counterpart is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="對話中沒有對方傳來的訊息，無法判定",
        )

    try:
        detection = await rag.detect(last_counterpart.text)
    except RagUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )

    # 已被標記為詐騙的對話（帶著 previous_stage 回來），即使對方最新一則是
    # 「好的」也要繼續判階段——否則階段會隨著一句無害的回話整個消失。
    needs_stage = detection.is_scam or body.previous_stage is not None
    if not settings.RAG_STAGE_ENABLED or not needs_stage:
        return RagDetectConversationResponse(**detection.model_dump())

    try:
        verdict = await stage_svc.classify(
            body.messages,
            scam_type=detection.scam_type,
            previous_stage=body.previous_stage,
        )
    except StageUnavailableError:
        # 偵測結果本身是好的，不因為階段判不出來就整包丟掉；
        # 以 stage_model 標示「判不出來」，與「不需要判」（null）分開
        return RagDetectConversationResponse(
            **detection.model_dump(), stage_model=STAGE_UNAVAILABLE_MODEL
        )

    return RagDetectConversationResponse(
        **detection.model_dump(),
        stage=verdict.stage,
        stage_label=verdict.label,
        stage_confidence=verdict.confidence,
        stage_reasons=verdict.reasons,
        next_step_warning=verdict.next_step_warning,
        stage_model=verdict.model,
    )
