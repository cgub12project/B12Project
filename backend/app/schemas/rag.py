"""RAG（檢索增強生成）相關的請求／回應 Schema。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.phone import RiskLevel


class RagReportItem(BaseModel):
    """供 RAG Worker 入庫的使用者回報項目。"""

    source: Literal["phone_report", "fraud_report"] = Field(description="來源資料表")
    id: int = Field(description="來源資料表中的紀錄 ID")
    content: str = Field(description="回報內容（向量化的原文）")
    scam_type: str = Field(description="詐騙類型")
    created_at: datetime


class RagReportsResponse(BaseModel):
    """RAG Worker 輪詢回應：指定時間之後的新回報。"""

    server_time: datetime = Field(description="伺服器目前時間（供 Worker 記錄同步點）")
    count: int = Field(description="本次回傳筆數")
    items: list[RagReportItem]


class RagDetectRequest(BaseModel):
    """詐騙訊息偵測請求。"""

    message: str = Field(min_length=1, max_length=4000, description="要偵測的訊息內容")


class SimilarCase(BaseModel):
    """向量資料庫中相似度最高的歷史案例。"""

    content: str = Field(description="案例訊息內容")
    scam_type: str = Field(description="案例詐騙類型（一般訊息為「非詐騙」）")
    similarity: float = Field(ge=0, le=1, description="餘弦相似度（0-1，越高越相似）")
    is_scam: bool = Field(
        default=True,
        description="案例是否為詐騙訊息（早期入庫的向量無此標籤，預設視為詐騙）",
    )


class RagDetectResponse(BaseModel):
    """詐騙訊息偵測結果。"""

    is_scam: bool = Field(description="是否判定為詐騙訊息")
    risk_level: RiskLevel = Field(description="風險等級：high / mid / safe")
    scam_type: str | None = Field(default=None, description="判定的詐騙類型（非詐騙為 null）")
    confidence: float = Field(
        ge=0,
        le=1,
        description=(
            "判定信心值 0-1：模型對「這個判斷」的把握程度，不是詐騙機率。"
            "is_scam=false 時的高信心代表「很確定安全」，不可直接當風險條使用——"
            "要顯示風險程度請改用 risk_score"
        ),
    )
    risk_score: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description=(
            "校準後的詐騙機率 0-1（可直接當機率解讀、可跨判定來源比較與排序）。"
            "由評測結果擬合的校準表換算而得；校準表缺漏或與目前模型不符時為 null"
        ),
    )
    reasons: list[str] = Field(description="判定理由列表")
    advice: str | None = Field(default=None, description="給使用者的防詐建議")
    similar_cases: list[SimilarCase] = Field(
        description=(
            "檢索到的相似歷史案例（相似詐騙案例與相似正常訊息，各最多 3 筆）。"
            "只有在向量庫中找不到任何相似度超過顯示門檻的案例、或 RAG_ENABLED=false 時"
            "才會是空陣列"
        )
    )
    model: str = Field(
        description=(
            "做出判定的來源：LLM 模型名稱（如 gemma4），"
            "或 similarity-gate（相似度區間閘門直接判定，未呼叫 LLM）"
        )
    )


# ---------------------------------------------------------------------------
# 對話級偵測：詐騙階段
# ---------------------------------------------------------------------------

# 詐騙階段：順序即嚴重度，contact 最早、closing 最晚（中文名與嚴重度排序由
# app/services/stage_service.py 的 STAGES 定義，兩處一致性有測試把關）
ScamStage = Literal["contact", "grooming", "baiting", "extraction", "closing"]


class ConversationMessage(BaseModel):
    """對話中的一則訊息。"""

    sender: Literal["them", "me"] = Field(
        description="說話者：them 為可疑對象、me 為使用者本人"
    )
    text: str = Field(min_length=1, max_length=4000, description="訊息內容")
    sent_at: datetime | None = Field(default=None, description="發送時間（選填，僅供排序參考）")


class RagDetectConversationRequest(BaseModel):
    """對話級偵測請求：判斷詐騙與否，並判斷對話演進到哪個階段。

    對話狀態（previous_stage）由用戶端攜帶——後端不儲存任何對話內容，
    messages / message_threads 依系統規劃是 App 端 SQLite。
    """

    messages: list[ConversationMessage] = Field(
        min_length=1,
        description=(
            "依時間由舊到新排列的對話訊息。超過 RAG_STAGE_MAX_MESSAGES 則數"
            "或 RAG_STAGE_MAX_CHARS 字數時，由最舊的開始捨棄"
        ),
    )
    previous_stage: ScamStage | None = Field(
        default=None,
        description=(
            "此對話上一次判定的階段（由 App 保存並回傳）。"
            "用於單調性調和：模型只看得到最近數十則，"
            "視窗一旦滑過索取財物那幾則就會誤判成回退，帶上此欄位可擋掉"
        ),
    )


class RagDetectConversationResponse(RagDetectResponse):
    """對話級偵測結果：既有偵測欄位 + 詐騙階段。

    偵測欄位（is_scam / scam_type / risk_level / ...）來自對「最後一則對方訊息」
    的判定，與直接呼叫 /rag/detect 的結果一致。
    """

    stage: ScamStage | None = Field(
        default=None,
        description=(
            "詐騙階段；非詐騙且無 previous_stage 時為 null（此時不呼叫階段模型）"
        ),
    )
    stage_label: str | None = Field(
        default=None, description="階段的中文名稱（可直接顯示，如「索取財物」）"
    )
    stage_confidence: float | None = Field(
        default=None, ge=0, le=1, description="階段判定的信心值 0-1"
    )
    stage_reasons: list[str] = Field(
        default_factory=list, description="階段判定理由（引用對話中的具體話術）"
    )
    next_step_warning: str | None = Field(
        default=None, description="對方下一步最可能的行動（供提前提醒使用者）"
    )
    stage_model: str | None = Field(
        default=None,
        description=(
            "做出階段判定的來源：LLM 模型名稱（OLLAMA_STAGE_MODEL）／"
            "stage-rule（階段模型不可用，改由關鍵詞規則與前次階段推估）／"
            "stage-unavailable（階段模型不可用且無退路，stage 為 null）。"
            "非詐騙而未判階段時為 null——與 stage-unavailable 的差別是"
            "前者代表「不需要判」，後者代表「判不出來」"
        ),
    )
