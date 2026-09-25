"""詐騙回報的請求／回應 Schema。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# 帳號回報支援的平台。
# 前 5 種為 MessageReportBottomSheet 的社群平台；"Gmail" 是信箱功能的寄件人回報，
# 此時 account_name 帶的是寄件者的真實 email 位址——由信箱連接讀回來的 From 標頭，
# 不像 LINE 顯示名稱可能重複，所以不會有「同名不同人被合併成同一個可疑帳號」的問題。
# （日後要支援 Outlook 寄件人回報，加上 "Outlook" 即可，其餘邏輯共用。）
Platform = Literal["LINE", "Facebook", "Instagram", "WhatsApp", "Telegram", "Gmail"]


class PhoneReportRequest(BaseModel):
    """電話號碼回報請求（README：PhoneReportRequest）。"""

    fraud_type: str = Field(
        min_length=1, max_length=50, description="詐騙類型（7 種預設之一，或自訂）"
    )
    content: str = Field(min_length=10, description="回報內容（至少 10 字）")
    description: str | None = Field(default=None, description="補充說明")


class MessageReportBody(BaseModel):
    """帳號回報請求（README：MessageReportBody）。"""

    fraud_type: str = Field(min_length=1, max_length=50, description="詐騙類型")
    content: str = Field(min_length=10, description="回報內容（至少 10 字）")
    platform: Platform = Field(description="平台")
    account_name: str = Field(min_length=1, max_length=100, description="帳號名稱")
    account_id: str | None = Field(default=None, max_length=100, description="帳號 ID（選填）")
    description: str | None = Field(default=None, description="補充說明")


class FullReportRequest(BaseModel):
    """完整回報請求（ReportFullActivity：詐騙類型 + 附加證據 + 事件描述）。"""

    fraud_type: str = Field(min_length=1, max_length=50, description="詐騙類型")
    content: str = Field(min_length=10, description="事件描述（至少 10 字）")
    description: str | None = Field(default=None, description="補充說明")
    evidence_files: list[str] | None = Field(
        default=None, description="附加證據檔案 URL 列表"
    )


class ReportSubmitResponse(BaseModel):
    """回報提交成功回應。"""

    success: bool = True
    message: str = Field(description="說明訊息")
    report_id: int = Field(description="回報紀錄 ID")
    case_number: str | None = Field(
        default=None, description="案件編號（帳號回報／完整回報時提供）"
    )


class MyReportItem(BaseModel):
    """個人回報紀錄項目（合併電話／帳號／完整回報）。"""

    id: int
    kind: Literal["phone", "account", "full"] = Field(description="回報種類")
    fraud_type: str
    content: str
    target: str = Field(description="回報對象（電話號碼或「平台/帳號」；完整回報為 —）")
    case_number: str | None = Field(default=None, description="案件編號（電話回報無）")
    status: str = Field(description="審核狀態：pending / approved / rejected")
    created_at: datetime


class MyReportsResponse(BaseModel):
    """個人回報紀錄回應。"""

    total: int
    items: list[MyReportItem]
