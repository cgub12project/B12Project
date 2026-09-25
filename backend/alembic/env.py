"""Alembic 遷移環境（非同步版本）。

連線字串自 app.core.config（.env 的 DATABASE_URL）動態注入，
目標 metadata 為 app.db.base.Base（已匯入全部模型）。
"""

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# 直接執行 alembic.exe 時，CWD 不會自動加入 sys.path，
# 這裡明確把專案根目錄（alembic/ 的上一層）加入，確保 `import app` 成功
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app.models  # noqa: E402, F401  # 匯入所有模型，註冊至 Base.metadata
from app.core.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402

# Alembic Config 物件（讀取 alembic.ini）
config = context.config

# 以 .env 的 DATABASE_URL 覆寫 alembic.ini 的佔位符
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# 設定日誌
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# autogenerate 的比對目標
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """離線模式：不建立連線，直接輸出 SQL 腳本。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """在給定連線上執行遷移（由非同步引擎透過 run_sync 呼叫）。"""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """建立非同步引擎並執行遷移。"""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """線上模式：以非同步引擎連線資料庫執行遷移。"""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
