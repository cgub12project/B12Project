"""詐騙階段判定服務（對話級）。

回答的是偵測管線不回答的第三個問題：這段對話**演進到哪一個階段**。
詐騙類型說的是「這是什麼手法」，階段說的是「你現在有多危險、對方下一步要做什麼」——
同一段假投資對話，在「培養信任」只需要提醒，到了「索取財物」就該擋下匯款。

為什麼是獨立的第二段判定，而不是在偵測的 prompt 上多加一個欄位：

1. app/prompts/scam_detection_system.txt 是微調模型的訓練契約，推論輸入必須與
   data/finetune.jsonl 逐字一致（實測過在推論端加料反而掉分，見 test_rag.py 的
   test_prompt_has_no_extra_guidance_beyond_finetune_contract）。
2. 一致性閘門在最相似的 N 筆一面倒時完全不呼叫 LLM，那條路徑產不出階段。
3. 階段是「對話」的屬性，偵測管線的輸入是單則訊息。

判定流程（StageService.classify）：
1. 取最近的 RAG_STAGE_MAX_MESSAGES 則 / RAG_STAGE_MAX_CHARS 字（由最舊的捨棄）
2. 關鍵詞規則掃出一個階段「下界」（只掃對方的訊息）
3. 以專屬 system prompt + Ollama structured outputs 取得模型判定
4. 單調性調和：低信心的回退不予採信（詐騙腳本幾乎不倒退）
5. 取「下界」與「調和後結果」的較高者

本服務不儲存任何對話內容——對話狀態（previous_stage）由用戶端攜帶。
"""

import json
import logging
import re
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.schemas.rag import ConversationMessage, ScamStage
from app.services import ollama_client

logger = logging.getLogger(__name__)

# 階段判定的 system prompt（五階段定義 + 判斷規則 + 輸出契約）
_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "scam_stage_system.txt"
STAGE_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")

# 五階段：順序即嚴重度，索引越大越晚期、越危險。
# 對外用英文 slug（schemas.rag.ScamStage），對模型與使用者用中文名。
STAGES: tuple[tuple[str, str], ...] = (
    ("contact", "接觸建立"),
    ("grooming", "培養信任"),
    ("baiting", "鋪陳誘餌"),
    ("extraction", "索取財物"),
    ("closing", "收尾拖延"),
)
STAGE_SLUGS: tuple[str, ...] = tuple(slug for slug, _ in STAGES)
STAGE_LABELS: dict[str, str] = {slug: label for slug, label in STAGES}
STAGE_BY_LABEL: dict[str, str] = {label: slug for slug, label in STAGES}
STAGE_INDEX: dict[str, int] = {slug: index for index, slug in enumerate(STAGE_SLUGS)}

# 階段名稱以 prompt 為單一事實來源（同 rag_service 的 SCAM_TYPES）：兩處各自維護
# 必然走樣——prompt 改了名稱、程式碼沒改，模型輸出的中文名就對不回任何 slug。
_PROMPT_STAGE_LABELS = re.findall(r"^\d+\.\s*([^：\n]+)：", STAGE_SYSTEM_PROMPT, re.MULTILINE)
if _PROMPT_STAGE_LABELS != [label for _, label in STAGES]:  # pragma: no cover
    raise RuntimeError(
        f"階段 prompt 解析出的階段名稱 {_PROMPT_STAGE_LABELS} 與 STAGES 不一致："
        "請確認【詐騙階段五階段】的編號格式與名稱未被改動"
    )

# 階段判定的輸出欄位鍵序（中文鍵，與偵測那條線的風格一致）
STAGE_KEY_ORDER = ["詐騙階段", "階段判斷理由", "下一步預測", "階段可信度評分"]

# 傳給 Ollama 的 format（structured outputs）：解碼階段就鎖死階段名稱的 enum，
# 模型無法自創「取得信任期」這種對不回 slug 的名字
STAGE_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "詐騙階段": {"type": "string", "enum": [label for _, label in STAGES]},
        "階段判斷理由": {"type": "string"},
        "下一步預測": {"type": "string"},
        "階段可信度評分": {"type": "integer", "minimum": 0, "maximum": 100},
    },
    "required": STAGE_KEY_ORDER,
}

# 階段由關鍵詞規則決定（模型不可用但規則有意見）時，回應 stage_model 的識別名稱
STAGE_RULE_MODEL = "stage-rule"

# 階段模型不可用且無退路時，回應 stage_model 的識別名稱。stage 會是 null——
# 但與「非詐騙所以不判階段」（stage_model 亦為 null）必須分得開，否則
# OLLAMA_STAGE_MODEL 指到一顆沒 pull 的模型時，外部看到的是「所有對話都沒有階段」。
STAGE_UNAVAILABLE_MODEL = "stage-unavailable"

# 關鍵詞規則的「階段下界」。只作為下界、不覆蓋模型往上判的結果，概念同相似度閘門的短路：
# 便宜、確定，補的是小模型把「請匯款到這個帳號」判成「培養信任」這種漏判。
#
# 收錄標準是高精確度——寧可漏，不可錯。刻意排除的例子：
# - 「帳號」：使用者互留 LINE 帳號時也會出現，是接觸階段的正常行為
# - 「保證金」：六合彩／假推銷詐騙一開口就要保證金，那是索取而非收尾
# 誤判的方向是把階段往上抬（多一次警示），這在防詐情境下比漏抬安全。
_EXTRACTION_PATTERNS = (
    r"匯款|匯到|匯過去|先匯|轉帳|轉到這個",
    # 「入金」與收尾拖延的「出金」是一對，漏掉它等於假投資詐騙最典型的
    # 索取話術（「先入金六萬我教你下單」）判不出來。由 test_stage_data.py 抓到。
    r"入金|儲值",
    r"提款卡|金融卡|存摺|存簿",
    r"驗證碼|簡訊碼|OTP",
    r"遊戲點數|點數卡|禮品卡|儲值卡|MyCard",
    r"超商代碼|代碼繳費",
    r"ATM|網路銀行|網銀",
    r"收款帳號|指定帳戶|監管帳戶|安全帳戶",
    r"卡號|末三碼|安全碼",
    r"身分證正反面|證件照|證件正反面",
    r"面交",
)
_CLOSING_PATTERNS = (
    r"出金",
    r"解凍",
    r"補繳|再匯|補匯|加碼匯",
    r"追回|追討|協助追款",
)
_RULE_FLOORS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # 由高階段往低階段檢查，命中即停
    ("closing", _CLOSING_PATTERNS),
    ("extraction", _EXTRACTION_PATTERNS),
)


def _flatten(text: str) -> str:
    """把訊息壓成單行：對話以「一則一行」餵給模型，內含換行會打亂行首的說話者標記。"""
    return re.sub(r"\s+", " ", text).strip()


def trim_conversation(
    messages: list[ConversationMessage],
) -> list[ConversationMessage]:
    """截出進入提示詞的對話視窗：保留最近的訊息，由最舊的開始捨棄。

    兩個上限（則數 RAG_STAGE_MAX_MESSAGES、總字數 RAG_STAGE_MAX_CHARS）取較嚴者。
    至少保留最後一則，否則長訊息會把整個視窗清空。
    """
    window = messages[-settings.RAG_STAGE_MAX_MESSAGES :]

    total = sum(len(message.text) for message in window)
    while len(window) > 1 and total > settings.RAG_STAGE_MAX_CHARS:
        total -= len(window[0].text)
        window = window[1:]

    return window


def rule_floor(messages: list[ConversationMessage]) -> ScamStage | None:
    """以關鍵詞掃出階段下界；沒有命中則回 None。

    只掃「對方」的訊息——使用者自己說「我不會匯款給你」不代表對方索取過。
    """
    counterpart_text = " ".join(
        message.text for message in messages if message.sender == "them"
    )
    if not counterpart_text:
        return None

    for stage, patterns in _RULE_FLOORS:
        if any(re.search(pattern, counterpart_text, re.IGNORECASE) for pattern in patterns):
            return stage  # type: ignore[return-value]
    return None


def reconcile(
    previous: ScamStage | None, predicted: ScamStage, confidence: float
) -> ScamStage:
    """單調性調和：低信心的回退不予採信。

    詐騙腳本幾乎不會倒退，但模型只看得到最近數十則——視窗一旦把「先匯 30000」
    那幾則滑掉，它就會退回「培養信任」，使用者眼中就是風險自己降下來了。
    只有信心達 RAG_STAGE_REGRESS_CONFIDENCE 的回退才採信（例如對話確實換了主題）。
    """
    if previous is None or STAGE_INDEX[predicted] >= STAGE_INDEX[previous]:
        return predicted
    if confidence >= settings.RAG_STAGE_REGRESS_CONFIDENCE:
        return predicted
    return previous


def _higher(left: ScamStage | None, right: ScamStage | None) -> ScamStage | None:
    """取兩個階段中較晚（較嚴重）的一個；None 視為沒有意見。"""
    if left is None:
        return right
    if right is None:
        return left
    return left if STAGE_INDEX[left] >= STAGE_INDEX[right] else right


class StageVerdict:
    """階段判定結果（對應 RagDetectConversationResponse 的 stage_* 欄位）。"""

    __slots__ = ("stage", "confidence", "reasons", "next_step_warning", "model")

    def __init__(
        self,
        *,
        stage: ScamStage,
        confidence: float,
        reasons: list[str],
        next_step_warning: str | None,
        model: str,
    ) -> None:
        self.stage = stage
        self.confidence = confidence
        self.reasons = reasons
        self.next_step_warning = next_step_warning
        self.model = model

    @property
    def label(self) -> str:
        return STAGE_LABELS[self.stage]


class StageUnavailableError(Exception):
    """階段判定不可用（階段模型連線／推論失敗，且無規則或前次階段可退回）。"""


class StageService:
    """詐騙階段判定服務（無狀態；對話由呼叫端提供，不落地）。"""

    @staticmethod
    def model_name() -> str:
        """判階段實際使用的模型：未設定 OLLAMA_STAGE_MODEL 時沿用偵測模型。"""
        return settings.OLLAMA_STAGE_MODEL or settings.OLLAMA_MODEL

    @staticmethod
    def format_user_prompt(
        messages: list[ConversationMessage], scam_type: str | None
    ) -> str:
        """組裝 user 訊息：（選填的已知詐騙類型）+ 一則一行的對話。"""
        lines: list[str] = []
        if scam_type:
            lines += [f"【已知詐騙類型】{scam_type}", ""]

        lines.append("【對話內容】")
        for message in messages:
            speaker = "對方" if message.sender == "them" else "我"
            lines.append(f"[{speaker}] {_flatten(message.text)}")

        return "\n".join(lines)

    @classmethod
    def build_prompt(
        cls, messages: list[ConversationMessage], scam_type: str | None
    ) -> list[dict[str, str]]:
        """組裝送給階段模型的對話提示詞。"""
        return [
            {"role": "system", "content": STAGE_SYSTEM_PROMPT},
            {"role": "user", "content": cls.format_user_prompt(messages, scam_type)},
        ]

    @staticmethod
    def parse_response(raw: str) -> dict[str, Any] | None:
        """解析階段模型的中文鍵 JSON 回應；無法解析時回 None（由呼叫端決定退路）。

        映射：詐騙階段（中文名）→ stage slug、階段可信度評分 0-100 → confidence 0-1、
        階段判斷理由 → reasons、下一步預測 → next_step_warning。
        """
        parsed: dict[str, Any] | None = None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                except json.JSONDecodeError:
                    parsed = None

        if not isinstance(parsed, dict):
            return None

        label = str(parsed.get("詐騙階段", "")).strip()
        stage = STAGE_BY_LABEL.get(label)
        if stage is None:
            # 保險層：schema 的 enum 已在解碼階段擋掉，此路徑只在 Ollama 版本過舊
            # 或換推論後端時走到。對不回 slug 就等於沒有判定，不猜。
            logger.warning("階段模型回傳未知的階段名稱：%r", label)
            return None

        score_raw = parsed.get("階段可信度評分", 0)
        try:
            score = float(score_raw)
            if 0.0 < score <= 1.0:
                score *= 100.0  # 少數情況模型誤填 0-1 小數
            score = max(0.0, min(100.0, score))
        except (TypeError, ValueError):
            score = 50.0

        reason = parsed.get("階段判斷理由")
        warning = parsed.get("下一步預測")

        return {
            "stage": stage,
            "confidence": round(score / 100.0, 4),
            "reasons": [str(reason)] if reason and str(reason).strip() else [],
            "next_step_warning": (
                str(warning) if warning and str(warning).strip() else None
            ),
        }

    async def classify(
        self,
        messages: list[ConversationMessage],
        *,
        scam_type: str | None = None,
        previous_stage: ScamStage | None = None,
    ) -> StageVerdict:
        """判斷這段對話目前的詐騙階段。

        Raises:
            StageUnavailableError: 階段模型不可用，且關鍵詞規則與 previous_stage
                都沒有意見（此時沒有任何依據可回，不猜一個階段給使用者）。
        """
        window = trim_conversation(messages)
        floor = rule_floor(window)

        try:
            raw = await ollama_client.chat(
                self.build_prompt(window, scam_type),
                base_url=settings.OLLAMA_BASE_URL,
                model=self.model_name(),
                timeout=settings.OLLAMA_TIMEOUT,
                response_schema=STAGE_RESPONSE_SCHEMA,
                think=settings.OLLAMA_STAGE_THINK,
            )
            verdict = self.parse_response(raw)
        except ollama_client.OllamaError as exc:
            logger.warning("階段模型不可用，改由關鍵詞規則／前次階段決定：%s", exc)
            verdict = None

        if verdict is None:
            # 退路：規則地板或前次階段。兩者皆無就代表真的什麼都不知道。
            fallback = _higher(floor, previous_stage)
            if fallback is None:
                raise StageUnavailableError(
                    "階段模型不可用，且對話中沒有可據以判定階段的關鍵詞"
                )
            return StageVerdict(
                stage=fallback,
                confidence=0.3,
                reasons=["階段模型無法判定，依關鍵詞規則與前次階段推估"],
                next_step_warning=None,
                model=STAGE_RULE_MODEL,
            )

        stage = _higher(floor, reconcile(previous_stage, verdict["stage"], verdict["confidence"]))
        assert stage is not None  # verdict["stage"] 必不為 None，僅為型別收斂

        return StageVerdict(
            stage=stage,
            confidence=verdict["confidence"],
            reasons=verdict["reasons"],
            next_step_warning=verdict["next_step_warning"],
            model=self.model_name(),
        )


# 全域單例（無狀態，純為與 get_rag_service 的相依性寫法一致）
stage_service = StageService()


def get_stage_service() -> StageService:
    """FastAPI 相依性：取得階段判定服務單例（測試時可覆寫）。"""
    return stage_service
