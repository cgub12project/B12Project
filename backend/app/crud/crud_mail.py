"""信箱連接（mail_accounts）與信件判定（mail_analysis）的 CRUD 操作。"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.models.mail import MailAccount, MailAnalysis, MailBlockedSender

# last_sync_error 欄位長度上限（超過即截斷，避免長錯誤訊息寫入失敗）
SYNC_ERROR_MAX_CHARS = 500


# ============================================================
# mail_accounts
# ============================================================

async def get_account(
    db: AsyncSession, account_id: int, user_id: int
) -> MailAccount | None:
    """取得使用者自己的信箱連接（他人的一律視為不存在）。"""
    result = await db.execute(
        select(MailAccount).where(
            MailAccount.id == account_id, MailAccount.user_id == user_id
        )
    )
    return result.scalar_one_or_none()


async def list_accounts(
    db: AsyncSession, user_id: int, *, active_only: bool = False
) -> list[MailAccount]:
    """列出某使用者已連接的信箱。"""
    query = select(MailAccount).where(MailAccount.user_id == user_id)
    if active_only:
        query = query.where(MailAccount.is_active.is_(True))
    result = await db.execute(query.order_by(MailAccount.connected_at))
    return list(result.scalars().all())


async def list_all_active_accounts(db: AsyncSession) -> list[MailAccount]:
    """列出全系統仍在生效的信箱連接（排程輪詢用）。"""
    result = await db.execute(
        select(MailAccount)
        .where(MailAccount.is_active.is_(True))
        .order_by(MailAccount.id)
    )
    return list(result.scalars().all())


async def upsert_account(
    db: AsyncSession,
    *,
    user_id: int,
    provider: str,
    email_address: str,
    refresh_token_encrypted: str,
) -> MailAccount:
    """建立或更新信箱連接。

    重新授權同一個信箱時視為更新既有紀錄（換上新的 refresh_token 並重新啟用），
    不會產生第二筆——否則排程會對同一個信箱重複抓信。

    ⚠ 重新授權會把 `last_synced_at` 歸零，當成全新連接處理。使用者會來重新連接，
    通常正是因為這個信箱已經斷線一段時間了；沿用斷線前的舊游標，等於宣告
    「斷線期間的信一封都不用補」，而使用者的期待剛好相反——重新連接後應該
    馬上看得到近期的信。歸零後首次同步會改用 MAIL_SYNC_INITIAL_LOOKBACK_HOURS
    的回溯視窗，重複的部分由 provider_message_id 去重擋掉。
    """
    result = await db.execute(
        select(MailAccount).where(
            MailAccount.user_id == user_id,
            MailAccount.provider == provider,
            MailAccount.email_address == email_address,
        )
    )
    account = result.scalar_one_or_none()

    if account is None:
        account = MailAccount(
            user_id=user_id,
            provider=provider,
            email_address=email_address,
            refresh_token_encrypted=refresh_token_encrypted,
        )
        db.add(account)
    else:
        account.refresh_token_encrypted = refresh_token_encrypted
        account.is_active = True
        account.connected_at = utcnow()
        account.last_synced_at = None
        account.last_sync_error = None

    await db.commit()
    await db.refresh(account)
    return account


async def update_refresh_token(
    db: AsyncSession, account: MailAccount, refresh_token_encrypted: str
) -> None:
    """更新加密後的 refresh_token（Microsoft 刷新時會輪替權杖）。"""
    account.refresh_token_encrypted = refresh_token_encrypted
    await db.commit()


async def mark_sync_success(
    db: AsyncSession, account: MailAccount, synced_at: datetime
) -> None:
    """標記同步成功：更新增量抓取的起點並清除錯誤訊息。"""
    account.last_synced_at = synced_at
    account.last_sync_error = None
    await db.commit()


async def mark_sync_error(
    db: AsyncSession, account: MailAccount, message: str, *, deactivate: bool = False
) -> None:
    """記錄同步失敗原因。

    `deactivate=True` 用於授權已被撤銷等不可自行恢復的情況：停用後排程不再重試，
    App 端看到 last_sync_error 後可提示使用者重新連接。
    """
    account.last_sync_error = message[:SYNC_ERROR_MAX_CHARS]
    if deactivate:
        account.is_active = False
    await db.commit()


async def delete_account(db: AsyncSession, account: MailAccount) -> int:
    """刪除信箱連接，並回傳一併刪除的判定紀錄筆數。

    使用者主動中斷連接時，加密的 refresh_token 與所有判定紀錄一起消失
    （mail_analysis 以 ON DELETE CASCADE 連動）。
    """
    count = await db.scalar(
        select(func.count())
        .select_from(MailAnalysis)
        .where(MailAnalysis.mail_account_id == account.id)
    )
    await db.delete(account)
    await db.commit()
    return int(count or 0)


# ============================================================
# mail_analysis
# ============================================================

async def existing_message_ids(
    db: AsyncSession, account_id: int, message_ids: list[str]
) -> set[str]:
    """回傳這批信件 ID 中「已分析過」的部分（輪詢去重用）。"""
    if not message_ids:
        return set()
    result = await db.execute(
        select(MailAnalysis.provider_message_id).where(
            MailAnalysis.mail_account_id == account_id,
            MailAnalysis.provider_message_id.in_(message_ids),
        )
    )
    return set(result.scalars().all())


async def create_analysis(
    db: AsyncSession,
    *,
    user_id: int,
    mail_account_id: int,
    provider: str,
    provider_message_id: str,
    received_at: datetime,
    is_scam: bool,
    risk_level: str,
    scam_type: str | None,
    confidence: float,
    reasons: list[str],
    advice: str | None,
    model: str,
) -> MailAnalysis:
    """寫入一封信的判定結果（不含信件內容）。"""
    analysis = MailAnalysis(
        user_id=user_id,
        mail_account_id=mail_account_id,
        provider=provider,
        provider_message_id=provider_message_id,
        received_at=received_at,
        is_scam=is_scam,
        risk_level=risk_level,
        scam_type=scam_type,
        confidence=confidence,
        reasons=reasons,
        advice=advice,
        model=model,
    )
    db.add(analysis)
    await db.commit()
    await db.refresh(analysis)
    return analysis


async def get_analysis(
    db: AsyncSession, analysis_id: int, user_id: int
) -> MailAnalysis | None:
    """取得使用者自己的單筆判定紀錄（他人的一律視為不存在）。"""
    result = await db.execute(
        select(MailAnalysis).where(
            MailAnalysis.id == analysis_id, MailAnalysis.user_id == user_id
        )
    )
    return result.scalar_one_or_none()


async def list_analyses(
    db: AsyncSession,
    user_id: int,
    *,
    risk_level: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[int, list[MailAnalysis]]:
    """查詢某使用者的信件判定結果（依收信時間新到舊，含總筆數）。"""
    conditions = [MailAnalysis.user_id == user_id]
    if risk_level is not None:
        conditions.append(MailAnalysis.risk_level == risk_level)

    total = await db.scalar(
        select(func.count()).select_from(MailAnalysis).where(*conditions)
    )
    result = await db.execute(
        select(MailAnalysis)
        .where(*conditions)
        .order_by(MailAnalysis.received_at.desc(), MailAnalysis.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return int(total or 0), list(result.scalars().all())


# ============================================================
# mail_blocked_senders
# ============================================================

async def list_blocked_senders(
    db: AsyncSession, account_id: int
) -> list[MailBlockedSender]:
    """列出某信箱已封鎖的寄件人（新到舊）。"""
    result = await db.execute(
        select(MailBlockedSender)
        .where(MailBlockedSender.mail_account_id == account_id)
        .order_by(MailBlockedSender.created_at.desc(), MailBlockedSender.id.desc())
    )
    return list(result.scalars().all())


async def blocked_sender_addresses(db: AsyncSession, account_id: int) -> set[str]:
    """回傳某信箱已封鎖的寄件位址集合（同步時比對用）。"""
    result = await db.execute(
        select(MailBlockedSender.sender_address).where(
            MailBlockedSender.mail_account_id == account_id
        )
    )
    return set(result.scalars().all())


async def get_blocked_sender(
    db: AsyncSession, account_id: int, sender_address: str
) -> MailBlockedSender | None:
    """取得某信箱對某寄件人的封鎖紀錄。"""
    result = await db.execute(
        select(MailBlockedSender).where(
            MailBlockedSender.mail_account_id == account_id,
            MailBlockedSender.sender_address == sender_address,
        )
    )
    return result.scalar_one_or_none()


async def upsert_blocked_sender(
    db: AsyncSession,
    *,
    account_id: int,
    sender_address: str,
    provider_filter_id: str | None,
) -> MailBlockedSender:
    """新增或更新一筆封鎖紀錄。

    重複封鎖同一個寄件人時更新既有紀錄的 provider_filter_id：提供者端會多出
    一條規則，我們只留得住最後一條的 ID，因此呼叫端應先檢查是否已封鎖過
    （端點就是這麼做的），這裡的 upsert 是防競態的最後一道。
    """
    blocked = await get_blocked_sender(db, account_id, sender_address)
    if blocked is None:
        blocked = MailBlockedSender(
            mail_account_id=account_id,
            sender_address=sender_address,
            provider_filter_id=provider_filter_id,
        )
        db.add(blocked)
    else:
        blocked.provider_filter_id = provider_filter_id

    await db.commit()
    await db.refresh(blocked)
    return blocked


async def delete_blocked_sender(db: AsyncSession, blocked: MailBlockedSender) -> None:
    """刪除一筆封鎖紀錄（提供者端的規則由呼叫端負責先刪）。"""
    await db.delete(blocked)
    await db.commit()
