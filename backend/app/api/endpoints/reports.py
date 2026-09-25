"""詐騙回報端點：電話回報、帳號回報、完整回報與個人回報紀錄。"""

import re
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.api.dependencies import CurrentUser, DbSession
from app.crud import crud_phone, crud_report
from app.schemas.report import (
    FullReportRequest,
    MessageReportBody,
    MyReportsResponse,
    PhoneReportRequest,
    ReportSubmitResponse,
)

router = APIRouter(prefix="/reports", tags=["詐騙回報"])

# 電話號碼格式：允許數字、+、-、空格，長度 3-30（涵蓋國際碼與市話）
PHONE_PATTERN = re.compile(r"^[0-9+\-\s]{3,30}$")


@router.post(
    "/phone/{phone_number}",
    response_model=ReportSubmitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="回報詐騙電話號碼",
    description=(
        "回報一組詐騙電話號碼（App 的 ReportBottomSheet）。"
        "號碼不存在時自動建檔，並依社群舉報次數更新風險等級。"
    ),
)
async def report_phone(
    phone_number: str, body: PhoneReportRequest, db: DbSession, current_user: CurrentUser
) -> ReportSubmitResponse:
    # 基本號碼格式驗證（路徑參數無法用 pydantic 驗證格式）
    normalized = phone_number.strip()
    if not PHONE_PATTERN.fullmatch(normalized):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="電話號碼格式不正確",
        )

    report = await crud_phone.add_report(
        db,
        phone_number=normalized,
        user_id=current_user.id,
        fraud_type=body.fraud_type,
        content=body.content,
        description=body.description,
    )
    return ReportSubmitResponse(
        message="回報成功，感謝您協助建立防詐情報",
        report_id=report.id,
    )


@router.post(
    "/account",
    response_model=ReportSubmitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="回報可疑社群帳號",
    description=(
        "回報一個可疑社群帳號（App 的 MessageReportBottomSheet）。"
        "自動建立／關聯可疑帳號檔案並更新其風險評分，回傳案件編號。"
    ),
)
async def report_account(
    body: MessageReportBody, db: DbSession, current_user: CurrentUser
) -> ReportSubmitResponse:
    report = await crud_report.create_account_report(
        db,
        user_id=current_user.id,
        fraud_type=body.fraud_type,
        content=body.content,
        platform=body.platform,
        account_name=body.account_name,
        external_account_id=body.account_id,
        description=body.description,
    )
    return ReportSubmitResponse(
        message="回報成功，感謝您協助建立防詐情報",
        report_id=report.id,
        case_number=report.case_number,
    )


@router.post(
    "/full",
    response_model=ReportSubmitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="提交完整回報",
    description=(
        "完整回報（App 的 ReportFullActivity）：詐騙類型 + 事件描述 + "
        "附加證據，成功後產生案件編號（FR-yyyymmdd-XXXXXX）。"
    ),
)
async def report_full(
    body: FullReportRequest, db: DbSession, current_user: CurrentUser
) -> ReportSubmitResponse:
    report = await crud_report.create_full_report(
        db,
        user_id=current_user.id,
        fraud_type=body.fraud_type,
        content=body.content,
        description=body.description,
        evidence_files=body.evidence_files,
    )
    return ReportSubmitResponse(
        message="回報已受理",
        report_id=report.id,
        case_number=report.case_number,
    )


@router.get(
    "/mine",
    response_model=MyReportsResponse,
    summary="查詢個人回報紀錄",
    description="合併電話／帳號／完整回報，依時間新到舊排序（kind 欄位區分種類）。",
)
async def list_my_reports(
    db: DbSession,
    current_user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100, description="每頁筆數")] = 20,
    offset: Annotated[int, Query(ge=0, description="略過筆數")] = 0,
) -> MyReportsResponse:
    total, items = await crud_report.list_user_reports(
        db, current_user.id, limit=limit, offset=offset
    )
    return MyReportsResponse(total=total, items=items)
