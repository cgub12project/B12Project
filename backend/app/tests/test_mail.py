"""信箱連接功能測試（OAuth 流程、輪詢同步、判定結果讀取）。

外部相依（Google／Microsoft API、本地 LLM）一律以假物件替換，
測試不需要真的信箱帳號、網路或 GPU。
"""

import base64
from datetime import datetime, timedelta

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.security import create_mail_oauth_state
from app.crud import crud_mail
from app.db.base import utcnow
from app.main import app
from app.models.mail import MailAccount, MailAnalysis
from app.models.user import User
from app.schemas.rag import RagDetectResponse
from app.services import mail_oauth, mail_provider, mail_sync
from app.services.mail_oauth import MailAuthRevokedError, MailOAuthError, OAuthTokens
from app.services.mail_provider import MailContent
from app.services.rag_service import get_rag_service


@pytest.fixture
async def db_session(db_engine):
    """與測試 HTTP 客戶端共用同一個記憶體資料庫的 Session。"""
    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


async def _get_user(db_session) -> User:
    """取得 auth_headers fixture 註冊的測試使用者。"""
    result = await db_session.execute(
        select(User).where(User.email == "tester@example.com")
    )
    return result.scalar_one()


async def _connect_account(
    db_session, *, refresh_token: str, email_address: str = "victim@example.com"
) -> MailAccount:
    """替 auth_headers 的測試使用者建一個已連接、仍生效中的 Gmail 信箱。"""
    user = await _get_user(db_session)
    return await _account_for(
        db_session, user, refresh_token=refresh_token, email_address=email_address
    )


async def _service_account(
    db_session, *, refresh_token: str, email_address: str
) -> MailAccount:
    """建一組獨立的使用者 + 已連接信箱。

    給不經過 HTTP 的服務層測試用（那些測試沒有 auth_headers fixture，
    也就沒有 tester@example.com 這個使用者）。
    """
    user = User(email=email_address, name="同步測試", password_hash=None)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return await _account_for(
        db_session, user, refresh_token=refresh_token, email_address=email_address
    )


async def _account_for(
    db_session, user: User, *, refresh_token: str, email_address: str
) -> MailAccount:
    account = MailAccount(
        user_id=user.id,
        provider="gmail",
        email_address=email_address,
        refresh_token_encrypted=encrypt_secret(refresh_token),
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)
    return account


class FakeRagService:
    """假的偵測服務：記錄收到的文字，固定回傳高風險判定。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def detect(self, message: str) -> RagDetectResponse:
        self.calls.append(message)
        return RagDetectResponse(
            is_scam=True,
            risk_level="high",
            scam_type="釣魚郵件",
            confidence=0.92,
            reasons=["要求點擊連結並輸入帳號密碼"],
            advice="請勿點擊信中連結，可撥打 165 查證。",
            similar_cases=[],
            model="fake-model",
        )


# ============================================================
# 資料落地原則（決策 2）
# ============================================================

def test_mail_analysis_stores_no_message_content() -> None:
    """mail_analysis 不得出現任何存放信件內容的欄位。

    這是決策 2 的核心約束：資料庫是全組都連得進去的 phpMyAdmin，
    信件內容一旦落地就人人看得到。日後若有人「順手」加上 subject/body
    欄位方便顯示，這個測試會擋下來。
    """
    columns = set(MailAnalysis.__table__.columns.keys())
    forbidden = {
        "subject",
        "sender",
        "from_address",
        "body",
        "content",
        "html",
        "snippet",
        "preview",
        "recipients",
    }
    assert not (columns & forbidden), f"mail_analysis 不應儲存信件內容：{columns & forbidden}"


def test_refresh_token_encryption_roundtrip() -> None:
    """refresh_token 加密後不得看得出原文，且能正確還原。"""
    secret = "1//0gFAKErefreshTOKENvalue"
    encrypted = encrypt_secret(secret)
    assert secret not in encrypted
    assert decrypt_secret(encrypted) == secret


# ============================================================
# OAuth 授權
# ============================================================

async def test_connect_returns_503_when_provider_not_configured(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    """未設定 client_id／secret 時，連接端點要明確回報未設定。"""
    monkeypatch.setattr(settings, "GMAIL_CLIENT_ID", "")
    monkeypatch.setattr(settings, "GMAIL_CLIENT_SECRET", "")

    response = await client.get("/api/v1/mail/connect/gmail", headers=auth_headers)
    assert response.status_code == 503
    assert "GMAIL_CLIENT_ID" in response.json()["detail"]


async def test_connect_builds_authorize_url(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    """授權網址須帶 offline + consent，否則 Google 不會發 refresh_token。"""
    monkeypatch.setattr(settings, "GMAIL_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(settings, "GMAIL_CLIENT_SECRET", "test-secret")

    response = await client.get("/api/v1/mail/connect/gmail", headers=auth_headers)
    assert response.status_code == 200, response.text

    url = response.json()["authorize_url"]
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=test-client-id" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "gmail.readonly" in url
    # 「真封鎖」要建 Gmail 過濾規則，少了這個 scope 封鎖端點只會拿到 403
    assert "gmail.settings.basic" in url
    assert "state=" in url


async def test_connect_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/mail/connect/gmail")
    assert response.status_code == 401


async def test_callback_rejects_invalid_state(client: AsyncClient) -> None:
    """state 驗不過就不能建立任何連接（防止他人把信箱掛到別的帳號下）。"""
    response = await client.get(
        "/api/v1/mail/callback/gmail", params={"code": "abc", "state": "not-a-jwt"}
    )
    assert response.status_code == 400
    assert "重新點一次連接" in response.text


async def test_callback_reports_user_denial(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/mail/callback/gmail", params={"error": "access_denied"}
    )
    assert response.status_code == 400
    assert "取消" in response.text


async def test_callback_stores_encrypted_refresh_token(
    client: AsyncClient, auth_headers: dict[str, str], db_session, monkeypatch
) -> None:
    """授權成功後建立連接，且 refresh_token 以密文落地。

    MAIL_OAUTH_SUCCESS_REDIRECT 要在測試裡釘成空字串：開發機的 .env 通常填了
    App 的深層連結，端點會改回 302，這個測試就會因為「別人的 .env」而紅。
    """
    monkeypatch.setattr(settings, "MAIL_OAUTH_SUCCESS_REDIRECT", "", raising=False)
    user = await _get_user(db_session)

    async def fake_exchange_code(provider: str, code: str) -> OAuthTokens:
        assert (provider, code) == ("gmail", "auth-code-123")
        return OAuthTokens(
            access_token="access-1", refresh_token="refresh-secret-1", expires_in=3600
        )

    async def fake_fetch_account_email(provider: str, access_token: str) -> str:
        return "victim@example.com"

    monkeypatch.setattr("app.api.endpoints.mail.exchange_code", fake_exchange_code)
    monkeypatch.setattr(
        "app.api.endpoints.mail.fetch_account_email", fake_fetch_account_email
    )

    state = create_mail_oauth_state(user.id, "gmail")
    response = await client.get(
        "/api/v1/mail/callback/gmail", params={"code": "auth-code-123", "state": state}
    )
    assert response.status_code == 200, response.text
    assert "victim@example.com" in response.text

    account = (
        await db_session.execute(select(MailAccount).where(MailAccount.user_id == user.id))
    ).scalar_one()
    assert account.provider == "gmail"
    assert account.email_address == "victim@example.com"
    # 明文不得出現在資料庫欄位裡
    assert "refresh-secret-1" not in account.refresh_token_encrypted
    assert decrypt_secret(account.refresh_token_encrypted) == "refresh-secret-1"

    # 列表端點看得到這個連接
    listed = await client.get("/api/v1/mail/accounts", headers=auth_headers)
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 1
    assert body["items"][0]["email_address"] == "victim@example.com"
    assert body["items"][0]["last_synced_at"] is None


async def test_disconnect_removes_account_and_analyses(
    client: AsyncClient, auth_headers: dict[str, str], db_session
) -> None:
    """中斷連接要一併刪掉判定紀錄與加密權杖。"""
    user = await _get_user(db_session)
    account = MailAccount(
        user_id=user.id,
        provider="gmail",
        email_address="victim@example.com",
        refresh_token_encrypted=encrypt_secret("refresh-secret-1"),
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)

    db_session.add(
        MailAnalysis(
            user_id=user.id,
            mail_account_id=account.id,
            provider="gmail",
            provider_message_id="msg-1",
            received_at=utcnow(),
            is_scam=True,
            risk_level="high",
            scam_type="釣魚郵件",
            confidence=0.9,
            reasons=["測試"],
            advice=None,
            model="fake-model",
        )
    )
    await db_session.commit()

    response = await client.delete(
        f"/api/v1/mail/accounts/{account.id}", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["deleted_analyses"] == 1

    remaining = (await db_session.execute(select(MailAccount))).scalars().all()
    assert remaining == []


async def test_disconnect_other_users_account_returns_404(
    client: AsyncClient, auth_headers: dict[str, str], db_session
) -> None:
    """別人的信箱連接一律視為不存在。"""
    other = User(email="other@example.com", name="別人", password_hash=None)
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)

    account = MailAccount(
        user_id=other.id,
        provider="gmail",
        email_address="other@example.com",
        refresh_token_encrypted=encrypt_secret("refresh-secret-2"),
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)

    response = await client.delete(
        f"/api/v1/mail/accounts/{account.id}", headers=auth_headers
    )
    assert response.status_code == 404


# ============================================================
# 同步（輪詢）
# ============================================================

def _fake_mail(
    message_id: str,
    *,
    subject: str,
    body: str,
    received_at: datetime | None = None,
) -> MailContent:
    return MailContent(
        message_id=message_id,
        subject=subject,
        sender="Bank Service <service@bank-secure.example>",
        preview=body[:50],
        received_at=received_at or utcnow(),
        body=body,
    )


async def test_sync_stores_verdict_and_dedupes(db_session, monkeypatch) -> None:
    """同步會逐封判定並存檔；第二次輪詢重複抓到同一批信要略過。"""
    user = User(email="sync@example.com", name="同步測試", password_hash=None)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    account = MailAccount(
        user_id=user.id,
        provider="gmail",
        email_address="sync@example.com",
        refresh_token_encrypted=encrypt_secret("refresh-secret-3"),
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)

    async def fake_get_access_token(db, acc) -> str:
        return "access-token"

    async def fake_list_message_ids(provider, access_token, *, since, limit):
        return ["msg-1", "msg-2"]

    # msg-1 比 msg-2 新：分析順序是新到舊，下面才能斷言存檔順序
    received = {
        "msg-1": datetime(2026, 8, 4, 12, 0, 0),
        "msg-2": datetime(2026, 8, 4, 11, 0, 0),
    }

    async def fake_fetch_message_content(provider, access_token, message_id):
        return _fake_mail(
            message_id,
            subject="您的帳戶已被鎖定",
            body="請立即點擊 http://bank-secure.example/login 驗證身分",
            received_at=received[message_id],
        )

    monkeypatch.setattr(mail_sync, "get_access_token", fake_get_access_token)
    monkeypatch.setattr(mail_sync, "list_message_ids", fake_list_message_ids)
    monkeypatch.setattr(mail_sync, "fetch_message_content", fake_fetch_message_content)

    rag = FakeRagService()
    results = await mail_sync.sync_user_accounts(db_session, user.id, rag)

    assert len(results) == 1
    assert (results[0].fetched, results[0].analyzed, results[0].skipped) == (2, 2, 0)
    assert results[0].error is None
    assert len(rag.calls) == 2
    # 寄件者與主旨要一起送進判斷（詐騙信的破綻常在這兩處）
    assert "service@bank-secure.example" in rag.calls[0]
    assert "您的帳戶已被鎖定" in rag.calls[0]

    stored = (
        (await db_session.execute(select(MailAnalysis).order_by(MailAnalysis.id)))
        .scalars()
        .all()
    )
    assert [item.provider_message_id for item in stored] == ["msg-1", "msg-2"]
    assert stored[0].risk_level == "high"
    assert stored[0].reasons == ["要求點擊連結並輸入帳號密碼"]
    assert stored[0].advice is not None

    # 同步成功後推進增量起點
    await db_session.refresh(account)
    assert account.last_synced_at is not None
    assert account.last_sync_error is None

    # 第二輪：同一批信全部略過，不再打 LLM
    results = await mail_sync.sync_user_accounts(db_session, user.id, rag)
    assert (results[0].analyzed, results[0].skipped) == (0, 2)
    assert len(rag.calls) == 2


async def test_sync_analyzes_messages_newest_first(db_session, monkeypatch) -> None:
    """判定順序依收信時間新到舊，不跟著提供者列表 API 的回傳順序走。"""
    user = User(email="ordered@example.com", name="排序測試", password_hash=None)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    account = MailAccount(
        user_id=user.id,
        provider="gmail",
        email_address="ordered@example.com",
        refresh_token_encrypted=encrypt_secret("refresh-secret-10"),
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)

    # 刻意打亂：Gmail 的 messages.list 沒有排序參數，順序不是保證
    received = {
        "old": datetime(2026, 8, 4, 9, 0, 0),
        "new": datetime(2026, 8, 4, 18, 0, 0),
        "mid": datetime(2026, 8, 4, 13, 0, 0),
    }

    async def fake_get_access_token(db, acc) -> str:
        return "access-token"

    async def fake_list_message_ids(provider, access_token, *, since, limit):
        return ["old", "new", "mid"]

    async def fake_fetch_message_content(provider, access_token, message_id):
        return _fake_mail(
            message_id,
            subject="您的帳戶已被鎖定",
            body="請立即點擊 http://bank-secure.example/login 驗證身分",
            received_at=received[message_id],
        )

    monkeypatch.setattr(mail_sync, "get_access_token", fake_get_access_token)
    monkeypatch.setattr(mail_sync, "list_message_ids", fake_list_message_ids)
    monkeypatch.setattr(mail_sync, "fetch_message_content", fake_fetch_message_content)

    results = await mail_sync.sync_user_accounts(db_session, user.id, FakeRagService())
    assert results[0].analyzed == 3

    stored = (
        (await db_session.execute(select(MailAnalysis).order_by(MailAnalysis.id)))
        .scalars()
        .all()
    )
    assert [item.provider_message_id for item in stored] == ["new", "mid", "old"]


async def test_sync_deactivates_account_on_expired_auth(db_session, monkeypatch) -> None:
    """授權被撤銷時停用連接，避免排程每輪白打提供者 API。"""
    user = User(email="revoked@example.com", name="撤銷測試", password_hash=None)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    account = MailAccount(
        user_id=user.id,
        provider="gmail",
        email_address="revoked@example.com",
        refresh_token_encrypted=encrypt_secret("refresh-secret-4"),
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)

    async def fake_get_access_token(db, acc) -> str:
        return "access-token"

    async def fake_list_message_ids(provider, access_token, *, since, limit):
        raise mail_provider.MailAuthExpiredError("信箱授權已失效，請重新連接信箱")

    monkeypatch.setattr(mail_sync, "get_access_token", fake_get_access_token)
    monkeypatch.setattr(mail_sync, "list_message_ids", fake_list_message_ids)

    results = await mail_sync.sync_user_accounts(db_session, user.id, FakeRagService())
    assert results[0].error is not None

    await db_session.refresh(account)
    assert account.is_active is False
    assert account.last_sync_error is not None
    # 失敗時不得推進增量起點，否則這段時間的信會被永久跳過
    assert account.last_synced_at is None


async def test_sync_keeps_account_active_when_provider_unconfigured(
    db_session, monkeypatch
) -> None:
    """後端沒設定憑證屬於配置問題，不該把使用者的連接停掉逼他重連。"""
    user = User(email="unconfigured@example.com", name="未設定", password_hash=None)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    account = MailAccount(
        user_id=user.id,
        provider="gmail",
        email_address="unconfigured@example.com",
        refresh_token_encrypted=encrypt_secret("refresh-secret-9"),
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)

    monkeypatch.setattr(settings, "GMAIL_CLIENT_ID", "")
    monkeypatch.setattr(settings, "GMAIL_CLIENT_SECRET", "")

    results = await mail_sync.sync_user_accounts(db_session, user.id, FakeRagService())
    assert "GMAIL_CLIENT_ID" in (results[0].error or "")

    await db_session.refresh(account)
    assert account.is_active is True
    assert account.last_synced_at is None


def test_build_detect_text_truncates_to_limit() -> None:
    """送進偵測的文字長度須對齊 RagDetectRequest 上限。"""
    mail = _fake_mail("msg-long", subject="標題", body="詐" * 10_000)
    text = mail_sync.build_detect_text(mail)
    assert len(text) == settings.MAIL_DETECT_MAX_CHARS


async def test_sync_endpoint_uses_current_user(
    client: AsyncClient, auth_headers: dict[str, str], db_session, monkeypatch
) -> None:
    """POST /mail/sync 只同步自己的信箱。"""
    user = await _get_user(db_session)
    account = MailAccount(
        user_id=user.id,
        provider="outlook",
        email_address="me@outlook.example",
        refresh_token_encrypted=encrypt_secret("refresh-secret-5"),
    )
    db_session.add(account)
    await db_session.commit()

    async def fake_get_access_token(db, acc) -> str:
        return "access-token"

    async def fake_list_message_ids(provider, access_token, *, since, limit):
        return ["msg-9"]

    async def fake_fetch_message_content(provider, access_token, message_id):
        return _fake_mail(message_id, subject="中獎通知", body="請提供帳號領獎")

    monkeypatch.setattr(mail_sync, "get_access_token", fake_get_access_token)
    monkeypatch.setattr(mail_sync, "list_message_ids", fake_list_message_ids)
    monkeypatch.setattr(mail_sync, "fetch_message_content", fake_fetch_message_content)
    app.dependency_overrides[get_rag_service] = FakeRagService

    try:
        response = await client.post("/api/v1/mail/sync", headers=auth_headers)
    finally:
        app.dependency_overrides.pop(get_rag_service, None)

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["accounts"]) == 1
    assert body["accounts"][0]["analyzed"] == 1


# ============================================================
# 讀取端點
# ============================================================

async def test_messages_returns_verdict_without_preview(
    client: AsyncClient, auth_headers: dict[str, str], db_session
) -> None:
    """include_preview=false 時完全不呼叫提供者，只回傳資料庫中的判定。"""
    user = await _get_user(db_session)
    account = MailAccount(
        user_id=user.id,
        provider="gmail",
        email_address="victim@example.com",
        refresh_token_encrypted=encrypt_secret("refresh-secret-6"),
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)

    base_time = utcnow()
    for index, risk in enumerate(["safe", "high"]):
        db_session.add(
            MailAnalysis(
                user_id=user.id,
                mail_account_id=account.id,
                provider="gmail",
                provider_message_id=f"msg-{index}",
                received_at=base_time + timedelta(minutes=index),
                is_scam=risk == "high",
                risk_level=risk,
                scam_type="釣魚郵件" if risk == "high" else None,
                confidence=0.8,
                reasons=[f"理由 {index}"],
                advice="保持警覺",
                model="fake-model",
            )
        )
    await db_session.commit()

    response = await client.get(
        "/api/v1/mail/messages",
        params={"include_preview": "false"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 2
    # 依收信時間新到舊
    assert [item["message_id"] for item in body["items"]] == ["msg-1", "msg-0"]

    latest = body["items"][0]
    assert latest["risk_level"] == "high"
    assert latest["reasons"] == ["理由 1"]
    assert latest["account_email"] == "victim@example.com"
    # 不落地的顯示欄位在未取回時為 null
    assert latest["preview_available"] is False
    assert latest["subject"] is None
    assert latest["sender"] is None

    # 風險等級篩選
    filtered = await client.get(
        "/api/v1/mail/messages",
        params={"include_preview": "false", "risk_level": "high"},
        headers=auth_headers,
    )
    assert filtered.json()["total"] == 1


async def test_messages_merges_live_summary(
    client: AsyncClient, auth_headers: dict[str, str], db_session, monkeypatch
) -> None:
    """主旨／寄件者由即時 passthrough 補上，與資料庫的判定合併回傳。"""
    user = await _get_user(db_session)
    account = MailAccount(
        user_id=user.id,
        provider="gmail",
        email_address="victim@example.com",
        refresh_token_encrypted=encrypt_secret("refresh-secret-7"),
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)

    db_session.add(
        MailAnalysis(
            user_id=user.id,
            mail_account_id=account.id,
            provider="gmail",
            provider_message_id="msg-live",
            received_at=utcnow(),
            is_scam=True,
            risk_level="high",
            scam_type="釣魚郵件",
            confidence=0.95,
            reasons=["偽造寄件網域"],
            advice="請勿點擊",
            model="fake-model",
        )
    )
    await db_session.commit()

    async def fake_get_access_token(db, acc) -> str:
        return "access-token"

    async def fake_fetch_message_summary(provider, access_token, message_id):
        return mail_provider.MailSummary(
            message_id=message_id,
            subject="您的包裹配送失敗",
            sender="Delivery <no-reply@parcel.example>",
            preview="請重新確認地址",
            received_at=utcnow(),
        )

    monkeypatch.setattr(mail_sync, "get_access_token", fake_get_access_token)
    monkeypatch.setattr(
        "app.api.endpoints.mail.fetch_message_summary", fake_fetch_message_summary
    )

    response = await client.get("/api/v1/mail/messages", headers=auth_headers)
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["preview_available"] is True
    assert item["subject"] == "您的包裹配送失敗"
    assert item["sender"] == "Delivery <no-reply@parcel.example>"
    assert item["risk_level"] == "high"


async def test_messages_degrades_when_provider_unavailable(
    client: AsyncClient, auth_headers: dict[str, str], db_session, monkeypatch
) -> None:
    """提供者取不到摘要時仍要回傳判定結果，不能整個端點失敗。"""
    user = await _get_user(db_session)
    account = MailAccount(
        user_id=user.id,
        provider="gmail",
        email_address="victim@example.com",
        refresh_token_encrypted=encrypt_secret("refresh-secret-8"),
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)

    db_session.add(
        MailAnalysis(
            user_id=user.id,
            mail_account_id=account.id,
            provider="gmail",
            provider_message_id="msg-down",
            received_at=utcnow(),
            is_scam=False,
            risk_level="safe",
            scam_type=None,
            confidence=0.1,
            reasons=[],
            advice=None,
            model="similarity-gate",
        )
    )
    await db_session.commit()

    async def failing_get_access_token(db, acc) -> str:
        raise mail_sync.MailSyncError("權杖解密失敗")

    monkeypatch.setattr(mail_sync, "get_access_token", failing_get_access_token)

    response = await client.get("/api/v1/mail/messages", headers=auth_headers)
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["preview_available"] is False
    assert item["risk_level"] == "safe"


# ============================================================
# 單封信完整內容（回報用）
# ============================================================

async def _seed_analysis(
    db_session, *, email_address: str, refresh_token: str, message_id: str
) -> tuple[MailAccount, MailAnalysis]:
    """建一組「已連接信箱 + 一封已判定的信」，供內容端點的測試共用。"""
    user = await _get_user(db_session)
    account = MailAccount(
        user_id=user.id,
        provider="gmail",
        email_address=email_address,
        refresh_token_encrypted=encrypt_secret(refresh_token),
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)

    analysis = MailAnalysis(
        user_id=user.id,
        mail_account_id=account.id,
        provider="gmail",
        provider_message_id=message_id,
        received_at=utcnow(),
        is_scam=True,
        risk_level="high",
        scam_type="釣魚郵件",
        confidence=0.93,
        reasons=["要求輸入銀行帳號"],
        advice="請勿點擊",
        model="fake-model",
    )
    db_session.add(analysis)
    await db_session.commit()
    await db_session.refresh(analysis)
    return account, analysis


async def test_message_content_returns_full_body(
    client: AsyncClient, auth_headers: dict[str, str], db_session, monkeypatch
) -> None:
    """回報用端點要拿到完整內文，並組好可直接送出的 report_text。"""
    _, analysis = await _seed_analysis(
        db_session,
        email_address="victim@example.com",
        refresh_token="refresh-secret-9",
        message_id="msg-report",
    )

    async def fake_get_access_token(db, acc) -> str:
        return "access-token"

    async def fake_fetch_message_content(provider, access_token, message_id):
        return MailContent(
            message_id=message_id,
            subject="您的帳戶即將被凍結",
            sender="Bank <no-reply@bank.example>",
            preview="請立即驗證",
            received_at=utcnow(),
            body="請立即點擊以下連結驗證您的網路銀行帳號密碼。",
        )

    monkeypatch.setattr(mail_sync, "get_access_token", fake_get_access_token)
    monkeypatch.setattr(
        "app.api.endpoints.mail.fetch_message_content", fake_fetch_message_content
    )

    response = await client.get(
        f"/api/v1/mail/messages/{analysis.id}/content", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["message_id"] == "msg-report"
    assert body["account_email"] == "victim@example.com"
    assert body["subject"] == "您的帳戶即將被凍結"
    # 完整內文（不是列表那種 200 字預覽片段）
    assert body["body"] == "請立即點擊以下連結驗證您的網路銀行帳號密碼。"
    assert body["body_truncated"] is False
    # 回報文字帶上寄件者與主旨，結構與偵測時餵給模型的一致
    assert body["report_text"] == (
        "寄件者：Bank <no-reply@bank.example>\n"
        "主旨：您的帳戶即將被凍結\n"
        "\n"
        "請立即點擊以下連結驗證您的網路銀行帳號密碼。"
    )
    # 回報表單預填用的判定結果
    assert body["scam_type"] == "釣魚郵件"
    assert body["risk_level"] == "high"


async def test_message_content_truncates_oversized_body(
    client: AsyncClient, auth_headers: dict[str, str], db_session, monkeypatch
) -> None:
    """超長內文截斷到上限並標記 body_truncated。"""
    _, analysis = await _seed_analysis(
        db_session,
        email_address="victim2@example.com",
        refresh_token="refresh-secret-10",
        message_id="msg-huge",
    )

    async def fake_get_access_token(db, acc) -> str:
        return "access-token"

    async def fake_fetch_message_content(provider, access_token, message_id):
        return MailContent(
            message_id=message_id,
            subject="促銷",
            sender="ad@example.com",
            preview="促銷",
            received_at=utcnow(),
            body="長" * (settings.MAIL_CONTENT_MAX_CHARS + 500),
        )

    monkeypatch.setattr(mail_sync, "get_access_token", fake_get_access_token)
    monkeypatch.setattr(
        "app.api.endpoints.mail.fetch_message_content", fake_fetch_message_content
    )

    response = await client.get(
        f"/api/v1/mail/messages/{analysis.id}/content", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["body_truncated"] is True
    assert len(body["body"]) == settings.MAIL_CONTENT_MAX_CHARS


async def test_message_content_rejects_unknown_analysis(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """不存在（或不屬於自己）的判定紀錄一律 404。"""
    response = await client.get(
        "/api/v1/mail/messages/999999/content", headers=auth_headers
    )
    assert response.status_code == 404


async def test_message_content_fails_loudly_when_provider_unavailable(
    client: AsyncClient, auth_headers: dict[str, str], db_session, monkeypatch
) -> None:
    """取不到內文要回錯誤，不能像列表那樣把欄位留空就當作成功。"""
    _, analysis = await _seed_analysis(
        db_session,
        email_address="victim3@example.com",
        refresh_token="refresh-secret-11",
        message_id="msg-gone",
    )

    async def fake_get_access_token(db, acc) -> str:
        return "access-token"

    async def failing_fetch_message_content(provider, access_token, message_id):
        raise mail_provider.MailFetchError("信件 API 回傳 HTTP 404")

    monkeypatch.setattr(mail_sync, "get_access_token", fake_get_access_token)
    monkeypatch.setattr(
        "app.api.endpoints.mail.fetch_message_content", failing_fetch_message_content
    )

    response = await client.get(
        f"/api/v1/mail/messages/{analysis.id}/content", headers=auth_headers
    )
    assert response.status_code == 502


async def test_message_content_reports_expired_authorization(
    client: AsyncClient, auth_headers: dict[str, str], db_session, monkeypatch
) -> None:
    """授權失效回 409，且不順手停用信箱（停用是同步流程的職責）。"""
    account, analysis = await _seed_analysis(
        db_session,
        email_address="victim4@example.com",
        refresh_token="refresh-secret-12",
        message_id="msg-expired",
    )

    async def fake_get_access_token(db, acc) -> str:
        return "access-token"

    async def expired_fetch_message_content(provider, access_token, message_id):
        raise mail_provider.MailAuthExpiredError("信箱授權已失效")

    monkeypatch.setattr(mail_sync, "get_access_token", fake_get_access_token)
    monkeypatch.setattr(
        "app.api.endpoints.mail.fetch_message_content", expired_fetch_message_content
    )

    response = await client.get(
        f"/api/v1/mail/messages/{analysis.id}/content", headers=auth_headers
    )
    assert response.status_code == 409

    await db_session.refresh(account)
    assert account.is_active is True


# ============================================================
# 提供者回應解析
# ============================================================

def _b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def test_gmail_body_prefers_plain_text_in_nested_parts() -> None:
    """multipart 巢狀結構要取到 text/plain，而非 HTML 版本。"""
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {
                "mimeType": "multipart/alternative",
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": _b64url("純文字內容")}},
                    {
                        "mimeType": "text/html",
                        "body": {"data": _b64url("<p>HTML 內容</p>")},
                    },
                ],
            }
        ],
    }
    assert mail_provider._gmail_extract_body(payload) == "純文字內容"


def test_gmail_body_falls_back_to_html() -> None:
    """只有 HTML 版本時轉成純文字（含實體還原、去標籤）。"""
    payload = {
        "mimeType": "text/html",
        "body": {"data": _b64url("<style>p{}</style><p>點我&amp;領獎</p>")},
    }
    body = mail_provider._gmail_extract_body(payload)
    assert "點我&領獎" in body
    assert "<p>" not in body
    assert "style" not in body


def test_gmail_received_at_parses_internal_date() -> None:
    """internalDate（毫秒 epoch）轉為 naive UTC。"""
    message = {"internalDate": "1754265600000"}
    assert mail_provider._gmail_received_at(message) == datetime(2025, 8, 4, 0, 0, 0)


def test_graph_sender_combines_name_and_address() -> None:
    message = {
        "from": {"emailAddress": {"name": "客服中心", "address": "svc@example.com"}}
    }
    assert mail_provider._graph_sender(message) == "客服中心 <svc@example.com>"


def test_graph_received_at_parses_iso_zulu() -> None:
    message = {"receivedDateTime": "2026-08-04T09:30:00Z"}
    assert mail_provider._graph_received_at(message) == datetime(2026, 8, 4, 9, 30, 0)


# ============================================================
# Bug A：增量抓取的時間游標
# ============================================================

def _account_with_cursor(cursor: datetime | None) -> MailAccount:
    """只為了算時間視窗而建的 MailAccount（不進資料庫）。"""
    return MailAccount(
        id=1,
        user_id=1,
        provider="gmail",
        email_address="victim@example.com",
        refresh_token_encrypted="x",
        last_synced_at=cursor,
    )


def test_sync_window_uses_lookback_without_cursor() -> None:
    """沒有游標（首次連接／剛重新授權）→ 回溯視窗。"""
    started_at = datetime(2026, 8, 12, 12, 0, 0)
    window = mail_sync.resolve_sync_window(_account_with_cursor(None), started_at)
    assert window == started_at - timedelta(
        hours=settings.MAIL_SYNC_INITIAL_LOOKBACK_HOURS
    )


def test_sync_window_rejects_future_cursor() -> None:
    """游標跑到未來時退回回溯視窗。

    這是 fetched=0／error=null 這種「安靜壞掉」的成因：游標比現在晚，
    「只抓比游標新的信」就永遠篩不到東西，而且不會自己好。
    """
    started_at = datetime(2026, 8, 12, 12, 0, 0)
    account = _account_with_cursor(started_at + timedelta(hours=8))
    window = mail_sync.resolve_sync_window(account, started_at)
    assert window == started_at - timedelta(
        hours=settings.MAIL_SYNC_INITIAL_LOOKBACK_HOURS
    )


def test_sync_window_overlaps_previous_cursor() -> None:
    """正常游標要往回多退一段重疊區間，免得踩到提供者的列表延遲。"""
    started_at = datetime(2026, 8, 12, 12, 0, 0)
    cursor = started_at - timedelta(minutes=5)
    window = mail_sync.resolve_sync_window(_account_with_cursor(cursor), started_at)
    assert window == cursor - timedelta(minutes=settings.MAIL_SYNC_OVERLAP_MINUTES)
    assert window < cursor


def test_gmail_after_query_backs_off_one_day() -> None:
    """Gmail 的 after: 只到日期精度，而且要往回多退一天。

    epoch 秒級時間戳看起來精確，實際上 Gmail 是用信箱自己的時區換算日期的，
    再加上搜尋索引的延遲，假裝精確反而會漏信。
    """
    since = datetime(2026, 8, 12, 3, 30, 0)
    assert mail_provider._gmail_after_query(since) == "after:2026/08/11"


async def test_reauthorization_resets_sync_cursor(db_session) -> None:
    """重新授權要把游標歸零，否則斷線期間的信永遠補不回來。"""
    account = await _service_account(
        db_session, refresh_token="refresh-old", email_address="reauth@example.com"
    )
    # 模擬「同步過一陣子之後授權失效」的狀態
    account.last_synced_at = utcnow() - timedelta(days=3)
    account.last_sync_error = "信箱授權已失效"
    account.is_active = False
    await db_session.commit()

    updated = await crud_mail.upsert_account(
        db_session,
        user_id=account.user_id,
        provider="gmail",
        email_address="reauth@example.com",
        refresh_token_encrypted=encrypt_secret("refresh-new"),
    )

    # 同一筆紀錄（不是第二筆），且恢復成「全新連接」的狀態
    assert updated.id == account.id
    assert updated.is_active is True
    assert updated.last_synced_at is None
    assert updated.last_sync_error is None
    assert decrypt_secret(updated.refresh_token_encrypted) == "refresh-new"


async def test_sync_result_reports_query_window(db_session, monkeypatch) -> None:
    """同步結果要帶出這次查詢的起點，fetched=0 時才分得出是哪一種 0。"""
    account = await _service_account(
        db_session, refresh_token="refresh-window", email_address="window@example.com"
    )

    async def fake_get_access_token(db, acc) -> str:
        return "access-token"

    async def fake_list_message_ids(provider, access_token, *, since, limit):
        return []

    monkeypatch.setattr(mail_sync, "get_access_token", fake_get_access_token)
    monkeypatch.setattr(mail_sync, "list_message_ids", fake_list_message_ids)

    result = await mail_sync.sync_account(db_session, account, FakeRagService())
    assert result.fetched == 0
    assert result.error is None
    assert result.synced_since is not None
    # 首次同步 → 起點是回溯視窗，而不是「現在」
    assert result.synced_since < utcnow() - timedelta(hours=1)


# ============================================================
# Bug B：暫時性失敗不得停用信箱
# ============================================================

def _token_error_response(status_code: int, body: str) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        text=body,
        request=httpx.Request("POST", "https://oauth2.googleapis.com/token"),
    )


def test_oauth_error_code_parses_provider_payload() -> None:
    """錯誤碼取自回應主體；非 JSON（超載時的 HTML 錯誤頁）要當成未知。"""
    revoked = _token_error_response(400, '{"error": "invalid_grant"}')
    assert mail_oauth._oauth_error_code(revoked) == "invalid_grant"

    overloaded = _token_error_response(503, "<html>Service Unavailable</html>")
    assert mail_oauth._oauth_error_code(overloaded) == ""


async def test_transient_token_failure_keeps_account_active(
    db_session, monkeypatch
) -> None:
    """Google 端一次 5xx／連線失敗，不能把使用者的信箱停用。

    這正是「授權每隔幾小時自己失效」的成因：排程每五分鐘打一次 Google，
    跑幾小時就有足夠機會撞上一次暫時性失敗。
    """
    account = await _service_account(
        db_session,
        refresh_token="refresh-transient",
        email_address="transient@example.com",
    )

    async def flaky_refresh_access_token(provider, refresh_token):
        raise MailOAuthError("無法連線到 Gmail 權杖端點：ConnectTimeout")

    monkeypatch.setattr(mail_sync, "refresh_access_token", flaky_refresh_access_token)

    result = await mail_sync.sync_account(db_session, account, FakeRagService())
    assert result.error is not None
    await db_session.refresh(account)
    assert account.is_active is True
    assert account.last_sync_error is not None


async def test_revoked_grant_deactivates_account(db_session, monkeypatch) -> None:
    """提供者明確回報 invalid_grant 時才停用——這才是真的要重新授權。"""
    account = await _service_account(
        db_session, refresh_token="refresh-revoked", email_address="revoked@example.com"
    )

    async def revoked_refresh_access_token(provider, refresh_token):
        raise MailAuthRevokedError("Gmail 權杖端點回傳 HTTP 400：invalid_grant")

    monkeypatch.setattr(mail_sync, "refresh_access_token", revoked_refresh_access_token)

    result = await mail_sync.sync_account(db_session, account, FakeRagService())
    assert result.error is not None
    await db_session.refresh(account)
    assert account.is_active is False


# ============================================================
# 寄件人封鎖（提供者端「真封鎖」）
# ============================================================

def test_normalize_sender_address() -> None:
    """封鎖以位址為準：顯示名稱是寄件人自己填的，不能拿來比對。"""
    normalize = mail_provider.normalize_sender_address
    assert normalize("詐騙集團 <Bad@Example.COM>") == "bad@example.com"
    assert normalize("bad@example.com") == "bad@example.com"
    assert normalize("  bad@example.com  ") == "bad@example.com"
    # 取不出位址的輸入
    assert normalize("詐騙集團") is None
    assert normalize("") is None
    assert normalize(None) is None


async def test_block_sender_creates_filter_and_record(
    client: AsyncClient, auth_headers: dict[str, str], db_session, monkeypatch
) -> None:
    """封鎖要真的在 Gmail 端建規則，並記下規則 ID 供日後解除。"""
    account = await _connect_account(db_session, refresh_token="refresh-block-1")
    calls: list[tuple[str, str]] = []

    async def fake_get_access_token(db, acc) -> str:
        return "access-token"

    async def fake_block_sender(provider, access_token, sender_address) -> str:
        calls.append((provider, sender_address))
        return "filter-abc"

    monkeypatch.setattr(mail_sync, "get_access_token", fake_get_access_token)
    monkeypatch.setattr("app.api.endpoints.mail.block_sender", fake_block_sender)

    response = await client.post(
        f"/api/v1/mail/accounts/{account.id}/block-sender",
        json={"sender": "詐騙集團 <Bad@Example.COM>"},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    # 顯示名稱丟掉、位址轉小寫後才送進 Gmail
    assert calls == [("gmail", "bad@example.com")]
    assert response.json()["sender_address"] == "bad@example.com"

    listed = await client.get(
        f"/api/v1/mail/accounts/{account.id}/blocked-senders", headers=auth_headers
    )
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 1
    assert body["items"][0]["sender_address"] == "bad@example.com"
    assert body["items"][0]["provider_filter_id"] == "filter-abc"


async def test_block_sender_rejects_duplicate(
    client: AsyncClient, auth_headers: dict[str, str], db_session, monkeypatch
) -> None:
    """重複封鎖會在 Gmail 端堆出多條規則，而我們只留得住最後一條的 ID。"""
    account = await _connect_account(db_session, refresh_token="refresh-block-2")

    async def fake_get_access_token(db, acc) -> str:
        return "access-token"

    async def fake_block_sender(provider, access_token, sender_address) -> str:
        return "filter-dup"

    monkeypatch.setattr(mail_sync, "get_access_token", fake_get_access_token)
    monkeypatch.setattr("app.api.endpoints.mail.block_sender", fake_block_sender)

    payload = {"sender": "bad@example.com"}
    first = await client.post(
        f"/api/v1/mail/accounts/{account.id}/block-sender",
        json=payload,
        headers=auth_headers,
    )
    assert first.status_code == 201
    second = await client.post(
        f"/api/v1/mail/accounts/{account.id}/block-sender",
        json=payload,
        headers=auth_headers,
    )
    assert second.status_code == 409


async def test_block_sender_requires_settings_scope(
    client: AsyncClient, auth_headers: dict[str, str], db_session, monkeypatch
) -> None:
    """加 scope 之前連接的信箱，權杖只有 gmail.readonly → 403 並要求重新連接。"""
    account = await _connect_account(db_session, refresh_token="refresh-block-3")

    async def fake_get_access_token(db, acc) -> str:
        return "access-token"

    async def denied_block_sender(provider, access_token, sender_address) -> str:
        raise mail_provider.MailPermissionError("信箱授權範圍不足：insufficientPermissions")

    monkeypatch.setattr(mail_sync, "get_access_token", fake_get_access_token)
    monkeypatch.setattr("app.api.endpoints.mail.block_sender", denied_block_sender)

    response = await client.post(
        f"/api/v1/mail/accounts/{account.id}/block-sender",
        json={"sender": "bad@example.com"},
        headers=auth_headers,
    )
    assert response.status_code == 403
    assert "重新連接" in response.json()["detail"]

    # 規則沒建成，就不能留下一筆「以為封鎖了」的紀錄
    listed = await client.get(
        f"/api/v1/mail/accounts/{account.id}/blocked-senders", headers=auth_headers
    )
    assert listed.json()["total"] == 0


async def test_block_sender_rejects_unparsable_address(
    client: AsyncClient, auth_headers: dict[str, str], db_session
) -> None:
    """取不出位址就不能封鎖（否則會建出一條抓不到任何信的規則）。"""
    account = await _connect_account(db_session, refresh_token="refresh-block-4")
    response = await client.post(
        f"/api/v1/mail/accounts/{account.id}/block-sender",
        json={"sender": "詐騙集團"},
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_unblock_sender_removes_filter(
    client: AsyncClient, auth_headers: dict[str, str], db_session, monkeypatch
) -> None:
    """解除封鎖要連 Gmail 端的規則一起刪掉。"""
    account = await _connect_account(db_session, refresh_token="refresh-block-5")
    deleted: list[str] = []

    async def fake_get_access_token(db, acc) -> str:
        return "access-token"

    async def fake_block_sender(provider, access_token, sender_address) -> str:
        return "filter-xyz"

    async def fake_unblock_sender(provider, access_token, filter_id) -> None:
        deleted.append(filter_id)

    monkeypatch.setattr(mail_sync, "get_access_token", fake_get_access_token)
    monkeypatch.setattr("app.api.endpoints.mail.block_sender", fake_block_sender)
    monkeypatch.setattr("app.api.endpoints.mail.unblock_sender", fake_unblock_sender)

    await client.post(
        f"/api/v1/mail/accounts/{account.id}/block-sender",
        json={"sender": "bad@example.com"},
        headers=auth_headers,
    )
    response = await client.delete(
        f"/api/v1/mail/accounts/{account.id}/blocked-senders/bad@example.com",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert deleted == ["filter-xyz"]

    listed = await client.get(
        f"/api/v1/mail/accounts/{account.id}/blocked-senders", headers=auth_headers
    )
    assert listed.json()["total"] == 0


async def test_unblock_keeps_record_when_provider_delete_fails(
    client: AsyncClient, auth_headers: dict[str, str], db_session, monkeypatch
) -> None:
    """Gmail 端規則沒刪掉就不能刪紀錄，否則規則 ID 遺失、信照樣被擋。"""
    account = await _connect_account(db_session, refresh_token="refresh-block-6")

    async def fake_get_access_token(db, acc) -> str:
        return "access-token"

    async def fake_block_sender(provider, access_token, sender_address) -> str:
        return "filter-stuck"

    async def failing_unblock_sender(provider, access_token, filter_id) -> None:
        raise mail_provider.MailFetchError("信件 API 回傳 HTTP 500")

    monkeypatch.setattr(mail_sync, "get_access_token", fake_get_access_token)
    monkeypatch.setattr("app.api.endpoints.mail.block_sender", fake_block_sender)
    monkeypatch.setattr("app.api.endpoints.mail.unblock_sender", failing_unblock_sender)

    await client.post(
        f"/api/v1/mail/accounts/{account.id}/block-sender",
        json={"sender": "bad@example.com"},
        headers=auth_headers,
    )
    response = await client.delete(
        f"/api/v1/mail/accounts/{account.id}/blocked-senders/bad@example.com",
        headers=auth_headers,
    )
    assert response.status_code == 502

    listed = await client.get(
        f"/api/v1/mail/accounts/{account.id}/blocked-senders", headers=auth_headers
    )
    assert listed.json()["total"] == 1


async def test_sync_skips_blocked_sender(db_session, monkeypatch) -> None:
    """過濾規則生效前的空窗期：已封鎖寄件人的信不再送進 AI 判定。"""
    account = await _service_account(
        db_session, refresh_token="refresh-block-7", email_address="blocked@example.com"
    )
    await crud_mail.upsert_blocked_sender(
        db_session,
        account_id=account.id,
        sender_address="bad@example.com",
        provider_filter_id="filter-1",
    )

    received = {
        "msg-blocked": utcnow() - timedelta(minutes=2),
        "msg-normal": utcnow() - timedelta(minutes=1),
    }
    senders = {
        "msg-blocked": "詐騙集團 <bad@example.com>",
        "msg-normal": "客服 <help@shop.example>",
    }

    async def fake_get_access_token(db, acc) -> str:
        return "access-token"

    async def fake_list_message_ids(provider, access_token, *, since, limit):
        return list(received)

    async def fake_fetch_message_content(provider, access_token, message_id):
        return MailContent(
            message_id=message_id,
            subject="通知",
            sender=senders[message_id],
            preview="通知",
            received_at=received[message_id],
            body="請點擊連結",
        )

    monkeypatch.setattr(mail_sync, "get_access_token", fake_get_access_token)
    monkeypatch.setattr(mail_sync, "list_message_ids", fake_list_message_ids)
    monkeypatch.setattr(mail_sync, "fetch_message_content", fake_fetch_message_content)

    rag = FakeRagService()
    result = await mail_sync.sync_account(db_session, account, rag)

    assert result.fetched == 2
    assert result.analyzed == 1
    assert result.skipped == 1
    # 被封鎖的那封完全沒進偵測
    assert len(rag.calls) == 1
    assert "bad@example.com" not in rag.calls[0]

    stored = await db_session.execute(
        select(MailAnalysis).where(MailAnalysis.mail_account_id == account.id)
    )
    assert [item.provider_message_id for item in stored.scalars().all()] == ["msg-normal"]
