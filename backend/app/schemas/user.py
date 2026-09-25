"""使用者資料與設定的請求／回應 Schema。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserOut(BaseModel):
    """使用者公開資料（回應用）。"""

    model_config = ConfigDict(from_attributes=True)  # 允許直接由 ORM 物件轉換

    id: int
    email: EmailStr
    name: str
    avatar_url: str | None = None
    email_verified: bool
    created_at: datetime


class UserUpdateRequest(BaseModel):
    """更新個人資料請求（僅允許修改名稱與頭像）。"""

    name: str | None = Field(default=None, min_length=1, max_length=100, description="顯示名稱")
    avatar_url: str | None = Field(default=None, max_length=500, description="頭像 URL")


class UserSettingsOut(BaseModel):
    """使用者設定回應（對應設定頁 6 個開關）。"""

    model_config = ConfigDict(from_attributes=True)

    message_monitoring: bool = Field(description="訊息監控")
    email_scanning: bool = Field(description="郵件掃描")
    call_detection: bool = Field(description="來電辨識")
    quick_login: bool = Field(description="快速登入（生物辨識）")
    high_risk_alert: bool = Field(description="高危警報")
    daily_report: bool = Field(description="每日安全報告")
    updated_at: datetime


class UserSettingsUpdateRequest(BaseModel):
    """更新使用者設定請求（僅傳入要變更的欄位即可）。"""

    message_monitoring: bool | None = None
    email_scanning: bool | None = None
    call_detection: bool | None = None
    quick_login: bool | None = None
    high_risk_alert: bool | None = None
    daily_report: bool | None = None
