"""建立初始資料表（9 張 Server 端資料表）

Revision ID: 0001
Revises:
Create Date: 2026-07-05

依 README 資料庫設計建立後端負責的資料表：
users、user_auth_providers、password_reset_tokens、user_settings、
phone_numbers、phone_reports、suspect_accounts、evidence_items、fraud_reports。
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Alembic 版本識別碼
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# MySQL 統一使用 utf8mb4（完整支援中文與 Emoji）
MYSQL_TABLE_ARGS = {
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}


def upgrade() -> None:
    """升級 schema：建立全部資料表。"""
    # ----- users：使用者主檔 -----
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("avatar_url", sa.String(length=500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("email_verified", sa.Boolean(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    # ----- user_auth_providers：社交登入綁定 -----
    op.create_table(
        "user_auth_providers",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("provider_user_id", sa.String(length=255), nullable=False),
        sa.Column("provider_email", sa.String(length=255), nullable=True),
        sa.Column("connected_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_user_auth_providers_user_id_users"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_auth_providers")),
        sa.UniqueConstraint("provider", "provider_user_id", name="uq_provider_account"),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index(
        op.f("ix_user_auth_providers_user_id"), "user_auth_providers", ["user_id"]
    )

    # ----- password_reset_tokens：忘記密碼 OTP -----
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("otp_hash", sa.String(length=64), nullable=False),
        sa.Column("reset_token", sa.String(length=128), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_password_reset_tokens_user_id_users"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_password_reset_tokens")),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index(
        op.f("ix_password_reset_tokens_user_id"), "password_reset_tokens", ["user_id"]
    )
    op.create_index(
        op.f("ix_password_reset_tokens_reset_token"),
        "password_reset_tokens",
        ["reset_token"],
    )

    # ----- user_settings：使用者設定開關 -----
    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("message_monitoring", sa.Boolean(), nullable=False),
        sa.Column("email_scanning", sa.Boolean(), nullable=False),
        sa.Column("call_detection", sa.Boolean(), nullable=False),
        sa.Column("quick_login", sa.Boolean(), nullable=False),
        sa.Column("high_risk_alert", sa.Boolean(), nullable=False),
        sa.Column("daily_report", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_user_settings_user_id_users"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_settings")),
        **MYSQL_TABLE_ARGS,
    )

    # ----- phone_numbers：詐騙電話號碼主檔 -----
    op.create_table(
        "phone_numbers",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("phone_number", sa.String(length=30), nullable=False),
        sa.Column("risk_level", sa.String(length=10), nullable=False),
        sa.Column("fraud_type", sa.String(length=50), nullable=True),
        sa.Column("report_count", sa.Integer(), nullable=False),
        sa.Column("last_reported_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_phone_numbers")),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index(
        op.f("ix_phone_numbers_phone_number"), "phone_numbers", ["phone_number"], unique=True
    )

    # ----- phone_reports：電話社群回報 -----
    op.create_table(
        "phone_reports",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("phone_number_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("fraud_type", sa.String(length=50), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["phone_number_id"], ["phone_numbers.id"],
            name=op.f("fk_phone_reports_phone_number_id_phone_numbers"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_phone_reports_user_id_users"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_phone_reports")),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index(op.f("ix_phone_reports_phone_number_id"), "phone_reports", ["phone_number_id"])
    op.create_index(op.f("ix_phone_reports_user_id"), "phone_reports", ["user_id"])
    op.create_index(op.f("ix_phone_reports_created_at"), "phone_reports", ["created_at"])

    # ----- suspect_accounts：可疑帳號主檔 -----
    op.create_table(
        "suspect_accounts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("account_name", sa.String(length=100), nullable=False),
        sa.Column("external_account_id", sa.String(length=100), nullable=True),
        sa.Column("risk_score", sa.Integer(), nullable=False),
        sa.Column("risk_level", sa.String(length=10), nullable=False),
        sa.Column("report_count", sa.Integer(), nullable=False),
        sa.Column("triggered_rules", sa.JSON(), nullable=False),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        sa.Column("last_reported_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_suspect_accounts")),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index(
        "ix_suspect_accounts_platform_name", "suspect_accounts", ["platform", "account_name"]
    )
    op.create_index(
        "ix_suspect_accounts_platform_ext",
        "suspect_accounts",
        ["platform", "external_account_id"],
    )

    # ----- evidence_items：證據摘要 -----
    op.create_table(
        "evidence_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("suspect_account_id", sa.BigInteger(), nullable=False),
        sa.Column("evidence_type", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["suspect_account_id"], ["suspect_accounts.id"],
            name=op.f("fk_evidence_items_suspect_account_id_suspect_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence_items")),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index(
        op.f("ix_evidence_items_suspect_account_id"), "evidence_items", ["suspect_account_id"]
    )

    # ----- fraud_reports：帳號回報 + 完整回報 -----
    op.create_table(
        "fraud_reports",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("case_number", sa.String(length=30), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("report_type", sa.String(length=10), nullable=False),
        sa.Column("fraud_type", sa.String(length=50), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("platform", sa.String(length=20), nullable=True),
        sa.Column("account_name", sa.String(length=100), nullable=True),
        sa.Column("external_account_id", sa.String(length=100), nullable=True),
        sa.Column("suspect_account_id", sa.BigInteger(), nullable=True),
        sa.Column("evidence_files", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_fraud_reports_user_id_users"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["suspect_account_id"], ["suspect_accounts.id"],
            name=op.f("fk_fraud_reports_suspect_account_id_suspect_accounts"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fraud_reports")),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index(op.f("ix_fraud_reports_case_number"), "fraud_reports", ["case_number"], unique=True)
    op.create_index(op.f("ix_fraud_reports_user_id"), "fraud_reports", ["user_id"])
    op.create_index(op.f("ix_fraud_reports_created_at"), "fraud_reports", ["created_at"])


def downgrade() -> None:
    """降級 schema：依外鍵相依順序反向刪除資料表。"""
    op.drop_table("fraud_reports")
    op.drop_table("evidence_items")
    op.drop_table("suspect_accounts")
    op.drop_table("phone_reports")
    op.drop_table("phone_numbers")
    op.drop_table("user_settings")
    op.drop_table("password_reset_tokens")
    op.drop_table("user_auth_providers")
    op.drop_table("users")
