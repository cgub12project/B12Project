"""認證流程測試：註冊、登入、個人資料、忘記密碼（OTP）、更改密碼。"""

import pytest
from httpx import AsyncClient

from app.services import email_service


async def test_register_and_login(client: AsyncClient):
    """註冊成功後可直接取得權杖，並能以相同帳密登入。"""
    # 註冊
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "user1@example.com", "password": "Secret123", "name": "小明"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["user"]["email"] == "user1@example.com"

    # 重複註冊 → 409
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "user1@example.com", "password": "Secret123", "name": "小明"},
    )
    assert response.status_code == 409

    # 正確登入
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "user1@example.com", "password": "Secret123"},
    )
    assert response.status_code == 200

    # 錯誤密碼 → 401
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "user1@example.com", "password": "WrongPass1"},
    )
    assert response.status_code == 401


async def test_me_and_settings(client: AsyncClient, auth_headers: dict):
    """取得／更新個人資料與設定開關。"""
    # 未帶權杖 → 401
    response = await client.get("/api/v1/users/me")
    assert response.status_code == 401

    # 取得個人資料
    response = await client.get("/api/v1/users/me", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["name"] == "測試使用者"

    # 更新名稱
    response = await client.patch(
        "/api/v1/users/me", json={"name": "新名字"}, headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["name"] == "新名字"

    # 取得設定（預設值）
    response = await client.get("/api/v1/users/me/settings", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["message_monitoring"] is True

    # 關閉訊息監控（其餘開關不變）
    response = await client.put(
        "/api/v1/users/me/settings",
        json={"message_monitoring": False},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["message_monitoring"] is False
    assert body["email_scanning"] is True


async def test_forgot_password_flow(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    """忘記密碼三步驟：發送 OTP → 驗證 OTP → 重設密碼。"""
    # 準備帳號
    await client.post(
        "/api/v1/auth/register",
        json={"email": "forgot@example.com", "password": "OldPass123", "name": "阿華"},
    )

    # 攔截寄信函式以取得 OTP（不實際寄送）
    captured: dict[str, str] = {}

    async def fake_send(to_email: str, otp: str) -> None:
        captured["otp"] = otp

    monkeypatch.setattr(email_service, "send_otp_email", fake_send)

    # 步驟一：發送 OTP（不存在的 Email 也回傳成功，避免帳號列舉）
    response = await client.post(
        "/api/v1/auth/forgot-password", json={"email": "forgot@example.com"}
    )
    assert response.status_code == 200
    assert "otp" in captured

    response = await client.post(
        "/api/v1/auth/forgot-password", json={"email": "nobody@example.com"}
    )
    assert response.status_code == 200

    # 步驟二：錯誤 OTP → 400
    wrong_otp = "000000" if captured["otp"] != "000000" else "111111"
    response = await client.post(
        "/api/v1/auth/verify-otp",
        json={"email": "forgot@example.com", "otp": wrong_otp},
    )
    assert response.status_code == 400

    # 正確 OTP → 取得 reset_token
    response = await client.post(
        "/api/v1/auth/verify-otp",
        json={"email": "forgot@example.com", "otp": captured["otp"]},
    )
    assert response.status_code == 200
    reset_token = response.json()["reset_token"]

    # 步驟三：重設密碼
    response = await client.post(
        "/api/v1/auth/reset-password",
        json={"reset_token": reset_token, "new_password": "NewPass456"},
    )
    assert response.status_code == 200

    # reset_token 為一次性：重複使用 → 400
    response = await client.post(
        "/api/v1/auth/reset-password",
        json={"reset_token": reset_token, "new_password": "Another789"},
    )
    assert response.status_code == 400

    # 新密碼可登入、舊密碼失效
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "forgot@example.com", "password": "NewPass456"},
    )
    assert response.status_code == 200
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "forgot@example.com", "password": "OldPass123"},
    )
    assert response.status_code == 401


async def test_refresh_and_change_password(client: AsyncClient):
    """權杖換發與更改密碼。"""
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "rt@example.com", "password": "Secret123", "name": "阿瑞"},
    )
    tokens = response.json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    # 以 refresh_token 換發新權杖組
    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert response.status_code == 200
    assert response.json()["access_token"]

    # access_token 不能當 refresh_token 用 → 401
    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["access_token"]}
    )
    assert response.status_code == 401

    # 更改密碼：舊密碼錯誤 → 400
    response = await client.post(
        "/api/v1/auth/change-password",
        json={"old_password": "WrongOld1", "new_password": "NewSecret456"},
        headers=headers,
    )
    assert response.status_code == 400

    # 正確更改
    response = await client.post(
        "/api/v1/auth/change-password",
        json={"old_password": "Secret123", "new_password": "NewSecret456"},
        headers=headers,
    )
    assert response.status_code == 200

    # 登出
    response = await client.post("/api/v1/auth/logout", headers=headers)
    assert response.status_code == 200
