"""詐騙回報（fraud_reports）的 CRUD 操作，以及供 RAG 使用的聯合查詢。"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_case_number
from app.crud import crud_account, crud_phone
from app.models.phone import PhoneReport
from app.models.report import FraudReport
from app.schemas.rag import RagReportItem
from app.schemas.report import MyReportItem


async def create_account_report(
    db: AsyncSession,
    *,
    user_id: int,
    fraud_type: str,
    content: str,
    platform: str,
    account_name: str,
    external_account_id: str | None,
    description: str | None,
) -> FraudReport:
    """建立帳號回報：關聯（或建立）可疑帳號並更新其風險統計。"""
    # 先取得／建立可疑帳號，並套用本次回報的風險統計
    account = await crud_account.get_or_create(
        db,
        platform=platform,
        account_name=account_name,
        external_account_id=external_account_id,
    )
    await crud_account.apply_report(db, account, fraud_type)

    report = FraudReport(
        case_number=generate_case_number("AC"),
        user_id=user_id,
        report_type="account",
        fraud_type=fraud_type,
        content=content,
        description=description,
        platform=platform,
        account_name=account_name,
        external_account_id=external_account_id,
        suspect_account_id=account.id,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return report


async def create_full_report(
    db: AsyncSession,
    *,
    user_id: int,
    fraud_type: str,
    content: str,
    description: str | None,
    evidence_files: list[str] | None,
) -> FraudReport:
    """建立完整回報（ReportFullActivity），產生 FR 開頭的案件編號。"""
    report = FraudReport(
        case_number=generate_case_number("FR"),
        user_id=user_id,
        report_type="full",
        fraud_type=fraud_type,
        content=content,
        description=description,
        evidence_files=evidence_files,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return report


async def list_user_reports(
    db: AsyncSession, user_id: int, *, limit: int = 20, offset: int = 0
) -> tuple[int, list[MyReportItem]]:
    """查詢個人回報紀錄：合併電話回報與帳號／完整回報，依時間新到舊排序。"""
    items: list[MyReportItem] = []

    # 電話回報
    for report, phone_number in await crud_phone.list_reports_by_user(db, user_id):
        items.append(
            MyReportItem(
                id=report.id,
                kind="phone",
                fraud_type=report.fraud_type,
                content=report.content,
                target=phone_number,
                case_number=None,
                status=report.status,
                created_at=report.created_at,
            )
        )

    # 帳號回報 + 完整回報
    result = await db.execute(
        select(FraudReport)
        .where(FraudReport.user_id == user_id)
        .order_by(FraudReport.created_at.desc())
    )
    for report in result.scalars().all():
        target = (
            f"{report.platform}/{report.account_name}"
            if report.report_type == "account"
            else "—"
        )
        items.append(
            MyReportItem(
                id=report.id,
                kind=report.report_type,  # "account" 或 "full"
                fraud_type=report.fraud_type,
                content=report.content,
                target=target,
                case_number=report.case_number,
                status=report.status,
                created_at=report.created_at,
            )
        )

    # 合併後統一排序與分頁（兩表資料量皆屬個人紀錄，記憶體排序可接受）
    items.sort(key=lambda item: item.created_at, reverse=True)
    total = len(items)
    return total, items[offset : offset + limit]


async def list_reports_since(
    db: AsyncSession, since: datetime | None, limit: int = 500
) -> list[RagReportItem]:
    """查詢指定時間之後的所有使用者回報（供 RAG Worker 向量入庫）。

    使用 >= 比較以避免同秒邊界漏資料；重複入庫由 ChromaDB
    upsert（確定性 ID）保證冪等，因此重複回傳無害。
    """
    items: list[RagReportItem] = []

    # 電話回報
    phone_query = select(PhoneReport).order_by(PhoneReport.created_at.asc()).limit(limit)
    if since is not None:
        phone_query = phone_query.where(PhoneReport.created_at >= since)
    for report in (await db.execute(phone_query)).scalars().all():
        items.append(
            RagReportItem(
                source="phone_report",
                id=report.id,
                content=report.content,
                scam_type=report.fraud_type,
                created_at=report.created_at,
            )
        )

    # 帳號回報 + 完整回報
    fraud_query = select(FraudReport).order_by(FraudReport.created_at.asc()).limit(limit)
    if since is not None:
        fraud_query = fraud_query.where(FraudReport.created_at >= since)
    for report in (await db.execute(fraud_query)).scalars().all():
        items.append(
            RagReportItem(
                source="fraud_report",
                id=report.id,
                content=report.content,
                scam_type=report.fraud_type,
                created_at=report.created_at,
            )
        )

    # 依時間排序後裁切至 limit
    items.sort(key=lambda item: item.created_at)
    return items[:limit]
