"""信箱連接與信件判定結果的請求／回應 Schema。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.phone import RiskLevel

# 支援的信箱提供者
MailProvider = Literal["gmail", "outlook"]


class MailConnectResponse(BaseModel):
    """信箱授權網址（App 以瀏覽器／Custom Tab 開啟此網址）。"""

    provider: MailProvider
    authorize_url: str = Field(description="使用者要前往的提供者官方授權網址")
    expires_in_minutes: int = Field(description="此授權網址（state）的有效時間")


class MailAccountOut(BaseModel):
    """已連接的信箱帳號。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: MailProvider
    email_address: str
    is_active: bool
    connected_at: datetime
    last_synced_at: datetime | None = Field(
        default=None, description="上次成功同步時間；null 表示尚未同步過"
    )
    last_sync_error: str | None = Field(
        default=None, description="上次同步的錯誤訊息（成功時為 null）"
    )


class MailAccountsResponse(BaseModel):
    """已連接信箱列表。"""

    total: int
    items: list[MailAccountOut]


class MailMessageItem(BaseModel):
    """信件列表項目：判定結果來自資料庫，主旨／寄件者為即時取回。

    `subject` / `sender` / `preview` 不儲存於資料庫（見 app/models/mail.py 的
    設計說明），而是本次請求向 Gmail API／Graph API 取回的。若取回失敗
    （授權失效、配額用盡、提供者暫時無回應），這三欄為 null 且
    `preview_available` 為 false，判定結果仍可正常顯示。
    """

    id: int = Field(description="mail_analysis 紀錄 ID")
    provider: MailProvider
    message_id: str = Field(description="提供者端的信件 ID（App 可用於開啟原信）")
    received_at: datetime
    account_email: str = Field(description="這封信所屬的已連接信箱位址")

    # ----- 即時取回（不落地）-----
    subject: str | None = None
    sender: str | None = None
    preview: str | None = Field(default=None, description="信件開頭片段")
    preview_available: bool = Field(
        description="主旨／寄件者／預覽是否成功取回"
    )

    # ----- 資料庫中的判定結果 -----
    is_scam: bool
    risk_level: RiskLevel
    scam_type: str | None = None
    confidence: float = Field(ge=0, le=1)
    reasons: list[str]
    advice: str | None = None
    model: str = Field(description="判定來源：LLM 模型名稱或 similarity-gate")
    analyzed_at: datetime


class MailMessagesResponse(BaseModel):
    """信件列表回應（含分頁資訊）。"""

    total: int = Field(description="符合條件的總筆數（已分析的信件）")
    items: list[MailMessageItem]


class MailMessageContent(BaseModel):
    """單封信的完整內容（回報詐騙信時取用）。

    與列表端點一樣是即時向 Gmail API／Graph API 取回的 passthrough，後端不儲存；
    但這裡取回的是**完整內文**而非預覽片段，因為使用者按下「回報」時，這封信
    的全文就是要送進向量資料庫的證據本身。取不到內容時此端點回錯誤，
    不做列表那種「欄位留空、判定照常顯示」的降級——沒有內文的回報沒有意義。
    """

    id: int = Field(description="mail_analysis 紀錄 ID（與列表項目的 id 相同）")
    provider: MailProvider
    message_id: str = Field(description="提供者端的信件 ID")
    account_id: int = Field(description="這封信所屬的已連接信箱 ID")
    account_email: str = Field(description="這封信所屬的已連接信箱位址")
    received_at: datetime

    # ----- 即時取回（不落地）-----
    subject: str | None = None
    sender: str | None = None
    body: str | None = Field(
        default=None,
        description=(
            "信件純文字內文（HTML 信件已去標籤）。純附件或空信時為 null。"
            "長度上限為 MAIL_CONTENT_MAX_CHARS，超過即截斷並將 body_truncated 設為 true。"
        ),
    )
    body_truncated: bool = Field(
        default=False, description="內文是否因超過長度上限而被截斷"
    )
    report_text: str = Field(
        description=(
            "「寄件者 / 主旨 / 內文」組好的回報文字，可直接當作 POST /reports/full "
            "的 content 送出。寄件者與主旨一併帶入，是為了讓入庫的案例與偵測時"
            "看到的文字結構一致（詐騙信的破綻常在寄件網域與主旨）。"
        )
    )

    # ----- 資料庫中的判定結果（回報表單預填用）-----
    is_scam: bool
    risk_level: RiskLevel
    scam_type: str | None = Field(
        default=None, description="可作為回報表單「詐騙類型」的預設值"
    )


class MailSyncAccountResult(BaseModel):
    """單一信箱的同步結果。"""

    account_id: int
    provider: MailProvider
    email_address: str
    synced_since: datetime | None = Field(
        default=None,
        description=(
            "本次向提供者查詢的起點時間（UTC）。`fetched` 是 0 時先看這一欄："
            "它若接近現在，代表上次同步剛跑過、真的沒有新信；"
            "它若落在遙遠的過去或未來，就是增量游標出了問題。"
        ),
    )
    fetched: int = Field(description="自提供者列出的信件數（含重疊區間中已分析過的）")
    analyzed: int = Field(description="本次實際完成 AI 判斷並存檔的封數")
    skipped: int = Field(description="先前已分析過而略過的封數")
    error: str | None = Field(default=None, description="同步失敗的原因（成功為 null）")


class MailSyncResponse(BaseModel):
    """手動同步的整體結果。"""

    synced_at: datetime
    accounts: list[MailSyncAccountResult]


class MailDisconnectResponse(BaseModel):
    """中斷信箱連接的結果。"""

    message: str
    deleted_analyses: int = Field(description="一併刪除的判定紀錄筆數")


class MailBlockSenderRequest(BaseModel):
    """封鎖寄件人的請求。"""

    sender: str = Field(
        min_length=3,
        max_length=320,  # RFC 3696：local(64) + @ + domain(255)
        description=(
            "要封鎖的寄件人。可直接傳信件列表拿到的 From 原文"
            "（`顯示名稱 <bad@example.com>`），後端會取出其中的位址；"
            "顯示名稱不參與封鎖判斷，因為那是寄件人自己填的。"
        ),
    )


class MailBlockedSenderOut(BaseModel):
    """一筆寄件人封鎖紀錄。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    sender_address: str = Field(description="已正規化的寄件位址（小寫純位址）")
    provider_filter_id: str | None = Field(
        default=None, description="提供者端的過濾規則 ID（Gmail filter id）"
    )
    created_at: datetime


class MailBlockedSendersResponse(BaseModel):
    """某信箱的封鎖名單。"""

    total: int
    items: list[MailBlockedSenderOut]


class MailBlockSenderResponse(BaseModel):
    """封鎖／解除封鎖的結果。"""

    success: bool = True
    message: str
    sender_address: str = Field(description="實際套用的寄件位址（已正規化）")
