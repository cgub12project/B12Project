"""安全性工具模組。

提供密碼雜湊、JWT 產生／驗證、OTP 產生／雜湊、
重設權杖與案件編號產生等功能。
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import bcrypt
import jwt

from app.core.config import settings

# JWT 權杖類型
# mail_oauth：信箱授權流程的 state 參數（短效，見 create_mail_oauth_state）
# local_model：地端模型下載網址的簽章（短效，見 create_local_model_token）
TokenType = Literal["access", "refresh", "mail_oauth", "local_model"]


# ============================================================
# 密碼雜湊（bcrypt）
# ============================================================

def hash_password(plain_password: str) -> str:
    """將明文密碼以 bcrypt 雜湊（含隨機 salt）。"""
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """驗證明文密碼是否與雜湊值相符。"""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), hashed_password.encode("utf-8")
        )
    except ValueError:
        # 雜湊格式不正確（例如資料損毀）時一律視為驗證失敗
        return False


# ============================================================
# JWT 權杖
# ============================================================

def _create_token(
    subject: str | int,
    token_type: TokenType,
    expires_delta: timedelta,
    extra: dict[str, Any] | None = None,
) -> str:
    """建立 JWT 權杖。

    Payload 欄位：
    - sub：使用者 ID
    - type：權杖類型（access / refresh / mail_oauth）
    - iat / exp：簽發與過期時間
    - jti：權杖唯一識別碼
    - extra：額外自訂宣告（例如信箱授權 state 的 provider）
    """
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
        "jti": uuid.uuid4().hex,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: int) -> str:
    """建立 access_token（短效，用於一般 API 認證）。"""
    return _create_token(
        user_id, "access", timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )


def create_refresh_token(user_id: int) -> str:
    """建立 refresh_token（長效，僅用於換發新權杖）。"""
    return _create_token(
        user_id, "refresh", timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    """解碼並驗證 JWT。

    Args:
        token: JWT 字串。
        expected_type: 預期的權杖類型（access / refresh）。

    Raises:
        jwt.InvalidTokenError: 權杖無效、過期或類型不符。
    """
    payload = jwt.decode(
        token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
    )
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("權杖類型不符")
    return payload


# ============================================================
# OTP（忘記密碼 6 位數驗證碼）
# ============================================================

def generate_otp() -> str:
    """產生 6 位數 OTP（前導零補齊，使用密碼學安全亂數）。"""
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(otp: str) -> str:
    """OTP 以 SHA-256 加上系統密鑰（pepper）雜湊後儲存，避免明碼落地。"""
    return hashlib.sha256(f"{otp}{settings.JWT_SECRET_KEY}".encode("utf-8")).hexdigest()


def verify_otp_hash(otp: str, otp_hash: str) -> bool:
    """驗證 OTP 是否與儲存的雜湊相符（常數時間比較防止時序攻擊）。"""
    return secrets.compare_digest(hash_otp(otp), otp_hash)


# ============================================================
# 信箱授權（OAuth state）
# ============================================================

def create_mail_oauth_state(user_id: int, provider: str) -> str:
    """建立信箱授權流程的 `state` 參數（短效 JWT）。

    授權是在系統瀏覽器完成的，Google／Microsoft 打回 callback 時不會帶
    Authorization 標頭，因此「這次授權屬於哪個使用者」必須靠 state 傳遞。
    以 JWT 簽章可同時達成兩件事：
    - 綁定發起者：callback 只認得後端自己簽出來的 state，外人偽造不了
    - 防 CSRF：state 短效且含 jti，撿到舊網址也無法重放
    """
    return _create_token(
        user_id,
        "mail_oauth",
        timedelta(minutes=settings.MAIL_OAUTH_STATE_EXPIRE_MINUTES),
        extra={"provider": provider},
    )


def decode_mail_oauth_state(state: str) -> tuple[int, str]:
    """驗證信箱授權的 `state`，回傳（使用者 ID, 提供者）。

    Raises:
        jwt.InvalidTokenError: state 無效、過期、類型不符或缺少 provider。
    """
    payload = decode_token(state, expected_type="mail_oauth")
    provider = payload.get("provider")
    if not provider:
        raise jwt.InvalidTokenError("state 缺少 provider")
    return int(payload["sub"]), str(provider)


# ============================================================
# 地端模型下載（短效簽章網址）
# ============================================================

def create_local_model_token(
    user_id: int, file_name: str, version: str, expire_hours: int
) -> tuple[str, datetime]:
    """建立地端模型下載網址的簽章，回傳（權杖, 到期時間 UTC）。

    下載是由 Android 的下載元件（可能在 App 已被系統回收後才續傳）發出的，
    那條請求不會帶使用者的 access token，所以授權必須內嵌在網址本身。
    以 JWT 簽章可同時滿足需求書的三件事：
    - 不可猜測：外人偽造不出後端簽的權杖，模型檔沒有匿名可取得的網址
    - 短效：預設 24 小時，足以容納 1.93 GB 的慢速／中斷續傳，過期即失效
    - 綁定版本與檔名：換版後舊網址自動失效，不會下載到已下架的模型

    ⚠ 此權杖只授權「下載這個模型檔」，不能用於其他 API（type 不是 access）。
    """
    expires_at = datetime.now(timezone.utc) + timedelta(hours=expire_hours)
    token = _create_token(
        user_id,
        "local_model",
        timedelta(hours=expire_hours),
        extra={"file": file_name, "ver": version},
    )
    return token, expires_at


def decode_local_model_token(token: str) -> tuple[int, str, str]:
    """驗證下載簽章，回傳（使用者 ID, 檔名, 版本）。

    Raises:
        jwt.InvalidTokenError: 權杖無效、過期、類型不符或缺少檔名／版本。
    """
    payload = decode_token(token, expected_type="local_model")
    file_name = payload.get("file")
    version = payload.get("ver")
    if not file_name or not version:
        raise jwt.InvalidTokenError("下載權杖缺少檔名或版本")
    return int(payload["sub"]), str(file_name), str(version)


# ============================================================
# 其他權杖 / 編號
# ============================================================

def generate_reset_token() -> str:
    """產生密碼重設權杖（OTP 驗證成功後核發，一次性使用）。"""
    return secrets.token_urlsafe(48)


def generate_case_number(prefix: str) -> str:
    """產生案件編號，格式：{前綴}-{yyyymmdd}-{6 碼隨機十六進位大寫}。

    例如：FR-20260705-3FA9C1（完整回報）、AC-20260705-B21E77（帳號回報）。
    """
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    rand_part = secrets.token_hex(3).upper()
    return f"{prefix}-{date_part}-{rand_part}"
