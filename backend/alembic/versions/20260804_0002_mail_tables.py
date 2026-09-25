"""建立信箱連接資料表（mail_accounts、mail_analysis）

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-04

配合 Gmail API／Microsoft Graph 完整信件讀取功能：
- mail_accounts：已連接的信箱帳號，refresh_token 加密後儲存
- mail_analysis：每封信的 AI 判定結果（刻意不含主旨／寄件者／內文）
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Alembic 版本識別碼
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# MySQL 統一使用 utf8mb4（完整支援中文與 Emoji）
MYSQL_TABLE_ARGS = {
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}


def upgrade() -> None:
    """升級 schema：建立信箱連接與信件判定資料表。"""
    # ----- mail_accounts：已連接的信箱帳號 -----
    op.create_table(
        "mail_accounts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(length=10), nullable=False),
        sa.Column("email_address", sa.String(length=255), nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("connected_at", sa.DateTime(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("last_sync_error", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_mail_accounts_user_id_users"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mail_accounts")),
        sa.UniqueConstraint(
            "user_id", "provider", "email_address", name="uq_mail_accounts_identity"
        ),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index(op.f("ix_mail_accounts_user_id"), "mail_accounts", ["user_id"])

    # ----- mail_analysis：信件 AI 判定結果（不存信件內容）-----
    op.create_table(
        "mail_analysis",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("mail_account_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(length=10), nullable=False),
        sa.Column("provider_message_id", sa.String(length=255), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("is_scam", sa.Boolean(), nullable=False),
        sa.Column("risk_level", sa.String(length=10), nullable=False),
        sa.Column("scam_type", sa.String(length=50), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("advice", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=50), nullable=False),
        sa.Column("analyzed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_mail_analysis_user_id_users"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["mail_account_id"], ["mail_accounts.id"],
            name=op.f("fk_mail_analysis_mail_account_id_mail_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mail_analysis")),
        sa.UniqueConstraint(
            "mail_account_id", "provider_message_id", name="uq_mail_analysis_message"
        ),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index(op.f("ix_mail_analysis_user_id"), "mail_analysis", ["user_id"])
    op.create_index(
        op.f("ix_mail_analysis_mail_account_id"), "mail_analysis", ["mail_account_id"]
    )
    op.create_index(op.f("ix_mail_analysis_received_at"), "mail_analysis", ["received_at"])
    op.create_index(
        "ix_mail_analysis_user_received", "mail_analysis", ["user_id", "received_at"]
    )


def downgrade() -> None:
    """降級 schema：依外鍵相依順序反向刪除資料表。"""
    op.drop_table("mail_analysis")
    op.drop_table("mail_accounts")
