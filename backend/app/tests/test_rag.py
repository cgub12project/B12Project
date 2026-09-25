"""RAG 端點測試。

偵測端點以假的 RagService 取代（不載入 BGE-M3 / Ollama），
回報查詢端點驗證 X-API-Key 與 since 篩選行為；
另含相似度區間閘門、風險分數校準，以及對話級詐騙階段判定的單元測試
（皆以替身取代檢索與 LLM 呼叫）。
"""

import json
import re

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.main import app
from app.schemas.rag import ConversationMessage, RagDetectResponse, SimilarCase
from app.services import ollama_client
from app.services.rag_service import (
    DETECT_RESPONSE_SCHEMA,
    NORMAL_TYPE,
    SCAM_TYPES,
    SIMILARITY_GATE_MODEL,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_NO_RAG,
    RagService,
    _apply_calibrated_risk_level,
    get_rag_service,
)
from app.services.risk_calibration import CALIBRATION_PATH, RiskCalibrator
from app.services.stage_service import (
    STAGE_RESPONSE_SCHEMA,
    STAGE_RULE_MODEL,
    STAGE_SYSTEM_PROMPT,
    STAGE_UNAVAILABLE_MODEL,
    STAGES,
    StageService,
    StageUnavailableError,
    StageVerdict,
    get_stage_service,
    reconcile,
    rule_floor,
    trim_conversation,
)


class FakeRagService:
    """測試替身：回傳固定的偵測結果。"""

    async def detect(self, message: str) -> RagDetectResponse:
        return RagDetectResponse(
            is_scam=True,
            risk_level="high",
            scam_type="投資詐騙",
            confidence=0.92,
            reasons=["假獲利保證", "引導加入群組"],
            advice="請勿依對方指示匯款。",
            similar_cases=[
                SimilarCase(content="保證獲利投資群組", scam_type="投資詐騙", similarity=0.91)
            ],
            model="gemma4",
        )


async def test_detect_scam(client: AsyncClient, auth_headers: dict):
    """偵測端點：需登入，回傳結構化判斷結果。"""
    app.dependency_overrides[get_rag_service] = lambda: FakeRagService()
    try:
        # 未登入 → 401
        response = await client.post(
            "/api/v1/rag/detect", json={"message": "保證獲利，快加入投資群組"}
        )
        assert response.status_code == 401

        # 登入後偵測
        response = await client.post(
            "/api/v1/rag/detect",
            json={"message": "保證獲利，快加入投資群組"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["is_scam"] is True
        assert body["risk_level"] == "high"
        assert len(body["similar_cases"]) == 1
    finally:
        app.dependency_overrides.pop(get_rag_service, None)


async def test_rag_reports_feed(client: AsyncClient, auth_headers: dict):
    """RAG 回報查詢端點：X-API-Key 驗證與新回報回傳。"""
    # 錯誤金鑰 → 401
    response = await client.get(
        "/api/v1/rag/reports", headers={"X-API-Key": "wrong-key"}
    )
    assert response.status_code == 401

    # 尚無回報 → 空列表
    valid_headers = {"X-API-Key": settings.RAG_API_KEY}
    response = await client.get("/api/v1/rag/reports", headers=valid_headers)
    assert response.status_code == 200
    assert response.json()["count"] == 0

    # 建立一筆電話回報與一筆帳號回報
    await client.post(
        "/api/v1/reports/phone/0911222333",
        json={"fraud_type": "釣魚簡訊", "content": "假冒電信公司要求點擊繳費連結"},
        headers=auth_headers,
    )
    await client.post(
        "/api/v1/reports/account",
        json={
            "fraud_type": "交友詐騙",
            "content": "交友軟體認識後誘導投資虛擬貨幣",
            "platform": "Instagram",
            "account_name": "sweet_anna",
        },
        headers=auth_headers,
    )

    # 兩筆回報皆可供 RAG 入庫（含 content 與 scam_type）
    response = await client.get("/api/v1/rag/reports", headers=valid_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    sources = {item["source"] for item in body["items"]}
    assert sources == {"phone_report", "fraud_report"}
    assert all(item["content"] and item["scam_type"] for item in body["items"])

    # since 設為未來時間 → 無資料
    response = await client.get(
        "/api/v1/rag/reports",
        params={"since": "2099-01-01T00:00:00"},
        headers=valid_headers,
    )
    assert response.json()["count"] == 0


# ------------------------------------------------------------
# 一致性閘門（RagService.detect 單元測試，不需 BGE-M3 / Ollama）
# ------------------------------------------------------------

# 假 LLM 回應採 fine_tune.jsonl 的中文欄位鍵。可信度評分 66 在舊規則下推導為 mid；
# 現在 risk_level 改由校準後的 risk_score 決定（見 _apply_calibrated_risk_level）
_LLM_REPLY = json.dumps(
    {
        "是否為詐騙": "是",
        "詐騙類別": "假投資詐騙",
        "分析原因": "出現保證獲利話術。",
        "防詐建議": "請先向 165 反詐騙專線查證。",
        "可信度評分": 66,
    },
    ensure_ascii=False,
)


def _make_cases(
    *similarities: float, is_scam: bool = True, count: int | None = None
) -> list[SimilarCase]:
    """建立檢索結果替身（依序即 top-1、top-2…）。

    閘門看的是「最相似的 N 筆」，所以測試必須能精確控制每一筆的相似度，
    不能只給一個 top-1 再讓其餘自動遞減——舊版那樣寫的話，「第 N 名剛好
    掉到門檻以下」這個案例根本測不出來。

    count 用於一次產生 N 筆相同相似度的候選（測「票數剛好湊齊」時方便）。
    """
    if count is not None:
        similarities = tuple(similarities[0] for _ in range(count))
    label = "投資詐騙" if is_scam else "非詐騙"
    return [
        SimilarCase(
            content=f"案例{i}", scam_type=label, similarity=sim, is_scam=is_scam
        )
        for i, sim in enumerate(similarities, start=1)
    ]


# 預設的待測訊息刻意超過 RAG_GATE_SHORT_MESSAGE_CHARS（20 字），讓一般閘門測試
# 不會意外落入短訊息規則；短訊息規則另有專屬測試。
_LONG_MESSAGE = "您好，您的包裹因地址不完整無法配送，請於今日內更新收件資料以免退回"


async def _detect_with_cases(
    monkeypatch, cases: list[SimilarCase], message: str = _LONG_MESSAGE
) -> tuple[RagDetectResponse, bool]:
    """以假的檢索結果執行 RagService.detect，回傳（偵測結果, 是否呼叫了 LLM）。"""
    service = RagService()
    llm_called = False

    async def fake_ask_ollama(messages):
        nonlocal llm_called
        llm_called = True
        return _LLM_REPLY

    # 以替身取代「嵌入＋向量檢索」與「LLM 呼叫」，只驗證閘門邏輯本身
    monkeypatch.setattr(service, "_query_similar_sync", lambda message: cases)
    monkeypatch.setattr(service, "_ask_ollama", fake_ask_ollama)
    result = await service.detect(message)
    return result, llm_called


async def test_gate_unanimous_scam_returns_high(monkeypatch):
    """最相似的 N 筆全部超過門檻且全是詐騙 → 直接判定 high，不呼叫 LLM。"""
    monkeypatch.setattr(settings, "RAG_GATE_TOP_N", 3)
    monkeypatch.setattr(settings, "RAG_GATE_SIMILARITY", 0.35)

    cases = _make_cases(0.72, 0.68, 0.61, is_scam=True)
    result, llm_called = await _detect_with_cases(monkeypatch, cases)

    assert llm_called is False
    assert result.is_scam is True
    assert result.risk_level == "high"
    assert result.scam_type == "投資詐騙"  # 取最相似案例的詐騙類型
    assert result.model == SIMILARITY_GATE_MODEL
    assert result.confidence == 0.72  # confidence 取 top-1 相似度（校準表依此擬合）


async def test_gate_unanimous_normal_returns_safe(monkeypatch):
    """最相似的 N 筆全部超過門檻且全是一般訊息 → 直接判定 safe，不呼叫 LLM。"""
    monkeypatch.setattr(settings, "RAG_GATE_TOP_N", 3)
    monkeypatch.setattr(settings, "RAG_GATE_SIMILARITY", 0.35)

    cases = _make_cases(0.66, 0.64, 0.58, is_scam=False)
    result, llm_called = await _detect_with_cases(monkeypatch, cases)

    assert llm_called is False
    assert result.is_scam is False
    assert result.risk_level == "safe"
    assert result.scam_type is None
    assert result.model == SIMILARITY_GATE_MODEL


async def test_gate_conflict_uses_llm(monkeypatch):
    """N 筆之中兩類並存 → 模糊地帶，交由 LLM，不直接判定。"""
    monkeypatch.setattr(settings, "RAG_GATE_TOP_N", 3)
    monkeypatch.setattr(settings, "RAG_GATE_SIMILARITY", 0.35)

    cases = [
        SimilarCase(content="正常訊息", scam_type="非詐騙", similarity=0.70, is_scam=False),
        SimilarCase(content="保證獲利", scam_type="投資詐騙", similarity=0.68, is_scam=True),
        SimilarCase(content="正常訊息2", scam_type="非詐騙", similarity=0.66, is_scam=False),
    ]
    result, llm_called = await _detect_with_cases(monkeypatch, cases)

    assert llm_called is True
    assert result.model == settings.OLLAMA_MODEL


async def test_gate_requires_every_voter_above_threshold(monkeypatch):
    """只要 N 筆之中有一筆沒超過門檻（含等於）→ 交由 LLM。

    ★ 這是新閘門與舊閘門最關鍵的行為差異，也是舊版最大的漏洞：舊規則只看
      top-1，一個孤立的高相似鄰居就能帶著後面幾個不相干的鄰居直接判定。
      實測那種「超標候選只有 1 筆」的樣本準確率僅 0.9143，是舊閘門子集裡
      最差的一塊。這裡釘住「第 N 名才是這組票的下限」。
    """
    monkeypatch.setattr(settings, "RAG_GATE_TOP_N", 3)
    monkeypatch.setattr(settings, "RAG_GATE_SIMILARITY", 0.35)

    # top-1 高達 0.95，但第 3 名只有 0.20 → 票投不出來
    lone_high = _make_cases(0.95, 0.40, 0.20, is_scam=True)
    result, llm_called = await _detect_with_cases(monkeypatch, lone_high)
    assert llm_called is True
    assert result.model == settings.OLLAMA_MODEL

    # 邊界：等於門檻不算通過（閘門要求嚴格大於）
    boundary = _make_cases(0.60, 0.50, 0.35, is_scam=True)
    result, llm_called = await _detect_with_cases(monkeypatch, boundary)
    assert llm_called is True


async def test_gate_too_few_candidates_uses_llm(monkeypatch):
    """候選不足 N 筆（向量庫太小）→ 湊不齊票，交由 LLM。"""
    monkeypatch.setattr(settings, "RAG_GATE_TOP_N", 3)
    monkeypatch.setattr(settings, "RAG_GATE_SIMILARITY", 0.35)

    result, llm_called = await _detect_with_cases(
        monkeypatch, _make_cases(0.9, 0.9, is_scam=True)
    )

    assert llm_called is True
    assert result.model == settings.OLLAMA_MODEL


async def test_gate_low_similarity_goes_to_llm_not_safe(monkeypatch):
    """全部候選都很不相似 → 交由 LLM，**不可**逕自判定為安全。

    ★ 舊閘門有一條「top-1 低於下界 → 直接判 safe 且不呼叫 LLM」的分支，
      已於 2026-09-09 移除。那條分支攔下的正是「庫裡沒見過」的訊息——而那
      恰恰是最該交給 LLM 的一批。實測它在 0.40 攔下 25 筆、其中 1 筆是真詐騙
      （以聯合國名義行騙的簡體訊息，LLM 其實判對了），且完全沒有後手。
      這個測試釘住那條分支不會被人「順手加回來」。
    """
    monkeypatch.setattr(settings, "RAG_GATE_TOP_N", 3)
    monkeypatch.setattr(settings, "RAG_GATE_SIMILARITY", 0.35)

    result, llm_called = await _detect_with_cases(
        monkeypatch, _make_cases(0.10, 0.08, 0.05, is_scam=False)
    )

    assert llm_called is True
    assert result.model == settings.OLLAMA_MODEL
    assert result.model != SIMILARITY_GATE_MODEL


async def test_gate_short_message_needs_higher_scam_similarity(monkeypatch):
    """短訊息的詐騙票沒過較高門檻 → 交給 LLM，而不是直接判詐騙。

    ★ 2026-09-19 真實聊天紀錄：「你好了直接打給我」的 top-3 全是「猜猜我是誰」
      話術（0.441／0.437／0.436），舊閘門直接判詐騙。短句的向量只由一兩個詞決定，
      那種全票一致不可信。
    """
    monkeypatch.setattr(settings, "RAG_GATE_TOP_N", 3)
    monkeypatch.setattr(settings, "RAG_GATE_SIMILARITY", 0.35)
    monkeypatch.setattr(settings, "RAG_GATE_SHORT_MESSAGE_CHARS", 20)
    monkeypatch.setattr(settings, "RAG_GATE_SHORT_SCAM_SIMILARITY", 0.65)

    cases = _make_cases(0.441, 0.437, 0.436, is_scam=True)
    result, llm_called = await _detect_with_cases(monkeypatch, cases, "你好了直接打給我")
    assert llm_called is True
    assert result.model == settings.OLLAMA_MODEL

    # 同一組鄰居配上長訊息 → 照舊直接判詐騙（規則只針對短訊息）
    result, llm_called = await _detect_with_cases(monkeypatch, cases)
    assert llm_called is False
    assert result.is_scam is True


async def test_gate_short_message_still_gated_when_clearly_scam(monkeypatch):
    """短訊息的詐騙票全部超過較高門檻 → 仍直接判詐騙；判安全那側不受短訊息規則影響。"""
    monkeypatch.setattr(settings, "RAG_GATE_TOP_N", 3)
    monkeypatch.setattr(settings, "RAG_GATE_SIMILARITY", 0.35)
    monkeypatch.setattr(settings, "RAG_GATE_SHORT_MESSAGE_CHARS", 20)
    monkeypatch.setattr(settings, "RAG_GATE_SHORT_SCAM_SIMILARITY", 0.65)

    result, llm_called = await _detect_with_cases(
        monkeypatch, _make_cases(0.80, 0.75, 0.70, is_scam=True), "媽我換新號碼了"
    )
    assert llm_called is False
    assert result.is_scam is True

    # 判安全側只需過一般門檻 0.35
    result, llm_called = await _detect_with_cases(
        monkeypatch, _make_cases(0.45, 0.42, 0.40, is_scam=False), "晚餐吃什麼"
    )
    assert llm_called is False
    assert result.is_scam is False


async def test_gate_top_n_one_degenerates_to_top1(monkeypatch):
    """N=1 時退化成純 top-1 判定——記錄這個行為，並提醒它就是舊閘門的病灶。

    留這個測試不是因為 N=1 是好設定（實測它讓整體 F1 從 0.9564 掉到 0.8833），
    而是因為 --sweep 會掃到 N=1，行為必須是明確定義的。
    """
    monkeypatch.setattr(settings, "RAG_GATE_TOP_N", 1)
    monkeypatch.setattr(settings, "RAG_GATE_SIMILARITY", 0.35)

    result, llm_called = await _detect_with_cases(
        monkeypatch, _make_cases(0.95, 0.10, 0.05, is_scam=True)
    )

    assert llm_called is False
    assert result.is_scam is True
    assert result.model == SIMILARITY_GATE_MODEL


async def test_gate_no_cases_uses_llm(monkeypatch):
    """向量庫尚無任何案例（無相似度可依據）→ 交由 LLM 判斷。"""
    result, llm_called = await _detect_with_cases(monkeypatch, [])

    assert llm_called is True
    assert result.model == settings.OLLAMA_MODEL


# ------------------------------------------------------------
# 回應的 similar_cases（顯示門檻與注入門檻分家）
# ------------------------------------------------------------


def _set_thresholds(monkeypatch, *, case: float = 0.559, display: float = 0.35) -> None:
    monkeypatch.setattr(settings, "RAG_CASE_SIMILARITY_THRESHOLD", case)
    monkeypatch.setattr(settings, "RAG_DISPLAY_SIMILARITY_THRESHOLD", display)
    monkeypatch.setattr(settings, "RAG_GATE_TOP_N", 3)
    monkeypatch.setattr(settings, "RAG_GATE_SIMILARITY", 0.35)


async def test_similar_cases_not_empty_when_below_injection_threshold(monkeypatch):
    """★ 相似度落在「判得出來、卻注入不了」的空窗 → 仍要回得出相似案例。

    這是回報的 bug：閘門只要 0.35 就成立，注入門檻卻是 0.559，落在中間的訊息
    會拿到「高風險」加一個空的 similar_cases（實測 1,983 筆中佔 31.7%）。
    """
    _set_thresholds(monkeypatch)

    cases = _make_cases(0.52, 0.48, 0.44, is_scam=True)
    result, llm_called = await _detect_with_cases(monkeypatch, cases)

    assert llm_called is False
    assert result.model == SIMILARITY_GATE_MODEL  # 判定確實成立
    assert [case.similarity for case in result.similar_cases] == [0.52, 0.48, 0.44]


async def test_display_cases_never_leak_into_prompt(monkeypatch):
    """顯示用的案例不得進入提示詞——注入契約必須與微調資料逐字一致。"""
    _set_thresholds(monkeypatch)

    service = RagService()
    sent: list[dict] = []

    async def fake_ask_ollama(messages):
        sent.extend(messages)
        return _LLM_REPLY

    # 兩類並存 → 閘門放行走 LLM；三筆都在 0.35~0.559 之間（顯示得出、注入不得）
    candidates = [
        SimilarCase(content="保證獲利", scam_type="投資詐騙", similarity=0.52, is_scam=True),
        SimilarCase(content="明天開會", scam_type="非詐騙", similarity=0.50, is_scam=False),
        SimilarCase(content="保證獲利2", scam_type="投資詐騙", similarity=0.48, is_scam=True),
    ]
    monkeypatch.setattr(service, "_query_similar_sync", lambda m: candidates)
    monkeypatch.setattr(service, "_ask_ollama", fake_ask_ollama)
    result = await service.detect(_LONG_MESSAGE)

    user_prompt = sent[1]["content"]
    assert user_prompt.count("（無）") == 2  # 兩組案例區塊都是空的
    assert "保證獲利" not in user_prompt
    assert len(result.similar_cases) == 3  # 但回應照樣看得到佐證


async def test_similar_cases_empty_when_nothing_similar_enough(monkeypatch):
    """連顯示門檻都過不了 → 空陣列是誠實的（庫裡真的沒有相近案例）。"""
    _set_thresholds(monkeypatch)

    result, llm_called = await _detect_with_cases(
        monkeypatch, _make_cases(0.30, 0.22, 0.11, is_scam=True)
    )

    assert llm_called is True  # 沒過閘門門檻 → 交給 LLM
    assert result.similar_cases == []


async def test_injection_group_preferred_when_available(monkeypatch):
    """注入那組挑得到時就照舊顯示它，不因為多了退路而混入低相似度的案例。"""
    _set_thresholds(monkeypatch)
    monkeypatch.setattr(settings, "RAG_CASE_MAX_PER_GROUP", 3)

    cases = _make_cases(0.80, 0.75, 0.60, 0.40, 0.38, is_scam=True)
    result, _ = await _detect_with_cases(monkeypatch, cases)

    assert [case.similarity for case in result.similar_cases] == [0.80, 0.75, 0.60]


def test_display_cases_still_exclude_the_query_itself(monkeypatch):
    """退路那組一樣要排除查詢訊息自身／近重複，不能把使用者的訊息回給他自己。"""
    _set_thresholds(monkeypatch)

    candidates = [
        SimilarCase(content=_LONG_MESSAGE, scam_type="投資詐騙", similarity=0.9999),
        # 只差空白與換行的近重複：正規化後與查詢訊息相同，一樣要排掉
        SimilarCase(
            content=f"\n  {_LONG_MESSAGE}\n", scam_type="投資詐騙", similarity=0.50
        ),
        SimilarCase(content="另一則相近的詐騙", scam_type="投資詐騙", similarity=0.45),
    ]
    shown = RagService._display_cases(candidates, _LONG_MESSAGE)

    assert [case.content for case in shown] == ["另一則相近的詐騙"]


# ------------------------------------------------------------
# RAG 總開關（RAG_ENABLED=false：有無 RAG 的 A/B 比較用）
# ------------------------------------------------------------


async def _detect_without_rag(monkeypatch) -> tuple[RagDetectResponse, list[dict]]:
    """以 RAG_ENABLED=false 執行 detect，回傳（偵測結果, 實際送出的提示詞）。

    檢索替身刻意直接拋錯：只要它被呼叫測試就會失敗，藉此證明關閉 RAG 後
    真的完全沒有走嵌入與向量檢索（而非只是把結果丟掉）。
    """
    monkeypatch.setattr(settings, "RAG_ENABLED", False)
    service = RagService()
    sent: list[dict] = []

    def must_not_retrieve(message):
        raise AssertionError("RAG_ENABLED=false 時不應執行嵌入與向量檢索")

    async def fake_ask_ollama(messages):
        sent.extend(messages)
        return _LLM_REPLY

    monkeypatch.setattr(service, "_query_similar_sync", must_not_retrieve)
    monkeypatch.setattr(service, "_ask_ollama", fake_ask_ollama)
    result = await service.detect("測試訊息")
    return result, sent


async def test_rag_disabled_skips_retrieval_and_gate(monkeypatch):
    """關閉 RAG → 不檢索、不走閘門，全部交由 LLM，且回應不含任何相似案例。"""
    # 參數設成「必定會被閘門直接判定」的值：若閘門仍有作用，model 就不會是 LLM
    monkeypatch.setattr(settings, "RAG_GATE_TOP_N", 1)
    monkeypatch.setattr(settings, "RAG_GATE_SIMILARITY", 0.0)

    result, _ = await _detect_without_rag(monkeypatch)

    assert result.model == settings.OLLAMA_MODEL
    assert result.model != SIMILARITY_GATE_MODEL
    assert result.similar_cases == []
    assert result.is_scam is True  # 來自假 LLM 回應
    # 可信度評分 66（< SCAM_HIGH_SCORE_THRESHOLD）在舊規則下是 mid，但 risk_level
    # 現在由已校準的 risk_score 決定（見 _apply_calibrated_risk_level），
    # 這個分箱的實測詐騙率高於 RISK_HIGH_SCORE，故為 high。
    assert result.risk_level == "high"


async def test_rag_disabled_prompt_drops_case_blocks(monkeypatch):
    """關閉 RAG → system 換成無 RAG 版本，user 只有待偵測訊息、無案例區塊。"""
    _, sent = await _detect_without_rag(monkeypatch)

    system, user = sent[0]["content"], sent[1]["content"]
    assert system == SYSTEM_PROMPT_NO_RAG
    assert "【相似案例參考說明】" not in system
    assert "【相似詐騙案例】" not in user
    assert "【相似正常訊息】" not in user
    assert user == "【待偵測訊息】\n測試訊息"  # NO_RAG_PROMPT_HEADER 預設 true


async def test_no_rag_prompt_header_can_be_disabled(monkeypatch):
    """NO_RAG_PROMPT_HEADER=false → user 直接送原始訊息，不加任何標頭。"""
    monkeypatch.setattr(settings, "NO_RAG_PROMPT_HEADER", False)

    _, sent = await _detect_without_rag(monkeypatch)

    assert sent[1]["content"] == "測試訊息"


async def test_rag_enabled_prompt_keeps_case_blocks(monkeypatch):
    """對照組：RAG 開啟時提示詞契約不變（system 為含相似案例說明的版本）。"""
    monkeypatch.setattr(settings, "RAG_ENABLED", True)
    # 兩類並存 → 閘門放行，確保這個測試量到的是 LLM 路徑的提示詞
    monkeypatch.setattr(settings, "RAG_GATE_TOP_N", 3)
    monkeypatch.setattr(settings, "RAG_GATE_SIMILARITY", 0.35)

    service = RagService()
    sent: list[dict] = []

    async def fake_ask_ollama(messages):
        sent.extend(messages)
        return _LLM_REPLY

    conflicting = [
        SimilarCase(content="保證獲利", scam_type="投資詐騙", similarity=0.80, is_scam=True),
        SimilarCase(content="正常訊息", scam_type="非詐騙", similarity=0.78, is_scam=False),
        SimilarCase(content="保證獲利2", scam_type="投資詐騙", similarity=0.76, is_scam=True),
    ]
    monkeypatch.setattr(service, "_query_similar_sync", lambda m: conflicting)
    monkeypatch.setattr(service, "_ask_ollama", fake_ask_ollama)
    await service.detect("測試訊息")

    assert sent[0]["content"] == SYSTEM_PROMPT
    assert "【相似案例參考說明】" in sent[0]["content"]
    assert "【相似詐騙案例】" in sent[1]["content"]
    assert "【相似正常訊息】" in sent[1]["content"]


def test_no_rag_system_prompt_only_drops_similar_case_section():
    """防走樣：兩份 system prompt 必須僅差【相似案例參考說明】整段。

    教科書與任務說明是兩版微調模型共用的訓練契約，若只改了其中一份而另一份
    沒跟上，A/B 比較量到的就會是提示詞差異而非 RAG 的效果。
    """
    start = SYSTEM_PROMPT.index("【相似案例參考說明】")
    end = SYSTEM_PROMPT.index("【任務說明】")
    assert SYSTEM_PROMPT[:start] + SYSTEM_PROMPT[end:] == SYSTEM_PROMPT_NO_RAG


# ------------------------------------------------------------
# LLM 回應正規化（小模型常見錯誤的容錯）
# ------------------------------------------------------------


def _llm_reply(**overrides) -> str:
    """產生一則合法的 LLM 中文鍵 JSON 回應，可覆寫個別欄位以模擬小模型輸出。"""
    verdict = {
        "是否為詐騙": "是",
        "詐騙類別": "假投資詐騙",
        "分析原因": "出現保證獲利話術。",
        "防詐建議": "請先向 165 反詐騙專線查證。",
        "可信度評分": 88,
    }
    verdict.update(overrides)
    return json.dumps(verdict, ensure_ascii=False)


def test_parse_maps_chinese_keys():
    """中文鍵輸出正確映射：高分詐騙 → high、confidence 為評分/100。"""
    verdict = RagService._parse_llm_response(_llm_reply(), [])
    assert verdict["is_scam"] is True
    assert verdict["risk_level"] == "high"  # 88 >= 70
    assert verdict["scam_type"] == "假投資詐騙"
    assert verdict["confidence"] == 0.88
    assert verdict["reasons"] == ["出現保證獲利話術。"]
    assert verdict["advice"] == "請先向 165 反詐騙專線查證。"


def test_parse_scam_low_score_is_mid():
    """詐騙但可信度評分低於門檻（<70）→ risk_level 推導為 mid。"""
    verdict = RagService._parse_llm_response(_llm_reply(**{"可信度評分": 55}), [])
    assert verdict["is_scam"] is True
    assert verdict["risk_level"] == "mid"
    assert verdict["confidence"] == 0.55


def test_parse_normal_is_safe():
    """是否為詐騙=否 → safe，且 scam_type 一律清為 None（即使模型填了類別）。"""
    verdict = RagService._parse_llm_response(
        _llm_reply(**{"是否為詐騙": "否", "詐騙類別": "正常訊息", "可信度評分": 90}),
        [],
    )
    assert verdict["is_scam"] is False
    assert verdict["risk_level"] == "safe"
    assert verdict["scam_type"] is None
    assert verdict["confidence"] == 0.9


def test_parse_decimal_score_normalized():
    """小模型誤把可信度評分填成 0-1 小數（0.85）→ 換算回百分制 → confidence 0.85。"""
    verdict = RagService._parse_llm_response(_llm_reply(**{"可信度評分": 0.85}), [])
    assert verdict["confidence"] == 0.85


# ---------------------------------------------------------------------------
# 詐騙類別 taxonomy（教科書 22 類）
# ---------------------------------------------------------------------------


def test_scam_types_parsed_from_prompt_match_schema_enum():
    """類別清單以 system prompt 為單一事實來源，並且完整灌進輸出 schema 的 enum。

    防的是兩處各自維護而走樣：prompt 改了類別、schema 沒跟上，模型就能輸出一個
    下游不認得的類別（v4.1 評測實測發生 14 次）。
    """
    assert len(SCAM_TYPES) == 22
    assert "假投資詐騙" in SCAM_TYPES
    assert "假新聞/謠言" not in SCAM_TYPES  # 謠言不實但不是詐騙，不在教科書內

    enum = DETECT_RESPONSE_SCHEMA["properties"]["詐騙類別"]["enum"]
    assert enum == [*SCAM_TYPES, NORMAL_TYPE]


def test_parse_normalizes_scam_type_outside_taxonomy():
    """schema enum 未生效時的保險層：教科書外的類別正規化為「未知」。

    structured outputs 已在解碼階段擋掉，此路徑只在 Ollama 版本過舊或換推論
    後端時才會走到——但下游只該處理一種未知值，不是各種模型自創的名稱。
    """
    verdict = RagService._parse_llm_response(
        _llm_reply(**{"詐騙類別": "冒充客服或銀行人員"}), []
    )
    assert verdict["is_scam"] is True
    assert verdict["scam_type"] == "未知"


def test_prompt_has_no_extra_guidance_beyond_finetune_contract():
    """提示詞不得加料：推論輸入必須與 fine_tune.jsonl 的訓練輸入逐字一致。

    曾試著在【任務說明】後補一段「判定邊界」（謠言／防詐提醒／合法交易通知都不是
    詐騙），想壓下短交易通知簡訊的誤報。在 347 筆同型態子集上實測反而更糟：
    誤報 54 → 67、準確率 0.789 → 0.736。點名「銀行驗證碼、超商取貨」這些字眼
    提高了模型對它們的警覺，加上輸入偏離了微調時的分布。

    結論：這類判定邊界要教，就得寫進 fine_tune.jsonl 重新微調，讓訓練與推論一致，
    不能只在推論端單方面加字。此測試把這個結論釘住，避免日後又被加回去。
    """
    for prompt in (SYSTEM_PROMPT, SYSTEM_PROMPT_NO_RAG):
        assert prompt.rstrip().endswith(
            "『可信度評分（0-100，判斷越確定分數越高）』。"
        ), "提示詞結尾被改動；推論輸入必須與微調資料逐字一致"


# ---------------------------------------------------------------------------
# 風險分數校準
# ---------------------------------------------------------------------------


def _calibrator(tmp_path, payload: dict) -> RiskCalibrator:
    path = tmp_path / "risk_calibration.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return RiskCalibrator(path)


def _payload(**overrides) -> dict:
    payload = {
        "model": settings.OLLAMA_MODEL,
        "eval_samples": 2000,
        "cells": [
            {"decided_by": "llm", "predicted": 1, "n": 340, "scam": 313, "risk": 0.92},
            {"decided_by": "llm", "predicted": 0, "n": 111, "scam": 6, "risk": 0.06},
            {"decided_by": "gate", "predicted": 1, "n": 645, "scam": 638, "risk": 0.99},
            {"decided_by": "gate", "predicted": 0, "n": 887, "scam": 21, "risk": 0.02},
        ],
    }
    payload.update(overrides)
    return payload


def test_risk_score_maps_verdict_to_measured_probability(tmp_path):
    """校準把「判定來源＋判定結果」換算成實測詐騙機率，而非沿用 confidence。"""
    calibrator = _calibrator(tmp_path, _payload())
    assert calibrator.score("llm", True) == 0.92
    assert calibrator.score("gate", True) == 0.99
    assert calibrator.score("gate", False) == 0.02


def test_risk_score_is_low_when_verdict_is_normal_despite_high_confidence(tmp_path):
    """判為正常時的高 confidence 代表「很確定安全」，風險分數必須是低的。

    這正是 confidence 不能直接畫成風險條的原因：不論模型多有信心，判為正常的
    那一格對應的都是 6% 風險。
    """
    calibrator = _calibrator(tmp_path, _payload())
    assert calibrator.score("llm", False) == 0.06


def test_risk_score_ignores_confidence_entirely(tmp_path):
    """risk_score 只看四格，不吃 confidence。

    2026-09-25 的改動：實測 confidence 對 risk_score 幾乎沒有貢獻（llm 那側甚至
    是負的），整條 confidence 維度連同分箱與最近鄰查表一起移除。
    """
    calibrator = _calibrator(tmp_path, _payload())
    assert calibrator.score("llm", True) == 0.92
    assert calibrator.score("llm", False) == 0.06


def test_similarity_coefficients_shift_score_within_cell(tmp_path):
    """llm 那格備有係數時，risk_score 會隨檢索鄰域在格內移動，而非固定常數。"""
    payload = _payload()
    for cell in payload["cells"]:
        if cell["decided_by"] == "llm" and cell["predicted"] == 1:
            cell["coef"] = {
                "features": ["scam_share", "topmean"],
                "intercept": -4.0,
                "weights": [6.0, 1.0],
                "n": 350,
            }
    calibrator = _calibrator(tmp_path, payload)
    # 鄰域全是詐騙案例且很近 → 高於格內常數
    strong = calibrator.score("llm", True, [(0.8, True), (0.78, True), (0.75, True)])
    # 鄰域倒向正常訊息 → 低於格內常數
    weak = calibrator.score("llm", True, [(0.6, False), (0.58, False), (0.55, True)])
    assert strong > weak
    assert 0.0 < weak < strong < 1.0


def test_similarity_coefficients_fall_back_without_candidates(tmp_path):
    """沒帶候選、或候選不足 FEATURE_TOP_N 時退回該格常數，而不是外推。"""
    payload = _payload()
    for cell in payload["cells"]:
        if cell["decided_by"] == "llm" and cell["predicted"] == 1:
            cell["coef"] = {
                "features": ["scam_share", "topmean"],
                "intercept": -4.0,
                "weights": [6.0, 1.0],
                "n": 350,
            }
    calibrator = _calibrator(tmp_path, payload)
    assert calibrator.score("llm", True) == 0.92
    assert calibrator.score("llm", True, [(0.8, True)]) == 0.92


def test_similarity_coefficients_ignored_when_feature_set_changed(tmp_path):
    """係數是以別組特徵擬合的 → 退回常數。改了特徵卻沿用舊係數是靜默失真。"""
    payload = _payload()
    for cell in payload["cells"]:
        if cell["decided_by"] == "llm" and cell["predicted"] == 1:
            cell["coef"] = {
                "features": ["top1", "margin"],
                "intercept": -4.0,
                "weights": [6.0, 1.0],
                "n": 350,
            }
    calibrator = _calibrator(tmp_path, payload)
    assert calibrator.score("llm", True, [(0.8, True), (0.78, True), (0.75, True)]) == 0.92


def test_gate_cells_never_carry_similarity_coefficients():
    """上線表的 gate 兩格不該有係數：閘門已經把相似度訊號花掉了（實測增益 0）。"""
    payload = json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))
    for cell in payload["cells"]:
        if cell["decided_by"] == "gate":
            assert "coef" not in cell, "gate 格不應帶相似度係數"


def test_risk_score_none_for_missing_cell(tmp_path):
    """校準表缺某一格時回 None，不拿別格的數字硬頂。"""
    payload = _payload()
    payload["cells"] = [c for c in payload["cells"] if c["decided_by"] != "llm"]
    calibrator = _calibrator(tmp_path, payload)
    assert calibrator.score("llm", True) is None
    assert calibrator.score("gate", True) == 0.99


def test_risk_score_disabled_when_gate_settings_changed(tmp_path):
    """閘門參數直接重劃四格邊界，不符時也要整個停用。"""
    calibrator = _calibrator(
        tmp_path, _payload(gate_top_n=settings.RAG_GATE_TOP_N + 1)
    )
    assert calibrator.score("gate", True) is None


def test_risk_score_disabled_when_calibration_fitted_for_other_model(tmp_path):
    """校準表綁定模型：模型不符時整個停用，不硬套一個看似合理的錯誤機率。"""
    calibrator = _calibrator(tmp_path, _payload(model="some-other-model"))
    assert calibrator.score("llm", True) is None


def test_risk_score_disabled_when_calibration_fitted_for_other_embedding_model(tmp_path):
    """閘門分箱的 confidence 是 top-1 相似度，嵌入模型一換尺度就變，也要整個停用。"""
    calibrator = _calibrator(
        tmp_path, _payload(embedding_model="some-other-embedding-model")
    )
    assert calibrator.score("gate", True) is None


def test_risk_score_kept_when_calibration_matches_embedding_model(tmp_path):
    """嵌入模型相符時照常套用（確認新檢查不會誤擋正確的校準表）。"""
    calibrator = _calibrator(
        tmp_path, _payload(embedding_model=settings.EMBEDDING_MODEL)
    )
    assert calibrator.score("gate", True) == 0.99


def test_risk_level_follows_calibrated_score(monkeypatch):
    """判為詐騙時 risk_level 由 risk_score 決定，不看模型自填的可信度評分。

    送 schema 時 Ollama 會把鍵排序、模型被迫先填分數（flash_v6 因此 82% 的詐騙
    判定拿到 0 或 25），那個分數已經不具資訊，只有校準過的機率能用。
    """
    monkeypatch.setattr(settings, "RISK_HIGH_SCORE", 0.90)

    verdict = {"is_scam": True, "risk_level": "high", "confidence": 0.0}
    _apply_calibrated_risk_level(verdict, 0.85)
    assert verdict["risk_level"] == "mid"

    verdict = {"is_scam": True, "risk_level": "mid", "confidence": 0.0}
    _apply_calibrated_risk_level(verdict, 0.95)
    assert verdict["risk_level"] == "high"


def test_risk_level_keeps_raw_rule_when_calibration_unavailable():
    """校準表不可用（risk_score=None）→ 保留舊規則算出的等級，不硬給。"""
    verdict = {"is_scam": True, "risk_level": "mid", "confidence": 0.66}
    _apply_calibrated_risk_level(verdict, None)
    assert verdict["risk_level"] == "mid"


def test_risk_level_untouched_for_non_scam_verdicts():
    """非詐騙那一側恆為 safe，不受 risk_score 影響。"""
    verdict = {"is_scam": False, "risk_level": "safe", "confidence": 0.95}
    _apply_calibrated_risk_level(verdict, 0.99)
    assert verdict["risk_level"] == "safe"


def test_risk_score_none_when_calibration_missing(tmp_path):
    """校準表不存在時回 None（欄位可選），不應讓偵測整個失敗。"""
    calibrator = RiskCalibrator(tmp_path / "does_not_exist.json")
    assert calibrator.score("llm", True) is None


def test_shipped_calibration_table_is_sane():
    """上線中的校準表必須滿足兩個硬性性質。

    1. 同一判定來源下，判詐騙的風險必須高於判正常——破了就代表分數失去可比較性。
    2. 任何一格都不能是 0.0 或 1.0：有限樣本得到的 100% 只是還沒看到反例
       （Laplace 平滑負責這件事）。
    """
    payload = json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))
    cells = {(c["decided_by"], c["predicted"]): c["risk"] for c in payload["cells"]}
    assert cells, "校準表沒有任何 cells"
    for risk in cells.values():
        assert 0.0 < risk < 1.0, f"機率不得為絕對值：{risk}"
    for decided_by in {k[0] for k in cells}:
        scam, normal = cells.get((decided_by, 1)), cells.get((decided_by, 0))
        if scam is not None and normal is not None:
            assert scam > normal, f"{decided_by}：判詐騙 {scam} 未高於判正常 {normal}"


# ---------------------------------------------------------------------------
# 詐騙階段判定（對話級）
# ---------------------------------------------------------------------------


def _conversation(*pairs: tuple[str, str]) -> list[dict]:
    """把 (說話者, 內容) 組成請求用的 messages 陣列。"""
    return [{"sender": sender, "text": text} for sender, text in pairs]


def _messages(*pairs: tuple[str, str]) -> list[ConversationMessage]:
    return [ConversationMessage(sender=s, text=t) for s, t in pairs]


class FakeStageService:
    """測試替身：回傳固定階段，並記錄是否被呼叫過。"""

    def __init__(self, stage: str = "extraction") -> None:
        self.stage = stage
        self.calls: list[dict] = []

    async def classify(self, messages, *, scam_type=None, previous_stage=None):
        self.calls.append(
            {
                "messages": messages,
                "scam_type": scam_type,
                "previous_stage": previous_stage,
            }
        )
        return StageVerdict(
            stage=self.stage,
            confidence=0.86,
            reasons=["對方要求匯款至指定帳號"],
            next_step_warning="接下來很可能以帳戶凍結為由要求第二筆匯款",
            model="qwen2.5:7b",
        )


class FakeSafeRagService:
    """測試替身：一律判定為非詐騙。"""

    async def detect(self, message: str) -> RagDetectResponse:
        return RagDetectResponse(
            is_scam=False,
            risk_level="safe",
            scam_type=None,
            confidence=0.9,
            reasons=[],
            advice=None,
            similar_cases=[],
            model="gemma4",
        )


def _override(rag, stage_svc) -> None:
    app.dependency_overrides[get_rag_service] = lambda: rag
    app.dependency_overrides[get_stage_service] = lambda: stage_svc


def _clear_overrides() -> None:
    app.dependency_overrides.pop(get_rag_service, None)
    app.dependency_overrides.pop(get_stage_service, None)


async def test_detect_conversation_returns_stage(
    client: AsyncClient, auth_headers: dict
):
    """對話端點：需登入；回傳既有偵測欄位 + 階段欄位。"""
    stage_svc = FakeStageService()
    _override(FakeRagService(), stage_svc)
    try:
        body = {
            "messages": _conversation(
                ("them", "妳好，我是林分析師"),
                ("me", "你哪位"),
                ("them", "先匯三萬到這個帳號就能開通出金"),
            )
        }

        # 未登入 → 401
        response = await client.post("/api/v1/rag/detect-conversation", json=body)
        assert response.status_code == 401

        response = await client.post(
            "/api/v1/rag/detect-conversation", json=body, headers=auth_headers
        )
        assert response.status_code == 200
        payload = response.json()

        # 既有偵測欄位照常回傳（與 /rag/detect 同一份結果）
        assert payload["is_scam"] is True
        assert payload["risk_level"] == "high"
        # 階段欄位
        assert payload["stage"] == "extraction"
        assert payload["stage_label"] == "索取財物"
        assert payload["stage_confidence"] == 0.86
        assert payload["stage_reasons"] == ["對方要求匯款至指定帳號"]
        assert payload["next_step_warning"]
        assert payload["stage_model"] == "qwen2.5:7b"
    finally:
        _clear_overrides()


async def test_detect_conversation_detects_last_counterpart_message(
    client: AsyncClient, auth_headers: dict
):
    """偵測的輸入是「最後一則對方訊息」原文，不是整串對話串接。

    微調模型是用單則訊息訓練的，串接整段對話等於餵它訓練分布外的輸入。
    """
    seen: list[str] = []

    class RecordingRagService(FakeRagService):
        async def detect(self, message: str) -> RagDetectResponse:
            seen.append(message)
            return await super().detect(message)

    _override(RecordingRagService(), FakeStageService())
    try:
        await client.post(
            "/api/v1/rag/detect-conversation",
            json={
                "messages": _conversation(
                    ("them", "第一則"), ("them", "最後一則對方訊息"), ("me", "我的回覆")
                )
            },
            headers=auth_headers,
        )
        assert seen == ["最後一則對方訊息"]
    finally:
        _clear_overrides()


async def test_detect_conversation_skips_stage_when_not_scam(
    client: AsyncClient, auth_headers: dict
):
    """非詐騙且無 previous_stage → 不呼叫階段模型（省一次推論），stage 為 null。"""
    stage_svc = FakeStageService()
    _override(FakeSafeRagService(), stage_svc)
    try:
        response = await client.post(
            "/api/v1/rag/detect-conversation",
            json={"messages": _conversation(("them", "明天的會議改到三點"))},
            headers=auth_headers,
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["is_scam"] is False
        assert payload["stage"] is None
        # 「不需要判」與「判不出來」必須分得開
        assert payload["stage_model"] is None
        assert stage_svc.calls == []
    finally:
        _clear_overrides()


async def test_detect_conversation_keeps_stage_after_flagged(
    client: AsyncClient, auth_headers: dict
):
    """已標記為詐騙的對話（帶 previous_stage）即使最新一則無害，仍要判階段。

    否則對方回一句「好的」就會讓階段整個消失。
    """
    stage_svc = FakeStageService()
    _override(FakeSafeRagService(), stage_svc)
    try:
        response = await client.post(
            "/api/v1/rag/detect-conversation",
            json={
                "messages": _conversation(("them", "好的謝謝")),
                "previous_stage": "extraction",
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["stage"] == "extraction"
        assert len(stage_svc.calls) == 1
        assert stage_svc.calls[0]["previous_stage"] == "extraction"
    finally:
        _clear_overrides()


async def test_detect_conversation_requires_counterpart_message(
    client: AsyncClient, auth_headers: dict
):
    """全部都是使用者自己的訊息 → 400（沒有對方訊息可判）；空陣列 → 422。"""
    _override(FakeRagService(), FakeStageService())
    try:
        response = await client.post(
            "/api/v1/rag/detect-conversation",
            json={"messages": _conversation(("me", "在嗎"), ("me", "哈囉"))},
            headers=auth_headers,
        )
        assert response.status_code == 400

        response = await client.post(
            "/api/v1/rag/detect-conversation",
            json={"messages": []},
            headers=auth_headers,
        )
        assert response.status_code == 422
    finally:
        _clear_overrides()


async def test_detect_conversation_reports_stage_unavailable(
    client: AsyncClient, auth_headers: dict
):
    """階段模型判不出來時仍回傳偵測結果，並以 stage-unavailable 標示。

    偵測結果本身是好的，不該因為階段那半邊掛了就整包丟掉；但也不能悄悄回 null，
    否則 OLLAMA_STAGE_MODEL 指到一顆沒 pull 的模型時，
    外部看到的會是「所有對話都沒有階段」。
    """

    class BrokenStageService:
        async def classify(self, messages, *, scam_type=None, previous_stage=None):
            raise StageUnavailableError("階段模型不可用")

    _override(FakeRagService(), BrokenStageService())
    try:
        response = await client.post(
            "/api/v1/rag/detect-conversation",
            json={"messages": _conversation(("them", "保證獲利，快加入投資群組"))},
            headers=auth_headers,
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["is_scam"] is True  # 偵測結果保留
        assert payload["stage"] is None
        assert payload["stage_model"] == STAGE_UNAVAILABLE_MODEL
    finally:
        _clear_overrides()


async def test_detect_conversation_stage_can_be_disabled(
    client: AsyncClient, auth_headers: dict, monkeypatch
):
    """RAG_STAGE_ENABLED=false → 階段一律 null，偵測結果照常回傳。"""
    monkeypatch.setattr(settings, "RAG_STAGE_ENABLED", False)
    stage_svc = FakeStageService()
    _override(FakeRagService(), stage_svc)
    try:
        response = await client.post(
            "/api/v1/rag/detect-conversation",
            json={"messages": _conversation(("them", "保證獲利，快加入投資群組"))},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["stage"] is None
        assert stage_svc.calls == []
    finally:
        _clear_overrides()


# ----- 階段判定的單元邏輯（不經 HTTP、不呼叫模型） -----


def test_stage_reconcile_is_monotonic(monkeypatch):
    """階段只前進；低信心的回退不予採信，高信心才放行。

    模型只看得到最近數十則——視窗一旦把「先匯 30000」那幾則滑掉，它就會退回
    「培養信任」，使用者眼中就是風險自己降下來了。這條規則專門擋這個。
    """
    monkeypatch.setattr(settings, "RAG_STAGE_REGRESS_CONFIDENCE", 0.8)

    cases = [
        # (previous, predicted, confidence, expected)
        (None, "contact", 0.2, "contact"),  # 沒有前次階段 → 直接採用
        ("grooming", "extraction", 0.4, "extraction"),  # 前進一律採用，不看信心
        ("extraction", "extraction", 0.5, "extraction"),  # 原地不動
        ("extraction", "grooming", 0.79, "extraction"),  # 低信心回退 → 擋住
        ("extraction", "grooming", 0.80, "grooming"),  # 達門檻的回退 → 採信
        ("closing", "contact", 0.1, "closing"),  # 跨多階的低信心回退也擋
    ]
    for previous, predicted, confidence, expected in cases:
        assert (
            reconcile(previous, predicted, confidence) == expected
        ), f"reconcile({previous!r}, {predicted!r}, {confidence}) 應為 {expected!r}"


def test_stage_rule_floor_only_reads_counterpart_messages():
    """關鍵詞規則只掃對方的訊息：使用者說「我不會匯款」不代表對方索取過。"""
    # 對方索取 → 下界為 extraction
    assert rule_floor(_messages(("them", "請將三萬元匯款到這個帳號"))) == "extraction"
    # 同樣的字出自使用者 → 不成立
    assert rule_floor(_messages(("me", "我不會匯款給你的"))) is None
    # 已經付過還要再付 → closing（比 extraction 晚）
    assert rule_floor(_messages(("them", "出金失敗，需要先繳稅金"))) == "closing"
    # 純寒暄 → 規則沒有意見，完全交給模型
    assert rule_floor(_messages(("them", "妳今天過得好嗎"))) is None
    # 刻意排除的高誤判字眼：互留帳號是接觸階段的正常行為
    assert rule_floor(_messages(("them", "我的 LINE 帳號是 abc123"))) is None


async def test_stage_rule_floor_lifts_model_underestimate(monkeypatch):
    """模型低估時由規則地板抬上來：對方明確要匯款，就不可能只是「培養信任」。"""
    service = StageService()

    async def fake_chat(messages, **kwargs):
        return json.dumps(
            {
                "詐騙階段": "培養信任",
                "階段判斷理由": "對方在閒聊",
                "下一步預測": "繼續閒聊",
                "階段可信度評分": 90,
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(ollama_client, "chat", fake_chat)
    verdict = await service.classify(
        _messages(("them", "妳今天過得好嗎"), ("them", "先匯三萬到這個帳號"))
    )
    assert verdict.stage == "extraction"
    assert verdict.label == "索取財物"


async def test_stage_falls_back_to_rule_when_model_unavailable(monkeypatch):
    """階段模型掛掉但規則有意見 → 退回規則結果，並標示 stage-rule。"""
    service = StageService()

    async def broken_chat(messages, **kwargs):
        raise ollama_client.OllamaError("連不上 Ollama")

    monkeypatch.setattr(ollama_client, "chat", broken_chat)
    verdict = await service.classify(_messages(("them", "請把提款卡寄到這個地址")))
    assert verdict.stage == "extraction"
    assert verdict.model == STAGE_RULE_MODEL

    # 規則與前次階段都沒有意見 → 不猜，拋出讓端點標示「判不出來」
    with pytest.raises(StageUnavailableError):
        await service.classify(_messages(("them", "妳今天過得好嗎")))


async def test_stage_prompt_contains_conversation_and_scam_type(monkeypatch):
    """送進階段模型的 user 訊息：一則一行、標記說話者，並帶上已知詐騙類型。"""
    service = StageService()
    sent: list[dict] = []

    async def fake_chat(messages, **kwargs):
        sent.extend(messages)
        return json.dumps(
            {
                "詐騙階段": "鋪陳誘餌",
                "階段判斷理由": "保證獲利",
                "下一步預測": "要求匯款",
                "階段可信度評分": 70,
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(ollama_client, "chat", fake_chat)
    await service.classify(
        _messages(("them", "這檔穩賺\n我帶妳"), ("me", "真的嗎")),
        scam_type="假投資詐騙",
    )

    system, user = sent[0]["content"], sent[1]["content"]
    assert system == STAGE_SYSTEM_PROMPT
    assert "【已知詐騙類型】假投資詐騙" in user
    # 訊息內的換行必須被壓平，否則行首的說話者標記會對不上
    assert "[對方] 這檔穩賺 我帶妳" in user
    assert "[我] 真的嗎" in user


def test_stage_trims_oldest_messages(monkeypatch):
    """超過則數／字數上限時由最舊的開始捨棄，且至少保留最後一則。"""
    monkeypatch.setattr(settings, "RAG_STAGE_MAX_MESSAGES", 3)
    monkeypatch.setattr(settings, "RAG_STAGE_MAX_CHARS", 4000)

    window = trim_conversation(_messages(*[("them", f"第{i}則") for i in range(10)]))
    assert [m.text for m in window] == ["第7則", "第8則", "第9則"]

    # 字數上限更嚴時再往下砍（每則 3 字，上限 7 字只容得下 2 則）
    monkeypatch.setattr(settings, "RAG_STAGE_MAX_CHARS", 7)
    window = trim_conversation(_messages(*[("them", f"第{i}則") for i in range(10)]))
    assert [m.text for m in window] == ["第8則", "第9則"]

    # 單則就超過上限 → 仍保留該則，不清空視窗
    monkeypatch.setattr(settings, "RAG_STAGE_MAX_CHARS", 2)
    window = trim_conversation(_messages(("them", "很長的一則訊息")))
    assert len(window) == 1


def test_stage_labels_parsed_from_prompt_match_schema_enum():
    """階段名稱以 prompt 為單一事實來源，並完整灌進輸出 schema 的 enum。

    防的是兩處各自維護而走樣：prompt 改了階段名稱、程式碼沒跟上，模型輸出的
    中文名就對不回任何 slug，等於整個階段功能靜默失效。
    """
    labels = [label for _, label in STAGES]
    assert labels == ["接觸建立", "培養信任", "鋪陳誘餌", "索取財物", "收尾拖延"]
    assert STAGE_RESPONSE_SCHEMA["properties"]["詐騙階段"]["enum"] == labels
    # 模組載入時的守門條件（prompt 解析結果必須與 STAGES 相同）在此重演一次
    assert (
        re.findall(r"^\d+\.\s*([^：\n]+)：", STAGE_SYSTEM_PROMPT, re.MULTILINE) == labels
    )


def test_stage_parse_rejects_unknown_stage_name():
    """schema enum 未生效時的保險層：對不回 slug 的階段名稱視為沒有判定，不猜。"""
    assert StageService.parse_response(json.dumps({"詐騙階段": "取得信任期"})) is None
    assert StageService.parse_response("這不是 JSON") is None

    parsed = StageService.parse_response(
        json.dumps(
            {
                "詐騙階段": "索取財物",
                "階段判斷理由": "要求匯款",
                "下一步預測": "再要一筆",
                "階段可信度評分": 88,
            },
            ensure_ascii=False,
        )
    )
    assert parsed == {
        "stage": "extraction",
        "confidence": 0.88,
        "reasons": ["要求匯款"],
        "next_step_warning": "再要一筆",
    }
