"""可疑帳號端點（帳號威脅檔案頁，README 未列出、依功能補齊）。"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.api.dependencies import CurrentUser, DbSession
from app.crud import crud_account
from app.schemas.account import (
    SuspectAccountDetailResponse,
    SuspectAccountListResponse,
    SuspectAccountOut,
)

router = APIRouter(prefix="/accounts", tags=["可疑帳號"])


@router.get(
    "",
    response_model=SuspectAccountListResponse,
    summary="查詢可疑帳號列表",
    description="支援平台篩選（platform）、帳號名稱／ID 關鍵字搜尋（search）與分頁。",
)
async def list_accounts(
    db: DbSession,
    current_user: CurrentUser,
    platform: Annotated[str | None, Query(max_length=20, description="平台篩選")] = None,
    search: Annotated[str | None, Query(max_length=100, description="帳號關鍵字")] = None,
    limit: Annotated[int, Query(ge=1, le=100, description="每頁筆數")] = 20,
    offset: Annotated[int, Query(ge=0, description="略過筆數")] = 0,
) -> SuspectAccountListResponse:
    total, accounts = await crud_account.list_accounts(
        db, platform=platform, search=search, limit=limit, offset=offset
    )
    return SuspectAccountListResponse(
        total=total,
        items=[SuspectAccountOut.model_validate(account) for account in accounts],
    )


@router.get(
    "/{account_id}",
    response_model=SuspectAccountDetailResponse,
    summary="查詢帳號威脅檔案",
    description=(
        "帳號威脅檔案頁：風險評分（0-100 環形圖）、觸發規則標籤、"
        "AI 威脅摘要與證據摘要列表。"
    ),
)
async def get_account_detail(
    account_id: int, db: DbSession, current_user: CurrentUser
) -> SuspectAccountDetailResponse:
    account = await crud_account.get_detail(db, account_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="查無此可疑帳號"
        )
    return SuspectAccountDetailResponse.model_validate(account)
