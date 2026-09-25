"""ORM 基底類別與共用工具。

- `Base`：所有 ORM 模型的宣告式基底類別（含索引／約束命名慣例）。
- `BigIntPK`：跨資料庫相容的大整數主鍵型別（MySQL 用 BIGINT，
  SQLite 測試環境退回 INTEGER 以支援自動遞增）。
- `utcnow`：統一以 UTC（naive）儲存時間戳記。
"""

from datetime import datetime, timezone

from sqlalchemy import BigInteger, Integer, MetaData
from sqlalchemy.orm import DeclarativeBase

# 命名慣例：讓 alembic autogenerate 產生穩定的約束名稱
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# 大整數主鍵：MySQL 使用 BIGINT；SQLite（單元測試）需退回 INTEGER 才能自動遞增
BigIntPK = BigInteger().with_variant(Integer(), "sqlite")


def utcnow() -> datetime:
    """回傳目前 UTC 時間（naive datetime，統一儲存格式）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    """所有 ORM 模型的基底類別。"""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
