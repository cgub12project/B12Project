"""電話號碼查詢端點（電話頁 / 電話詳情頁，README 未列出、依功能補齊）。"""

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status

from app.api.dependencies import CurrentUser, DbSession
from app.crud import crud_phone, crud_user
from app.schemas.phone import (
    PhoneCommunityReportOut,
    PhoneDetailResponse,
    PhoneListResponse,
    PhoneOut,
)

router = APIRouter(prefix="/phones", tags=["電話查詢"])


def _mask_name(name: str) -> str:
    """遮罩回報者名稱以保護隱私（例如「王小明」→「王**」）。"""
    if not name:
        return "匿名"
    return name[0] + "*" * max(2, len(name) - 1)


@router.get(
    "",
    response_model=PhoneListResponse,
    summary="查詢電話號碼資料庫",
    description=(
        "電話頁的號碼列表：支援號碼關鍵字即時搜尋（search）、"
        "風險等級篩選（risk_level）與分頁（limit / offset）。"
    ),
)
async def list_phones(
    db: DbSession,
    current_user: CurrentUser,
    search: Annotated[str | None, Query(max_length=30, description="號碼關鍵字")] = None,
    risk_level: Annotated[
        Literal["high", "mid", "safe"] | None, Query(description="風險等級篩選")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100, description="每頁筆數")] = 20,
    offset: Annotated[int, Query(ge=0, description="略過筆數")] = 0,
) -> PhoneListResponse:
    total, phones = await crud_phone.list_phones(
        db, search=search, risk_level=risk_level, limit=limit, offset=offset
    )
    return PhoneListResponse(
        total=total, items=[PhoneOut.model_validate(phone) for phone in phones]
    )


@router.get(
    "/{phone_number}",
    response_model=PhoneDetailResponse,
    summary="查詢電話詳情",
    description="電話詳情頁：號碼風險資訊 + 社群回報列表（回報者名稱已遮罩）。",
)
async def get_phone_detail(
    phone_number: str, db: DbSession, current_user: CurrentUser
) -> PhoneDetailResponse:
    phone = await crud_phone.get_detail_with_reports(db, phone_number)
    if phone is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="此號碼尚無詐騙情報",
        )

    # 取得各回報者名稱並遮罩（逐筆查詢；單一號碼回報數量有限，可接受）
    report_items: list[PhoneCommunityReportOut] = []
    for report in sorted(phone.reports, key=lambda r: r.created_at, reverse=True):
        reporter = await crud_user.get_by_id(db, report.user_id)
        report_items.append(
            PhoneCommunityReportOut(
                id=report.id,
                fraud_type=report.fraud_type,
                content=report.content,
                reporter=_mask_name(reporter.name if reporter else ""),
                created_at=report.created_at,
            )
        )

    return PhoneDetailResponse(
        id=phone.id,
        phone_number=phone.phone_number,
        risk_level=phone.risk_level,
        fraud_type=phone.fraud_type,
        report_count=phone.report_count,
        last_reported_at=phone.last_reported_at,
        created_at=phone.created_at,
        reports=report_items,
    )
