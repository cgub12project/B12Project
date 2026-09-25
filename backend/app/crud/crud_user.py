"""使用者與使用者設定的 CRUD 操作。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.base import utcnow
from app.models.user import User, UserSetting


async def get_by_id(db: AsyncSession, user_id: int) -> User | None:
    """依 ID 取得使用者。"""
    return await db.get(User, user_id)


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    """依 Email 取得使用者（Email 統一轉小寫比對）。"""
    result = await db.execute(select(User).where(User.email == email.lower()))
    return result.scalar_one_or_none()


async def create(
    db: AsyncSession,
    *,
    email: str,
    name: str,
    password: str | None = None,
    email_verified: bool = False,
    avatar_url: str | None = None,
) -> User:
    """建立使用者（password 為 None 表示純社交登入帳號），並同時建立預設設定。"""
    user = User(
        email=email.lower(),
        name=name,
        password_hash=hash_password(password) if password else None,
        email_verified=email_verified,
        avatar_url=avatar_url,
    )
    db.add(user)
    await db.flush()  # 先 flush 取得 user.id

    # 建立預設設定（一對一）
    db.add(UserSetting(user_id=user.id))
    await db.commit()
    await db.refresh(user)
    return user


async def update_profile(
    db: AsyncSession, user: User, *, name: str | None = None, avatar_url: str | None = None
) -> User:
    """更新個人資料（僅名稱與頭像）。"""
    if name is not None:
        user.name = name
    if avatar_url is not None:
        user.avatar_url = avatar_url
    await db.commit()
    await db.refresh(user)
    return user


async def update_password(db: AsyncSession, user: User, new_password: str) -> None:
    """更新使用者密碼（重新雜湊後儲存）。"""
    user.password_hash = hash_password(new_password)
    await db.commit()


async def touch_last_login(db: AsyncSession, user: User) -> None:
    """更新最後登入時間。"""
    user.last_login_at = utcnow()
    await db.commit()


# ============================================================
# 使用者設定
# ============================================================

async def get_or_create_settings(db: AsyncSession, user_id: int) -> UserSetting:
    """取得使用者設定；不存在時自動建立預設值（容錯舊資料）。"""
    setting = await db.get(UserSetting, user_id)
    if setting is None:
        setting = UserSetting(user_id=user_id)
        db.add(setting)
        await db.commit()
        await db.refresh(setting)
    return setting


async def update_settings(
    db: AsyncSession, user_id: int, changes: dict[str, bool]
) -> UserSetting:
    """更新使用者設定（僅套用有傳值的欄位）。"""
    setting = await get_or_create_settings(db, user_id)
    for field, value in changes.items():
        setattr(setting, field, value)
    await db.commit()
    await db.refresh(setting)
    return setting
