"""建立寄件人封鎖資料表（mail_blocked_senders）

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-12

配合郵件「真封鎖」功能：實際擋信的是提供者端的過濾規則
（Gmail Filters API），這張表記錄「誰在哪個信箱封鎖了誰」與對應的規則 ID，
供解除封鎖時刪規則、以及規則生效前的同步先行跳過。
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Alembic 版本識別碼
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# MySQL 統一使用 utf8mb4（完整支援中文與 Emoji）
MYSQL_TABLE_ARGS = {
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}


def upgrade() -> None:
    """升級 schema：建立寄件人封鎖資料表。"""
    op.create_table(
        "mail_blocked_senders",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("mail_account_id", sa.BigInteger(), nullable=False),
        sa.Column("sender_address", sa.String(length=255), nullable=False),
        sa.Column("provider_filter_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["mail_account_id"], ["mail_accounts.id"],
            name=op.f("fk_mail_blocked_senders_mail_account_id_mail_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mail_blocked_senders")),
        sa.UniqueConstraint(
            "mail_account_id", "sender_address", name="uq_mail_blocked_sender"
        ),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index(
        op.f("ix_mail_blocked_senders_mail_account_id"),
        "mail_blocked_senders",
        ["mail_account_id"],
    )


def downgrade() -> None:
    """降級 schema：移除寄件人封鎖資料表。"""
    op.drop_table("mail_blocked_senders")
