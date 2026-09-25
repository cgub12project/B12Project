"""測試共用 fixture。

以 SQLite（aiosqlite）記憶體資料庫取代 MySQL，
覆寫 get_db 相依性後透過 httpx ASGITransport 直接呼叫 FastAPI app，
測試不需要啟動伺服器或安裝 MySQL。
"""

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  # 註冊所有模型至 Base.metadata
from app.db.base import Base
from app.db.session import get_db
from app.main import app

# 記憶體 SQLite：StaticPool 讓所有連線共用同一個記憶體資料庫
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def db_engine():
    """建立測試用資料庫引擎，並在測試前後建立／清除資料表。"""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def client(db_engine) -> AsyncGenerator[AsyncClient, None]:
    """提供已覆寫資料庫相依性的測試 HTTP 客戶端。"""
    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    """註冊一個測試帳號並回傳其 Bearer 認證標頭。"""
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "tester@example.com",
            "password": "Passw0rd123",
            "name": "測試使用者",
        },
    )
    assert response.status_code == 201, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
