"""風險分數校準：把判定結果映射成實測的詐騙機率。

偵測回應的 `confidence` 是「模型對這個判斷的信心」，不是「這則訊息是詐騙的機率」：
判為正常、confidence 0.95 代表「很確定安全」，直接拿去畫風險條會變成滿格紅色。
本模組讀入 fit_risk_calibration.py 由評測結果擬合的對照表，把
(判定來源, 判定結果) 換算成 `risk_score`——可直接當機率解讀、可跨判定來源比較、
可用來排序，而 `confidence` 維持原語意不動以免影響既有前端。

⚠ 2026-09-25 起不再吃 confidence：實測它對 risk_score 幾乎沒有貢獻
（四格基礎率 Brier 0.0345 vs 舊的 11 分箱版 0.0340），llm 那側甚至是負貢獻。
推導與數據見 fit_risk_calibration.py 的模組註解。

校準表與整條管線綁定：模型、嵌入模型或閘門參數一改，四格的母體就不同，舊表會
靜默地給出錯誤的風險分數。因此載入時逐項比對，不符就整個停用（risk_score 回
None）而非硬套——寧可前端沒有這個欄位，也不要給一個看起來合理的錯誤機率。
"""

import json
import logging
import math
import threading
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

# 校準表路徑（專案根目錄；由 fit_risk_calibration.py 產生）
CALIBRATION_PATH = Path(__file__).resolve().parent.parent.parent / "risk_calibration.json"

# 取最相似的前幾筆來算特徵。與 RAG_GATE_TOP_N 無關，不要共用設定：
# 閘門用它決定「投票人數」，這裡只是取一段穩定的鄰域來描述檢索結果。
FEATURE_TOP_N = 3

# 特徵名稱與順序，必須與 extract_features() 的輸出一致。
# 寫進校準表並於載入時比對，避免日後改了特徵卻沿用舊係數——那會是靜默失真。
FEATURE_NAMES = ["scam_share", "topmean"]


def extract_features(candidates: list[tuple[float, bool]]) -> list[float] | None:
    """由最相似的 N 筆（相似度, 是否為詐騙案例）算出校準特徵。

    候選不足 N 筆時回傳 None——此時呼叫端退回該格的常數，而不是拿一個
    由一兩筆算出來的特徵去外推。

    兩個特徵的用意：
    - scam_share：相似度加權的「詐騙票佔比」，描述鄰域倒向哪一邊
    - topmean   ：前 N 筆的平均相似度，描述這個鄰域整體有多近
    """
    top = candidates[:FEATURE_TOP_N]
    if len(top) < FEATURE_TOP_N:
        return None
    total = sum(sim for sim, _ in top) or 1e-9
    scam_share = sum(sim for sim, is_scam in top if is_scam) / total
    topmean = total / len(top)
    return [scam_share, topmean]


class RiskCalibrator:
    """依校準表把判定結果換算成詐騙機率（延遲載入的單例）。"""

    def __init__(self, path: Path = CALIBRATION_PATH) -> None:
        self._path = path
        self._cells: dict[tuple[str, int], float] | None = None
        self._loaded = False
        self._lock = threading.Lock()

    def _binding_mismatch(self, payload: dict) -> str | None:
        """回傳不符的項目說明；全部相符時回傳 None。

        舊版校準表沒有的欄位不比對（無從比對），由必定存在的 model 欄位兜底。
        """
        checks = [
            ("model", settings.OLLAMA_MODEL, "LLM 模型"),
            ("embedding_model", settings.EMBEDDING_MODEL, "嵌入模型"),
            # 閘門參數直接重劃四格的邊界：門檻一動，哪些樣本會落在 gate 那兩格
            # 就跟著變，四個機率全部失真。
            ("gate_top_n", settings.RAG_GATE_TOP_N, "閘門投票數 RAG_GATE_TOP_N"),
            ("gate_similarity", settings.RAG_GATE_SIMILARITY, "閘門門檻 RAG_GATE_SIMILARITY"),
        ]
        for key, current, label in checks:
            fitted = payload.get(key)
            if fitted is not None and fitted != current:
                return f"{label}：擬合時為 {fitted!r}，目前為 {current!r}"
        return None

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            self._loaded = True  # 不論成敗都只嘗試一次，避免每次請求都讀檔／重複告警
            try:
                payload = json.loads(self._path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                logger.warning(
                    "找不到風險校準表 %s，risk_score 將回傳 null；"
                    "請跑 fit_risk_calibration.py 由評測結果擬合",
                    self._path,
                )
                return
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("風險校準表載入失敗（%s），risk_score 將回傳 null", exc)
                return

            mismatch = self._binding_mismatch(payload)
            if mismatch:
                logger.warning(
                    "風險校準表與目前設定不符（%s）；四格的母體已經不同，"
                    "已停用 risk_score。請以目前設定重跑評測並重新擬合。",
                    mismatch,
                )
                return

            cells: dict[tuple[str, int], dict] = {}
            for entry in payload.get("cells", []):
                coef = entry.get("coef")
                # 特徵定義變了卻沿用舊係數 → 靜默失真，故只在名稱與順序都相符時採用
                if coef and list(coef.get("features", [])) != FEATURE_NAMES:
                    logger.warning(
                        "校準表 %s/%s 的係數是以特徵 %s 擬合的，目前為 %s；"
                        "已改用該格的常數。請重新擬合。",
                        entry["decided_by"], entry["predicted"],
                        coef.get("features"), FEATURE_NAMES,
                    )
                    coef = None
                cells[(entry["decided_by"], int(entry["predicted"]))] = {
                    "risk": float(entry["risk"]),
                    "coef": coef,
                }
            if not cells:
                logger.warning("風險校準表沒有任何 cells，risk_score 將回傳 null")
                return
            self._cells = cells
            logger.info(
                "風險校準表已載入（模型 %s，擬合樣本 %s 筆，%s 格）",
                payload.get("model"),
                payload.get("eval_samples"),
                len(cells),
            )

    def score(
        self,
        decided_by: str,
        is_scam: bool,
        candidates: list[tuple[float, bool]] | None = None,
    ) -> float | None:
        """回傳校準後的詐騙機率；校準表不可用或該格不存在時回傳 None。

        不吃 confidence：見模組註解，那一維實測沒有貢獻。

        candidates（最相似的前幾筆）只在該格備有係數時才用得到——目前只有 llm
        兩格有，gate 那側的相似度訊號已經被閘門花掉了。沒帶候選、候選不足、或該格
        沒有係數時，一律退回該格的常數，行為與四格版相同。
        """
        self._ensure_loaded()
        if self._cells is None:
            return None
        cell = self._cells.get((decided_by, int(is_scam)))
        if cell is None:
            return None

        coef = cell["coef"]
        if not coef or candidates is None:
            return cell["risk"]
        features = extract_features(candidates)
        if features is None:
            return cell["risk"]

        z = coef["intercept"] + sum(
            w * x for w, x in zip(coef["weights"], features)
        )
        return round(1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z)))), 4)


# 全域單例：校準表只讀一次
risk_calibrator = RiskCalibrator()
