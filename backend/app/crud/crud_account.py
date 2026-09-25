"""可疑帳號（帳號威脅檔案）的 CRUD 操作。"""

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.base import utcnow
from app.models.account import SuspectAccount

# 風險評分規則（簡易啟發式，AI 引擎可再覆寫）：
# 首次回報基礎分 40，之後每筆回報 +10，上限 95
BASE_RISK_SCORE = 40
SCORE_PER_REPORT = 10
MAX_RISK_SCORE = 95
# 評分對應風險等級的門檻
HIGH_SCORE_THRESHOLD = 70


def _compute_risk(report_count: int) -> tuple[int, str]:
    """依回報次數計算（風險評分, 風險等級）。"""
    score = min(MAX_RISK_SCORE, BASE_RISK_SCORE + SCORE_PER_REPORT * max(0, report_count - 1))
    level = "high" if score >= HIGH_SCORE_THRESHOLD else "mid"
    return score, level


async def list_accounts(
    db: AsyncSession,
    *,
    platform: str | None = None,
    search: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[int, list[SuspectAccount]]:
    """查詢可疑帳號列表（支援平台篩選、名稱／ID 關鍵字搜尋、分頁）。"""
    query = select(SuspectAccount)
    if platform:
        query = query.where(SuspectAccount.platform == platform)
    if search:
        query = query.where(
            or_(
                SuspectAccount.account_name.contains(search),
                SuspectAccount.external_account_id.contains(search),
            )
        )

    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar_one()

    result = await db.execute(
        query.order_by(SuspectAccount.risk_score.desc(), SuspectAccount.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return total, list(result.scalars().all())


async def get_detail(db: AsyncSession, account_id: int) -> SuspectAccount | None:
    """取得帳號威脅檔案（預先載入證據摘要）。"""
    result = await db.execute(
        select(SuspectAccount)
        .where(SuspectAccount.id == account_id)
        .options(selectinload(SuspectAccount.evidence_items))
    )
    return result.scalar_one_or_none()


async def get_or_create(
    db: AsyncSession,
    *,
    platform: str,
    account_name: str,
    external_account_id: str | None,
) -> SuspectAccount:
    """尋找既有可疑帳號；優先以（平台, 外部 ID）比對，其次（平台, 名稱）。

    找不到時建立新紀錄（初始 report_count=0，套用回報時再更新統計）。
    """
    account: SuspectAccount | None = None

    if external_account_id:
        result = await db.execute(
            select(SuspectAccount).where(
                SuspectAccount.platform == platform,
                SuspectAccount.external_account_id == external_account_id,
            )
        )
        account = result.scalar_one_or_none()

    if account is None:
        result = await db.execute(
            select(SuspectAccount).where(
                SuspectAccount.platform == platform,
                SuspectAccount.account_name == account_name,
            )
        )
        account = result.scalar_one_or_none()

    if account is None:
        account = SuspectAccount(
            platform=platform,
            account_name=account_name,
            external_account_id=external_account_id,
            report_count=0,
            triggered_rules=[],
        )
        db.add(account)
        await db.flush()
    return account


async def apply_report(
    db: AsyncSession, account: SuspectAccount, fraud_type: str
) -> SuspectAccount:
    """套用一筆新回報至可疑帳號：更新統計、風險評分與觸發規則。

    注意：呼叫端負責 commit（與 fraud_reports 寫入同一交易）。
    """
    account.report_count += 1
    account.risk_score, account.risk_level = _compute_risk(account.report_count)
    account.last_reported_at = utcnow()

    # 將詐騙類型加入觸發規則標籤（去重；JSON 欄位需重新指派才會偵測變更）
    rule = f"社群回報：{fraud_type}"
    rules = list(account.triggered_rules or [])
    if rule not in rules:
        rules.append(rule)
        account.triggered_rules = rules

    return account
