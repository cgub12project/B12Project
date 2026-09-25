"""信箱連接的 OAuth 授權服務（Gmail / Outlook）。

負責「取得並維持信箱存取權」這一段，不碰信件本身（抓信見 mail_provider.py）：

    App 點「連接 Gmail/Outlook」
      → GET /mail/connect/{provider} 取得授權網址（本模組組出）
      → 使用者在 Google／Microsoft 官方畫面同意
      → callback 帶 code 回來 → exchange_code() 換到 refresh_token
      → 加密存進 mail_accounts
      → 之後每次抓信用 refresh_access_token() 換短效 access_token

授權碼流程（authorization code）刻意由後端完成，client_secret 只存在伺服器端；
手機從頭到尾拿不到任何信箱權杖，即使 App 被反編譯也偷不走信箱存取權。

注意 Google 的 refresh_token 只在「首次授權」或帶 prompt=consent 時才會發放，
因此授權網址一律帶 access_type=offline + prompt=consent，避免使用者重新連接時
換到一組沒有 refresh_token 的權杖（那會導致排程同步在 access_token 過期後失效）。
"""

import logging
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# 呼叫提供者權杖端點的逾時秒數
OAUTH_TIMEOUT = 15


class MailOAuthError(Exception):
    """信箱授權流程失敗。

    ⚠ 這個基底類別代表「**可能只是暫時性**的失敗」：連不上 Google／Microsoft、
    對方回 5xx、被限流（429）等等。呼叫端**不可**因為收到這個例外就把信箱連接
    停用——那會讓一次網路抖動變成使用者必須手動重跑一次完整 OAuth。
    確定不可恢復的情況請改判 `MailAuthRevokedError`。
    """


class MailProviderNotConfiguredError(MailOAuthError):
    """該提供者尚未於 .env 設定 client_id／client_secret。"""


class MailAuthRevokedError(MailOAuthError):
    """refresh_token 已確定失效，非重新授權不可恢復。

    只在提供者明確回報 `invalid_grant`（權杖遭撤銷、使用者改密碼、Google
    「Testing」發布狀態下 refresh_token 逾期七天）時才拋出。這是唯一該讓
    呼叫端停用信箱連接的情況。
    """


# 提供者用來表示「這個 grant 已經死了」的錯誤碼。
# Google 與 Microsoft identity platform 都以 invalid_grant 表達 refresh_token
# 遭撤銷／逾期；其餘錯誤碼（temporarily_unavailable、server_error…）皆屬暫時性。
REVOKED_ERROR_CODES = frozenset({"invalid_grant"})


@dataclass(frozen=True)
class ProviderConfig:
    """單一提供者的 OAuth 端點與參數設定。"""

    name: str  # gmail / outlook
    display_name: str
    authorize_url: str
    token_url: str
    scopes: tuple[str, ...]
    # 授權網址的額外參數（各家取得 refresh_token 的寫法不同）
    authorize_params: dict[str, str]
    # 權杖請求是否需要重送 scope（Microsoft 需要，Google 不需要）
    send_scope_on_token: bool


def _microsoft_endpoint(path: str) -> str:
    """組出對應租戶的 Microsoft identity platform 端點。"""
    return f"https://login.microsoftonline.com/{settings.OUTLOOK_TENANT}/oauth2/v2.0/{path}"


def get_provider_config(provider: str) -> ProviderConfig:
    """取得提供者設定。

    Raises:
        MailOAuthError: 不支援的提供者。
    """
    if provider == "gmail":
        return ProviderConfig(
            name="gmail",
            display_name="Gmail",
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            # gmail.readonly 為 restricted scope：只讀信、不能寄信或修改信箱。
            # 信箱位址改由 Gmail API 的 users.getProfile 取得，因此不另外要 userinfo scope。
            # gmail.settings.basic 供「真封鎖」建立／刪除過濾規則（Filters API），
            # 它只能改設定，讀不到、也寄不了任何一封信。
            # ⚠ 新增 scope 後，在此之前連接的使用者手上的權杖仍只有舊 scope：
            #   封鎖端點會回 403（MailPermissionError），需請使用者重新連接一次信箱。
            scopes=(
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.settings.basic",
            ),
            authorize_params={
                # offline + consent 才保證拿得到 refresh_token（見模組說明）
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
            },
            send_scope_on_token=False,
        )
    if provider == "outlook":
        return ProviderConfig(
            name="outlook",
            display_name="Outlook",
            authorize_url=_microsoft_endpoint("authorize"),
            token_url=_microsoft_endpoint("token"),
            # offline_access 才會發 refresh_token；User.Read 用來取回信箱位址
            scopes=(
                "offline_access",
                "https://graph.microsoft.com/Mail.Read",
                "https://graph.microsoft.com/User.Read",
            ),
            authorize_params={"response_mode": "query", "prompt": "consent"},
            send_scope_on_token=True,
        )
    raise MailOAuthError(f"不支援的信箱提供者：{provider}")


def get_client_credentials(provider: str) -> tuple[str, str]:
    """取得該提供者的 client_id / client_secret。

    Raises:
        MailProviderNotConfiguredError: .env 尚未設定該提供者的憑證。
    """
    if provider == "gmail":
        client_id, client_secret = settings.GMAIL_CLIENT_ID, settings.GMAIL_CLIENT_SECRET
        env_names = "GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET"
    elif provider == "outlook":
        client_id, client_secret = (
            settings.OUTLOOK_CLIENT_ID,
            settings.OUTLOOK_CLIENT_SECRET,
        )
        env_names = "OUTLOOK_CLIENT_ID / OUTLOOK_CLIENT_SECRET"
    else:
        raise MailOAuthError(f"不支援的信箱提供者：{provider}")

    if not client_id or not client_secret:
        raise MailProviderNotConfiguredError(
            f"尚未設定 {env_names}，無法連接{get_provider_config(provider).display_name}"
        )
    return client_id, client_secret


def build_redirect_uri(provider: str) -> str:
    """組出 OAuth 轉址網址。

    必須與 Google Cloud Console／Azure 應用程式註冊登記的「逐字相同」，
    差一個斜線都會被提供者拒絕（redirect_uri_mismatch）。
    """
    base = settings.MAIL_OAUTH_REDIRECT_BASE.rstrip("/")
    return f"{base}{settings.API_V1_PREFIX}/mail/callback/{provider}"


def build_authorize_url(provider: str, state: str) -> str:
    """組出使用者要前往的授權網址（App 以瀏覽器／Custom Tab 開啟）。"""
    config = get_provider_config(provider)
    client_id, _ = get_client_credentials(provider)

    params = {
        "client_id": client_id,
        "redirect_uri": build_redirect_uri(provider),
        "response_type": "code",
        "scope": " ".join(config.scopes),
        "state": state,
        **config.authorize_params,
    }
    return f"{config.authorize_url}?{urlencode(params)}"


@dataclass
class OAuthTokens:
    """自提供者換到的權杖組。"""

    access_token: str
    # Google 在未帶 prompt=consent 的重複授權時可能不回傳；刷新時通常也不回傳
    refresh_token: str | None
    expires_in: int


def _oauth_error_code(response: httpx.Response) -> str:
    """自權杖端點的錯誤回應取出 OAuth 錯誤碼（取不到時回空字串）。

    Google 與 Microsoft 都回 `{"error": "invalid_grant", "error_description": …}`，
    但兩家在超載時也可能回非 JSON 的 HTML 錯誤頁，因此解析失敗必須當成
    「未知錯誤」＝暫時性，不能誤判成權杖失效。
    """
    try:
        payload = response.json()
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("error") or "").strip().lower()


async def _post_token_request(config: ProviderConfig, data: dict[str, str]) -> dict:
    """呼叫提供者的權杖端點，回傳解析後的 JSON。

    Raises:
        MailAuthRevokedError: 提供者明確回報 invalid_grant（不可恢復）。
        MailOAuthError: 其餘一切失敗，一律視為暫時性（見類別說明）。
    """
    try:
        async with httpx.AsyncClient(timeout=OAUTH_TIMEOUT) as client:
            response = await client.post(config.token_url, data=data)
    except httpx.HTTPError as exc:
        # 連線失敗／逾時：Google 沒說權杖有問題，是我們打不到它
        raise MailOAuthError(
            f"無法連線到 {config.display_name} 權杖端點：{type(exc).__name__}"
        ) from exc

    if response.status_code != 200:
        # 提供者的錯誤原因在回應主體（invalid_grant、redirect_uri_mismatch 等），
        # 截斷後帶出來——否則排查授權問題時只看得到一個 400
        detail = response.text.strip()[:300] or "（回應主體為空）"
        message = (
            f"{config.display_name} 權杖端點回傳 HTTP {response.status_code}：{detail}"
        )
        if _oauth_error_code(response) in REVOKED_ERROR_CODES:
            raise MailAuthRevokedError(message)
        # 5xx、429、redirect_uri_mismatch、看不懂的回應……都不足以斷定權杖已死。
        # 誤判的代價是使用者被迫重跑 OAuth，比多重試幾輪嚴重得多。
        raise MailOAuthError(message)

    return response.json()


async def exchange_code(provider: str, code: str) -> OAuthTokens:
    """以授權碼換取權杖組（OAuth callback 時呼叫）。

    Raises:
        MailOAuthError: 授權碼無效、轉址網址不符或提供者回應異常。
    """
    config = get_provider_config(provider)
    client_id, client_secret = get_client_credentials(provider)

    data = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": build_redirect_uri(provider),
        "grant_type": "authorization_code",
    }
    if config.send_scope_on_token:
        data["scope"] = " ".join(config.scopes)

    payload = await _post_token_request(config, data)
    access_token = payload.get("access_token")
    if not access_token:
        raise MailOAuthError(f"{config.display_name} 未回傳 access_token")

    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        # 沒有 refresh_token 就無法在使用者關閉 App 後持續同步，等同這次連接失敗
        raise MailOAuthError(
            f"{config.display_name} 未回傳 refresh_token，無法建立長期連接。"
            "請在授權畫面完整同意所有權限後重試。"
        )

    return OAuthTokens(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=int(payload.get("expires_in", 3600)),
    )


async def refresh_access_token(provider: str, refresh_token: str) -> OAuthTokens:
    """以 refresh_token 換取短效 access_token（每次抓信前呼叫）。

    Microsoft 會在刷新時輪替 refresh_token（回傳新的一組），Google 通常不會；
    回傳的 `refresh_token` 若非 None，呼叫端必須把新值寫回資料庫，
    否則下次刷新會用到已作廢的舊權杖。

    Raises:
        MailAuthRevokedError: refresh_token 已失效（使用者撤銷授權、改密碼、
            Google Testing 狀態下逾期七天）——非重新授權不可恢復。
        MailOAuthError: 暫時性失敗（連不上、5xx、限流）——下一輪重試即可。
    """
    config = get_provider_config(provider)
    client_id, client_secret = get_client_credentials(provider)

    data = {
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
    }
    if config.send_scope_on_token:
        data["scope"] = " ".join(config.scopes)

    payload = await _post_token_request(config, data)
    access_token = payload.get("access_token")
    if not access_token:
        raise MailOAuthError(f"{config.display_name} 刷新權杖時未回傳 access_token")

    return OAuthTokens(
        access_token=access_token,
        refresh_token=payload.get("refresh_token"),  # 有輪替才會有值
        expires_in=int(payload.get("expires_in", 3600)),
    )
