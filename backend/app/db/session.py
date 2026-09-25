"""非同步資料庫連線與 Session 管理。

使用 SQLAlchemy 2.0 async engine 搭配 aiomysql 驅動連線 MySQL。
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

# 非同步 Engine（連線池由 SQLAlchemy 管理）
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DB_ECHO,
    pool_pre_ping=True,  # 取用連線前先 ping，避免 MySQL 連線逾時斷線
    pool_recycle=3600,  # 每小時回收連線，低於 MySQL wait_timeout
)

# Session 工廠：expire_on_commit=False 讓 commit 後仍可讀取物件屬性
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 相依性：提供資料庫 Session，請求結束後自動關閉。

    發生例外時自動 rollback，確保連線回到乾淨狀態。
    """
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
