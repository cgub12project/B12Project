"""對稱加密工具：保護落地的第三方權杖。

目前唯一用途是加密信箱連接的 refresh_token（mail_accounts.refresh_token_encrypted）。
資料庫是全組（含教授）都連得進去的 phpMyAdmin，refresh_token 等同信箱的長期
存取權，明碼落地等於把使用者信箱交出去，因此一律加密後才寫入。

採用 Fernet（AES-128-CBC + HMAC-SHA256），密文自帶時間戳與完整性驗證。
金鑰來源：
- 有設定 MAIL_TOKEN_ENCRYPTION_KEY：直接使用（正式環境的正確做法，金鑰與
  資料庫分開保管，拿到 DB 的人沒有金鑰就解不開）
- 未設定：由 JWT_SECRET_KEY 以 SHA-256 衍生，僅為開發便利，啟動時會出現警告
"""

import base64
import hashlib
import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

logger = logging.getLogger(__name__)


class SecretDecryptError(Exception):
    """密文解密失敗（金鑰換過、資料損毀或非本系統寫入的值）。"""


@lru_cache
def _get_fernet() -> Fernet:
    """建立 Fernet 實例（單例；金鑰只解析一次）。"""
    configured = settings.MAIL_TOKEN_ENCRYPTION_KEY.strip()
    if configured:
        try:
            return Fernet(configured.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "MAIL_TOKEN_ENCRYPTION_KEY 格式不正確（需為 Fernet 金鑰，"
                "urlsafe base64 編碼的 32 bytes）。產生方式："
                "python -c \"from cryptography.fernet import Fernet; "
                'print(Fernet.generate_key().decode())"'
            ) from exc

    # 未設定專用金鑰：由 JWT_SECRET_KEY 衍生。此時金鑰與簽章密鑰同源，
    # 安全性取決於 JWT_SECRET_KEY 是否夠隨機且未外流。
    logger.warning(
        "未設定 MAIL_TOKEN_ENCRYPTION_KEY，信箱 refresh_token 的加密金鑰"
        "改由 JWT_SECRET_KEY 衍生；正式環境請設定獨立金鑰。"
    )
    derived = hashlib.sha256(settings.JWT_SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_secret(plaintext: str) -> str:
    """加密敏感字串，回傳可直接存進資料庫的密文（ASCII）。"""
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    """解密 `encrypt_secret` 產生的密文。

    Raises:
        SecretDecryptError: 密文無效或金鑰不符（例如換過 JWT_SECRET_KEY 卻沿用舊資料）。
    """
    try:
        return _get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError) as exc:
        raise SecretDecryptError(
            "權杖解密失敗：加密金鑰可能已更換，請要求使用者重新連接信箱"
        ) from exc
