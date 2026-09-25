"""電話號碼查詢／詳情的請求／回應 Schema。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 風險等級（README 風險三級制）
RiskLevel = Literal["high", "mid", "safe"]


class PhoneOut(BaseModel):
    """電話號碼列表項目（電話頁）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    phone_number: str
    risk_level: RiskLevel
    fraud_type: str | None = None
    report_count: int = Field(description="社群舉報次數")
    last_reported_at: datetime | None = None


class PhoneListResponse(BaseModel):
    """電話號碼列表回應（含分頁資訊）。"""

    total: int = Field(description="符合條件的總筆數")
    items: list[PhoneOut]


class PhoneCommunityReportOut(BaseModel):
    """電話詳情頁的社群回報項目（回報者身分經遮罩處理）。"""

    id: int
    fraud_type: str
    content: str
    reporter: str = Field(description="回報者名稱（已遮罩，例如「王**」）")
    created_at: datetime


class PhoneDetailResponse(BaseModel):
    """電話詳情回應：號碼資訊 + 社群回報列表。"""

    id: int
    phone_number: str
    risk_level: RiskLevel
    fraud_type: str | None = None
    report_count: int
    last_reported_at: datetime | None = None
    created_at: datetime
    reports: list[PhoneCommunityReportOut] = Field(description="社群回報列表（新到舊）")
