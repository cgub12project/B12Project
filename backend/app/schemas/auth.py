"""認證相關的請求／回應 Schema。"""

from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from app.schemas.user import UserOut


# ============================================================
# 請求
# ============================================================

class RegisterRequest(BaseModel):
    """註冊請求。"""

    email: EmailStr = Field(description="Email（登入帳號）")
    password: str = Field(min_length=8, max_length=72, description="密碼（至少 8 碼）")
    name: str = Field(min_length=1, max_length=100, description="顯示名稱")


class LoginRequest(BaseModel):
    """登入請求。"""

    email: EmailStr = Field(description="Email")
    password: str = Field(description="密碼")


class ForgotPasswordRequest(BaseModel):
    """忘記密碼：發送 OTP 請求。"""

    email: EmailStr = Field(description="註冊時使用的 Email")


class VerifyOtpRequest(BaseModel):
    """驗證 6 位數 OTP 請求。"""

    email: EmailStr = Field(description="Email")
    otp: str = Field(pattern=r"^\d{6}$", description="6 位數 OTP 驗證碼")


class ResetPasswordRequest(BaseModel):
    """重設密碼請求（需先通過 OTP 驗證取得 reset_token）。"""

    reset_token: str = Field(description="verify-otp 成功後取得的一次性重設權杖")
    new_password: str = Field(min_length=8, max_length=72, description="新密碼（至少 8 碼）")


class OAuthRequest(BaseModel):
    """社交登入請求。

    - Google：傳入 Credential Manager 取得的 `id_token`
    - Facebook：傳入 OAuth 取得的 `access_token`
    """

    provider: Literal["google", "facebook"] = Field(description="社交登入提供者")
    id_token: str | None = Field(default=None, description="Google ID Token")
    access_token: str | None = Field(default=None, description="Facebook Access Token")


class RefreshTokenRequest(BaseModel):
    """換發權杖請求。"""

    refresh_token: str = Field(description="有效的 refresh_token")


class ChangePasswordRequest(BaseModel):
    """更改密碼請求（設定頁，需登入）。"""

    old_password: str = Field(description="目前密碼")
    new_password: str = Field(min_length=8, max_length=72, description="新密碼（至少 8 碼）")


# ============================================================
# 回應
# ============================================================

class TokenResponse(BaseModel):
    """登入／註冊／OAuth／換發成功回應：JWT 權杖組。"""

    access_token: str = Field(description="存取權杖（API 認證用）")
    refresh_token: str = Field(description="更新權杖（換發新權杖用）")
    token_type: str = Field(default="bearer", description="權杖類型")
    expires_in: int = Field(description="access_token 有效秒數")
    user: UserOut = Field(description="使用者資料")


class MessageResponse(BaseModel):
    """通用訊息回應。"""

    success: bool = Field(default=True, description="是否成功")
    message: str = Field(description="說明訊息")


class VerifyOtpResponse(BaseModel):
    """OTP 驗證成功回應。"""

    success: bool = Field(default=True)
    message: str = Field(description="說明訊息")
    reset_token: str = Field(description="一次性重設權杖（用於 reset-password）")
