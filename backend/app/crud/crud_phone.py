"""電話號碼資料庫與電話回報的 CRUD 操作。"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.base import utcnow
from app.models.phone import PhoneNumber, PhoneReport

# 風險等級判定門檻：社群舉報達此次數即列為高危（可依營運需求調整）
HIGH_RISK_REPORT_THRESHOLD = 5


def _compute_risk_level(report_count: int) -> str:
    """依社群舉報次數計算風險等級（簡易規則，AI 引擎可再覆寫）。"""
    if report_count >= HIGH_RISK_REPORT_THRESHOLD:
        return "high"
    if report_count >= 1:
        return "mid"
    return "safe"


async def list_phones(
    db: AsyncSession,
    *,
    search: str | None = None,
    risk_level: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[int, list[PhoneNumber]]:
    """查詢電話號碼列表（支援號碼關鍵字搜尋、風險等級篩選、分頁）。

    Returns:
        (總筆數, 該頁項目)
    """
    query = select(PhoneNumber)
    if search:
        query = query.where(PhoneNumber.phone_number.contains(search))
    if risk_level:
        query = query.where(PhoneNumber.risk_level == risk_level)

    # 先算總數（供前端分頁）
    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar_one()

    # 依最後回報時間新到舊排序。注意：不可使用 NULLS LAST（PostgreSQL 語法，
    # MySQL/MariaDB 不支援）；MySQL 與 SQLite 皆將 NULL 視為最小值，
    # DESC 排序時 NULL 自然落在最後，行為相同。
    result = await db.execute(
        query.order_by(PhoneNumber.last_reported_at.desc(), PhoneNumber.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return total, list(result.scalars().all())


async def get_by_number(db: AsyncSession, phone_number: str) -> PhoneNumber | None:
    """依號碼取得電話資料。"""
    result = await db.execute(
        select(PhoneNumber).where(PhoneNumber.phone_number == phone_number)
    )
    return result.scalar_one_or_none()


async def get_detail_with_reports(
    db: AsyncSession, phone_number: str
) -> PhoneNumber | None:
    """取得電話詳情（預先載入社群回報，避免 N+1 查詢）。"""
    result = await db.execute(
        select(PhoneNumber)
        .where(PhoneNumber.phone_number == phone_number)
        .options(selectinload(PhoneNumber.reports))
    )
    return result.scalar_one_or_none()


async def get_or_create(db: AsyncSession, phone_number: str) -> PhoneNumber:
    """取得電話號碼紀錄；不存在時建立（初始為 safe，累積回報後升級）。"""
    phone = await get_by_number(db, phone_number)
    if phone is None:
        phone = PhoneNumber(phone_number=phone_number, risk_level="safe", report_count=0)
        db.add(phone)
        await db.flush()
    return phone


async def add_report(
    db: AsyncSession,
    *,
    phone_number: str,
    user_id: int,
    fraud_type: str,
    content: str,
    description: str | None,
) -> PhoneReport:
    """新增電話回報，並同步更新號碼主檔的統計與風險等級。"""
    phone = await get_or_create(db, phone_number)

    report = PhoneReport(
        phone_number_id=phone.id,
        user_id=user_id,
        fraud_type=fraud_type,
        content=content,
        description=description,
    )
    db.add(report)

    # 更新號碼主檔統計：舉報次數 +1、主要詐騙類型取最新、重算風險等級
    phone.report_count += 1
    phone.fraud_type = fraud_type
    phone.last_reported_at = utcnow()
    phone.risk_level = _compute_risk_level(phone.report_count)

    await db.commit()
    await db.refresh(report)
    return report


async def list_reports_by_user(
    db: AsyncSession, user_id: int
) -> list[tuple[PhoneReport, str]]:
    """查詢使用者的所有電話回報（附回報對象號碼）。"""
    result = await db.execute(
        select(PhoneReport, PhoneNumber.phone_number)
        .join(PhoneNumber, PhoneReport.phone_number_id == PhoneNumber.id)
        .where(PhoneReport.user_id == user_id)
        .order_by(PhoneReport.created_at.desc())
    )
    return [(row[0], row[1]) for row in result.all()]
