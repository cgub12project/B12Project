"""認證流程的 CRUD 操作：OTP 密碼重設、社交登入綁定。"""

from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    generate_otp,
    generate_reset_token,
    hash_otp,
    verify_otp_hash,
)
from app.db.base import utcnow
from app.models.user import PasswordResetToken, User, UserAuthProvider


# ============================================================
# 忘記密碼（OTP → reset_token）
# ============================================================

async def create_reset_otp(db: AsyncSession, user: User) -> str:
    """為使用者建立新的 OTP，並使既有未完成的 OTP 全部失效。

    Returns:
        明文 OTP（僅用於寄送 Email，資料庫只存雜湊）。
    """
    # 將既有未使用的 OTP 標記為已使用（同一時間僅允許一組有效 OTP）
    await db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used.is_(False),
        )
        .values(used=True)
    )

    otp = generate_otp()
    token = PasswordResetToken(
        user_id=user.id,
        otp_hash=hash_otp(otp),
        expires_at=utcnow() + timedelta(minutes=settings.OTP_EXPIRE_MINUTES),
    )
    db.add(token)
    await db.commit()
    return otp


async def verify_otp(db: AsyncSession, user: User, otp: str) -> str | None:
    """驗證 OTP；成功則核發一次性 reset_token。

    驗證失敗會累計嘗試次數，超過上限（OTP_MAX_ATTEMPTS）即永久失效。

    Returns:
        reset_token（成功）或 None（失敗）。
    """
    result = await db.execute(
        select(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used.is_(False),
            PasswordResetToken.verified.is_(False),
        )
        .order_by(PasswordResetToken.id.desc())
        .limit(1)
    )
    token = result.scalar_one_or_none()

    # 無有效 OTP、已過期、或嘗試次數超過上限
    if (
        token is None
        or token.expires_at < utcnow()
        or token.attempts >= settings.OTP_MAX_ATTEMPTS
    ):
        return None

    if not verify_otp_hash(otp, token.otp_hash):
        # OTP 錯誤：累計嘗試次數
        token.attempts += 1
        await db.commit()
        return None

    # OTP 正確：核發 reset_token，效期重新起算（RESET_TOKEN_EXPIRE_MINUTES）
    reset_token = generate_reset_token()
    token.verified = True
    token.reset_token = reset_token
    token.expires_at = utcnow() + timedelta(minutes=settings.RESET_TOKEN_EXPIRE_MINUTES)
    await db.commit()
    return reset_token


async def consume_reset_token(db: AsyncSession, reset_token: str) -> User | None:
    """驗證並消耗 reset_token（一次性使用）。

    Returns:
        對應的使用者（成功）或 None（權杖無效／過期）。
    """
    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.reset_token == reset_token,
            PasswordResetToken.verified.is_(True),
            PasswordResetToken.used.is_(False),
        )
    )
    token = result.scalar_one_or_none()
    if token is None or token.expires_at < utcnow():
        return None

    user = await db.get(User, token.user_id)
    if user is None:
        return None

    # 標記為已使用，確保一次性
    token.used = True
    await db.commit()
    return user


# ============================================================
# 社交登入綁定
# ============================================================

async def get_provider_link(
    db: AsyncSession, provider: str, provider_user_id: str
) -> UserAuthProvider | None:
    """依（提供者, 提供者端使用者 ID）查詢既有綁定。"""
    result = await db.execute(
        select(UserAuthProvider).where(
            UserAuthProvider.provider == provider,
            UserAuthProvider.provider_user_id == provider_user_id,
        )
    )
    return result.scalar_one_or_none()


async def link_provider(
    db: AsyncSession,
    *,
    user_id: int,
    provider: str,
    provider_user_id: str,
    provider_email: str | None,
) -> UserAuthProvider:
    """建立社交登入綁定紀錄。"""
    link = UserAuthProvider(
        user_id=user_id,
        provider=provider,
        provider_user_id=provider_user_id,
        provider_email=provider_email,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return link
