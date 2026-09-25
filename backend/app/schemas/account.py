"""可疑帳號（帳號威脅檔案）的回應 Schema。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.phone import RiskLevel


class SuspectAccountOut(BaseModel):
    """可疑帳號列表項目。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    platform: str
    account_name: str
    external_account_id: str | None = None
    risk_score: int = Field(ge=0, le=100, description="風險評分 0-100")
    risk_level: RiskLevel
    report_count: int
    last_reported_at: datetime | None = None


class SuspectAccountListResponse(BaseModel):
    """可疑帳號列表回應（含分頁資訊）。"""

    total: int
    items: list[SuspectAccountOut]


class EvidenceItemOut(BaseModel):
    """證據摘要項目（帳號威脅檔案）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    evidence_type: str = Field(description="證據類型")
    severity: str = Field(description="嚴重度：high / mid / low")
    description: str
    occurred_at: datetime | None = Field(default=None, description="時間標記")


class SuspectAccountDetailResponse(BaseModel):
    """帳號威脅檔案回應：風險環形圖 + 觸發規則 + 證據摘要。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    platform: str
    account_name: str
    external_account_id: str | None = None
    risk_score: int = Field(ge=0, le=100, description="風險評分（環形圖 0-100）")
    risk_level: RiskLevel
    report_count: int
    triggered_rules: list[str] = Field(description="觸發規則標籤列表")
    ai_summary: str | None = Field(default=None, description="AI 威脅摘要")
    last_reported_at: datetime | None = None
    created_at: datetime
    evidence_items: list[EvidenceItemOut] = Field(description="證據摘要列表")
