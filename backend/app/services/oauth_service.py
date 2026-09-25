"""社交登入（OAuth）驗證服務。

向提供者官方端點驗證權杖並取回使用者資訊：
- Google：以 tokeninfo 端點驗證 ID Token（並核對 audience）
- Facebook：以 Graph API 驗證 Access Token 並取得使用者資料
"""

import logging
from dataclasses import dataclass

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# 提供者官方驗證端點
GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
FACEBOOK_ME_URL = "https://graph.facebook.com/v18.0/me"


class OAuthError(Exception):
    """OAuth 驗證失敗（權杖無效、提供者回應異常等）。"""


@dataclass
class OAuthUserInfo:
    """自提供者取回的使用者資訊。"""

    provider: str  # google / facebook
    provider_user_id: str  # 提供者端唯一識別碼
    email: str | None
    name: str
    avatar_url: str | None = None
    email_verified: bool = False


async def _verify_google(id_token: str) -> OAuthUserInfo:
    """驗證 Google ID Token 並取回使用者資訊。"""
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(GOOGLE_TOKENINFO_URL, params={"id_token": id_token})

    if response.status_code != 200:
        raise OAuthError("Google ID Token 無效或已過期")

    data = response.json()

    # 核對 audience，確保權杖是簽發給本 App 的
    if settings.GOOGLE_CLIENT_ID and data.get("aud") != settings.GOOGLE_CLIENT_ID:
        raise OAuthError("Google ID Token 的 audience 不符")

    return OAuthUserInfo(
        provider="google",
        provider_user_id=data["sub"],
        email=data.get("email"),
        name=data.get("name") or (data.get("email") or "Google 使用者").split("@")[0],
        avatar_url=data.get("picture"),
        email_verified=data.get("email_verified") in (True, "true"),
    )


async def _verify_facebook(access_token: str) -> OAuthUserInfo:
    """驗證 Facebook Access Token 並取回使用者資訊。"""
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            FACEBOOK_ME_URL,
            params={
                "fields": "id,name,email,picture.type(large)",
                "access_token": access_token,
            },
        )

    if response.status_code != 200:
        raise OAuthError("Facebook Access Token 無效或已過期")

    data = response.json()
    avatar_url = (data.get("picture") or {}).get("data", {}).get("url")

    return OAuthUserInfo(
        provider="facebook",
        provider_user_id=data["id"],
        email=data.get("email"),
        name=data.get("name") or "Facebook 使用者",
        avatar_url=avatar_url,
        # Facebook Graph API 回傳的 email 已經過提供者驗證
        email_verified=bool(data.get("email")),
    )


async def verify_oauth_token(
    provider: str, *, id_token: str | None = None, access_token: str | None = None
) -> OAuthUserInfo:
    """驗證社交登入權杖，回傳提供者端的使用者資訊。

    Raises:
        OAuthError: 權杖缺漏、無效或提供者不支援。
    """
    if provider == "google":
        if not id_token:
            raise OAuthError("Google 登入需提供 id_token")
        return await _verify_google(id_token)

    if provider == "facebook":
        if not access_token:
            raise OAuthError("Facebook 登入需提供 access_token")
        return await _verify_facebook(access_token)

    raise OAuthError(f"不支援的社交登入提供者：{provider}")
