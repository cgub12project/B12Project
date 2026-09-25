"""RAG 詐騙偵測服務。

偵測流程：
1. 以嵌入模型（預設 BGE-M3，可由 EMBEDDING_MODEL 切換）將使用者訊息轉為稠密向量（GPU 加速）
2. 於本地 ChromaDB 取回相似度最高的多筆候選，依 is_scam 分成「相似詐騙案例」與
   「相似正常訊息」兩組，每組各留 similarity > RAG_CASE_SIMILARITY_THRESHOLD、
   最多 RAG_CASE_MAX_PER_GROUP 筆（對齊 fine_tune.jsonl 的注入契約）
3. 相似度一致性閘門：取相似度最高的 RAG_GATE_TOP_N 筆候選，若它們全部超過
   RAG_GATE_SIMILARITY 且 is_scam 標籤完全一致，就依該類直接判定 high（詐騙）
   或 safe（一般訊息），不呼叫 LLM；其餘情況一律交給 LLM。短訊息（≤
   RAG_GATE_SHORT_MESSAGE_CHARS 字）的「直接判詐騙」另需超過 RAG_GATE_SHORT_SCAM_SIMILARITY
   （參數可於 .env 調整；掃描方式見 scripts/eval_scam_detection.py --sweep）
4. 閘門放行的樣本才組提示詞，交由 Ollama 本地 LLM（OLLAMA_MODEL）判斷
5. 解析 LLM 的 JSON 回應（中文欄位鍵）並回傳結構化結果
   （回應的 similar_cases 走另一條門檻，見 _display_cases）
6. 依校準表換算 risk_score（校準後的詐騙機率）。⚠ confidence 是「模型對這個判斷的
   把握」不是詐騙機率——判為安全時的高 confidence 代表「很確定安全」，
   要呈現風險必須用 risk_score，見 risk_calibration.py

★ 提示詞與微調資料（data/finetune.jsonl）是同一份契約，推論時看到的 system／user
  必須與訓練時逐字一致（實測在推論端加料會掉分，test_rag.py 有測試釘住）。
  輸出由 Ollama structured outputs（JSON Schema）在解碼階段強制成中文鍵 JSON。

實作要點：嵌入模型與 ChromaDB 連線都是延遲初始化的單例；嵌入是同步阻塞運算，
以 asyncio.to_thread 移出事件迴圈。嵌入模型、門檻與 RAG_ENABLED=false 的
A/B 模式見 app/core/config.py 與 README。
"""

import asyncio
import json
import logging
import re
import threading
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.schemas.rag import RagDetectResponse, SimilarCase
from app.services import ollama_client

# 嵌入模型後端抽象層：實際模型由 .env 的 EMBEDDING_MODEL 決定。
# 於此重新匯出，維持 rag_worker.py 既有的匯入路徑。
from app.services.embedding import (  # noqa: F401  (re-export)
    check_collection_dimension,
    embed_texts_sync,
    load_embedding_model,
    resolve_device,
)
from app.services.risk_calibration import risk_calibrator

logger = logging.getLogger(__name__)

# 相似度閘門直接判定（未呼叫 LLM）時，回應 model 欄位所使用的識別名稱
SIMILARITY_GATE_MODEL = "similarity-gate"

# System prompt 為與 fine_tune.jsonl 完全一致的正規來源（165 教科書 + 相似案例參考
# 說明 + 任務說明）。存於獨立資源檔以確保推論與訓練逐字對齊；由此檔於載入時讀入。
_PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"
_SYSTEM_PROMPT_PATH = _PROMPT_DIR / "scam_detection_system.txt"
SYSTEM_PROMPT = _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")

# 關閉 RAG（RAG_ENABLED=false）時使用的 system prompt：與上方逐字相同，
# 僅移除【相似案例參考說明】整段——該段描述的輸入（相似案例）此時並不存在，
# 留著會讓模型去參照一個永遠為空的區塊。兩檔的一致性由 test_rag.py 驗證。
_SYSTEM_PROMPT_NO_RAG_PATH = _PROMPT_DIR / "scam_detection_system_no_rag.txt"
SYSTEM_PROMPT_NO_RAG = _SYSTEM_PROMPT_NO_RAG_PATH.read_text(encoding="utf-8")

# assistant 輸出的欄位鍵序（與 fine_tune.jsonl 一致）
ASSISTANT_KEY_ORDER = ["是否為詐騙", "詐騙類別", "分析原因", "防詐建議", "可信度評分"]

# 教科書的 22 種詐騙類別：直接從 system prompt 解析，而非另外維護一份清單。
# 兩處各自維護必然會走樣——prompt 改了、清單沒改，模型就會輸出一個下游不認得的
# 類別；反之則是限制了一個 prompt 根本沒教過的類別。以 prompt 為單一事實來源。
SCAM_TYPES = re.findall(r"^\d+\.\s*([^：\n]+)：", SYSTEM_PROMPT, re.MULTILINE)
if len(SCAM_TYPES) != 22:  # pragma: no cover - 提示詞被改壞時盡早爆掉
    raise RuntimeError(
        f"從 system prompt 解析出 {len(SCAM_TYPES)} 種詐騙類別（預期 22）："
        "請確認【台灣 165 官方詐騙手法與特徵參考教科書】的編號格式未被改動"
    )

# 非詐騙時「詐騙類別」欄位的值（與微調資料一致）
NORMAL_TYPE = "正常訊息"

# LLM 回應的 JSON Schema：傳給 Ollama 的 format 欄位（structured outputs），
# 於解碼階段強制輸出符合此結構（中文鍵，對齊微調輸出），小模型也不會漏欄位或給錯型別
DETECT_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "是否為詐騙": {"type": "string", "enum": ["是", "否"]},
        # 限定為教科書的 22 類 + 正常訊息：提示詞雖已要求，模型仍會自創類別
        # （v4.1 評測 2000 筆中出現 12 種教科書外的名稱，如「假新聞/謠言」、
        # 「冒充客服或銀行人員」共 14 次）。前端依類別顯示說明與防詐建議，收到
        # 沒見過的字串只能顯示空白，因此改由解碼階段直接擋掉，而非事後清洗。
        "詐騙類別": {"type": "string", "enum": [*SCAM_TYPES, NORMAL_TYPE]},
        # ⚠ maxLength 不是美觀考量，是防止整筆回應報廢：Ollama 會把鍵按字碼排序
        # （見 _ask_ollama），「分析原因」因此排在最前面，而它原本沒有長度上限——
        # 模型一旦在這裡退化成重複（實測有 -1-1-1…、✨✨✨…、整句複讀等形態），
        # 就會一路吃掉 num_predict，永遠到不了「是否為詐騙」，回應變成不合法 JSON，
        # 最後被 _parse_llm_response 的後備方案吞成 safe——那是無聲的漏報。
        # 2026-09-25 全量評測（1,983 筆 / 449 次 LLM 呼叫）：
        #     加上限前  解析失敗 18 次（4.01%），其中 5 筆是真詐騙被吞成 safe
        #     加上限後  解析失敗  0 次（0.00%），最長輸出 572 → 213 字元
        # 正常輸出的中位數是 157 字元，離上限還很遠，兩組的準確率差異不顯著
        # （McNemar p=0.40），所以這是正確性修正，不是準確率改善，勿混為一談。
        "分析原因": {"type": "string", "maxLength": 150},
        "防詐建議": {"type": "string", "maxLength": 100},
        "可信度評分": {"type": "integer", "minimum": 0, "maximum": 100},
    },
    "required": ASSISTANT_KEY_ORDER,
}

# 檢索案例放入提示詞時的單筆長度上限：避免長案例稀釋小模型的注意力
PROMPT_CASE_MAX_CHARS = 200

# LLM 回應解析失敗時，後備方案要「直接判詐騙」所需的 top-1 相似度。
# ⚠ 這個值隨嵌入模型的餘弦尺度變動，換模型必須重訂——舊值 0.8 是 BGE-M3 時代的，
#   在 embeddinggemma 下幾乎達不到（gate 判詐騙的 top-1 主體只在 0.58~0.67），
#   等於把後備判詐騙那條路無聲關閉：2026-09-25 評測的 18 次解析失敗沒有一次被它救起來。
# 依當次評測重訂（母體＝交由 LLM 判定且 top-1 為詐騙案例，209 筆）：
#     >=0.80   納入   7 筆   精確率 1.000  ← 舊值，覆蓋太少
#     >=0.70   納入  39 筆   精確率 1.000  ← 現值
#     >=0.65   納入  91 筆   精確率 0.956
# 後備是在「沒有 LLM 判定」的情況下猜，寧可少救幾筆也不要誤報，故取精確率仍為 1.0
# 的最低門檻。加上 maxLength 後解析失敗已降為 0，這條路平時不會觸發，但仍是最後防線。
FALLBACK_SCAM_SIMILARITY = 0.70

# 模型偶爾會把對話模板碎片吐進字串欄位（2026-09-25 評測 449 次呼叫中 21 次，4.68%；
# 與 maxLength 無關，加上限後反而降到 16 次）。這兩個欄位會直接顯示給使用者，
# 故在解析階段截掉標記之後的內容，而非讓它出現在 App 上。
_TEMPLATE_LEAK = re.compile(
    r"\}system|<start_of_turn>|<end_of_turn>|<\|[^>]*?\|>|系統偵測到一筆"
)


def _strip_template_leak(text: str) -> str:
    """截掉對話模板碎片之後的內容（找不到標記時原樣回傳）。"""
    match = _TEMPLATE_LEAK.search(text)
    return text[: match.start()].rstrip() if match else text

# 詐騙樣本 risk_level 的**退路**規則：可信度評分 >= 此門檻為 high、否則 mid。
# 校準表可用時不走這裡，改由 risk_score 決定（見 _apply_calibrated_risk_level）——
# 送 schema 時模型被迫先填分數，那個分數在 flash_v6 上已不具資訊。
SCAM_HIGH_SCORE_THRESHOLD = 70

# 相似度過高（近乎完全相同）視為查詢訊息自身／近重複，從相似案例中排除
SELF_SIMILARITY = 0.999


def _collapse_whitespace(text: str) -> str:
    """將連續空白（含換行）壓成單一空格並去頭尾（對齊注入時的 norm 規則）。"""
    return re.sub(r"\s+", " ", text).strip()


class RagUnavailableError(Exception):
    """RAG 服務不可用（相依套件未安裝、模型載入失敗或 Ollama 連線失敗）。"""


def _apply_calibrated_risk_level(
    verdict: dict[str, Any], risk_score: float | None
) -> None:
    """判為詐騙時，改以已校準的 risk_score 決定 high／mid（就地修改 verdict）。

    為什麼不沿用模型自填的「可信度評分」：送 schema 時 Ollama 會把鍵按字碼排序，
    模型得在下判斷之前先填分數（見 _ask_ollama 的註解）。flash_v6 因此有 82% 的
    詐騙判定拿到 0 或 25 分，1,983 筆實測中 947 筆真詐騙有 254 筆被降成 mid。
    risk_score 是由實測詐騙率擬合的機率，不受那個順序影響。

    校準表不可用時（換模型後尚未重擬合、檔案不存在）risk_score 為 None，
    此時保留呼叫端原本用可信度評分算出的 risk_level——寧可沿用舊規則，
    也不要在沒有校準依據時硬給一個等級。
    非詐騙判定不動：那一側恆為 safe，與分數無關。
    """
    if risk_score is None or not verdict.get("is_scam"):
        return
    verdict["risk_level"] = "high" if risk_score >= settings.RISK_HIGH_SCORE else "mid"


class RagService:
    """RAG 偵測服務（單例使用；模型與 ChromaDB 延遲初始化）。"""

    def __init__(self) -> None:
        self._model = None  # BGE-M3 模型（延遲載入）
        self._collection = None  # ChromaDB 集合（延遲連線）
        self._init_lock = threading.Lock()  # 避免並發請求重複載入模型
        # 保守防護：序列化 ChromaDB collection.query()。註：本服務曾出現「併發下相似度
        # 全部塌成 ~1.0、每筆都被誤判為高風險詐騙」的 bug，真正根因是 BGE-M3 冷啟動
        # 首次前向傳播的併發競爭（見 _ensure_ready_sync 的暖機修正），並非此查詢競爭；
        # 此鎖是依當初的錯誤假設加的，單獨無法修好該 bug。其必要性尚未驗證（ChromaDB
        # query 是否併發安全未確認），移除前請先驗證。BGE-M3 編碼不納入鎖內以保留吞吐。
        self._query_lock = threading.Lock()

    # ------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------

    def _ensure_ready_sync(self) -> None:
        """確保模型與向量資料庫已初始化（同步；於執行緒中呼叫）。"""
        if self._model is not None and self._collection is not None:
            return

        with self._init_lock:
            # double-checked locking：拿到鎖後再確認一次
            if self._model is None:
                try:
                    model = load_embedding_model()
                    # 嵌入模型的「首次」前向傳播並非併發安全（cuDNN benchmark 自動
                    # 選演算法與 CUDA/FP16 延遲初始化會在多執行緒下互相競爭），
                    # 冷啟動時若多個請求同時嵌入，會產生失真的向量，使檢索相似度
                    # 全部逼近 1.0，相似度閘門因而把每則訊息都誤判為高風險詐騙。
                    # 因此在鎖內先跑一次暖機推論，完成後才發布到 self._model：
                    # 確保任何併發呼叫看到的都是已完全初始化的模型。
                    # 以 is_query=True 暖機：與實際查詢路徑走完全相同的前綴與長度。
                    embed_texts_sync(model, ["暖機"], is_query=True)
                    self._model = model
                except ImportError as exc:
                    raise RagUnavailableError(
                        "RAG 相依套件未安裝（torch / FlagEmbedding / sentence-transformers），"
                        "請先安裝 GPU 版 PyTorch 與所選模型對應的後端套件"
                    ) from exc
                except Exception as exc:
                    raise RagUnavailableError(
                        f"嵌入模型 {settings.EMBEDDING_MODEL} 載入失敗：{exc}"
                    ) from exc

            if self._collection is None:
                try:
                    import chromadb

                    client = chromadb.PersistentClient(path=settings.CHROMA_DIR)
                    # 以餘弦距離建立／取得集合（與 RAG Worker 使用同一集合）
                    collection = client.get_or_create_collection(
                        name=settings.CHROMA_COLLECTION,
                        metadata={"hnsw:space": "cosine"},
                    )
                    # 換嵌入模型時最容易踩的坑：沿用舊模型建立的集合。維度不符會
                    # 在此直接報錯，而非等到查詢時才爆出難懂的錯誤。
                    check_collection_dimension(collection, self._model)
                    # 同理先在鎖內觸發 HNSW 索引的延遲載入，暖機後才發布。
                    # 以已暖機的模型產生查詢向量（集合建立時未指定 embedding
                    # function，用 query_texts 會誤觸 ChromaDB 內建模型的下載）
                    warmup_vector = embed_texts_sync(
                        self._model, ["暖機"], is_query=True
                    )[0]
                    collection.query(query_embeddings=[warmup_vector], n_results=1)
                    self._collection = collection
                except ImportError as exc:
                    raise RagUnavailableError("RAG 相依套件未安裝（chromadb）") from exc
                except Exception as exc:
                    raise RagUnavailableError(f"ChromaDB 連線失敗：{exc}") from exc

    # ------------------------------------------------------------
    # 向量檢索
    # ------------------------------------------------------------

    def _query_similar_sync(self, message: str) -> list[SimilarCase]:
        """嵌入查詢訊息並取回相似度最高的多筆候選案例（同步；於執行緒中呼叫）。

        取回 RAG_RETRIEVE_CANDIDATES 筆候選（依相似度遞減），供後續依 is_scam
        分成「相似詐騙案例／相似正常訊息」兩組挑選，以及相似度閘門取 top-1。
        """
        self._ensure_ready_sync()

        # 嵌入在鎖外執行：暖機後的編碼可安全併發，且為最耗時的 GPU 運算。
        # is_query=True：非對稱模型（E5、Qwen3 等）查詢側須套用專用前綴
        query_vector = embed_texts_sync(self._model, [message], is_query=True)[0]
        # 保守序列化 ChromaDB 查詢（其必要性尚未驗證，見 __init__ 的 _query_lock 註解）
        with self._query_lock:
            result = self._collection.query(
                query_embeddings=[query_vector],
                n_results=settings.RAG_RETRIEVE_CANDIDATES,
                include=["documents", "metadatas", "distances"],
            )

        cases: list[SimilarCase] = []
        documents = result.get("documents") or [[]]
        metadatas = result.get("metadatas") or [[]]
        distances = result.get("distances") or [[]]
        for doc, meta, distance in zip(documents[0], metadatas[0], distances[0]):
            # 餘弦距離轉相似度：similarity = 1 - distance，並夾在 [0, 1]
            similarity = max(0.0, min(1.0, 1.0 - float(distance)))
            cases.append(
                SimilarCase(
                    content=doc,
                    scam_type=str((meta or {}).get("scam_type", "未知")),
                    similarity=round(similarity, 4),
                    # 早期入庫的向量無 is_scam 標籤，一律視為詐騙案例
                    is_scam=bool((meta or {}).get("is_scam", True)),
                )
            )
        return cases

    @staticmethod
    def _select_cases(
        cases: list[SimilarCase], message: str, threshold: float
    ) -> tuple[list[SimilarCase], list[SimilarCase]]:
        """依 is_scam 把候選分成「相似詐騙案例／相似正常訊息」兩組。

        - 只保留 similarity > threshold（嚴格大於）
        - 排除與查詢訊息近乎相同者（similarity >= SELF_SIMILARITY 或正規化後文字相同）
        - 兩組各依相似度遞減取前 RAG_CASE_MAX_PER_GROUP 筆
        （傳入的 cases 已依相似度遞減排序，故過濾後保持順序即可）
        """
        query_norm = _collapse_whitespace(message)
        scam: list[SimilarCase] = []
        normal: list[SimilarCase] = []
        for case in cases:
            if case.similarity <= threshold:
                continue
            if case.similarity >= SELF_SIMILARITY:
                continue
            if _collapse_whitespace(case.content) == query_norm:
                continue
            (scam if case.is_scam else normal).append(case)
        limit = settings.RAG_CASE_MAX_PER_GROUP
        return scam[:limit], normal[:limit]

    @classmethod
    def _split_cases(
        cls, cases: list[SimilarCase], message: str
    ) -> tuple[list[SimilarCase], list[SimilarCase]]:
        """提示詞注入用的兩組相似案例（對齊 fine_tune.jsonl 的注入契約）。

        門檻固定為 RAG_CASE_SIMILARITY_THRESHOLD——它釘在訓練時的注入契約上，
        動它等於讓推論時看到的提示詞與訓練分佈不一致，不可為了「回應好看」而調。
        要改回應呈現的案例請改 _display_cases。
        """
        return cls._select_cases(
            cases, message, settings.RAG_CASE_SIMILARITY_THRESHOLD
        )

    @classmethod
    def _display_cases(
        cls, cases: list[SimilarCase], message: str
    ) -> list[SimilarCase]:
        """回應 similar_cases 要呈現的案例：注入那組優先，空的時候才退而求其次。

        為什麼不直接沿用注入那組（2026-09-20 修正）：注入門檻 0.559 是訓練契約的
        一部分，判定門檻只要 0.35，落在兩者之間的訊息照樣會被閘門判定、卻一筆佐證
        案例都顯示不出來（實測 1,983 筆有 31.7% 落在這個空窗，其中 508 筆是閘門判的）。
        因此顯示與注入分家：注入一個字都不動，只有注入那組為空時才以較低的
        RAG_DISPLAY_SIMILARITY_THRESHOLD 另挑一組純供呈現。兩者都挑不到才是真的空。
        """
        scam, normal = cls._split_cases(cases, message)
        if scam or normal:
            return scam + normal
        scam, normal = cls._select_cases(
            cases, message, settings.RAG_DISPLAY_SIMILARITY_THRESHOLD
        )
        return scam + normal

    # ------------------------------------------------------------
    # 相似度區間閘門
    # ------------------------------------------------------------

    @staticmethod
    def _similarity_gate(
        cases: list[SimilarCase], message: str | None = None
    ) -> dict[str, Any] | None:
        """一致性閘門：最相似的 N 筆若一面倒，直接判定，省下一次 LLM 推論。

        規則只有一條：取相似度最高的 `RAG_GATE_TOP_N` 筆，若它們**全部**嚴格大於
        `RAG_GATE_SIMILARITY`，且 is_scam 標籤**完全一致**，就依該類直接判定；
        其餘所有情況（票數不足、有一筆沒過門檻、兩類並存）一律回傳 None 交給 LLM。

        為什麼是固定 N 筆，而不是「所有超過門檻的候選」（2026-09-09 改）：後者的
        投票人數由相似度分佈間接決定，兩頭都會出事——只有 1 筆超標時「全部同類」
        自動成立（退化成 top-1，那批準確率只有 0.9143），40 筆全超標時第 35 名鄰居
        也握有否決權。固定成 N 之後兩個病一起消失，票數也不再隨嵌入模型的尺度漂移。
        實測對照表與門檻怎麼掃出來的見 README 的閘門章節與 --sweep。

        ⚠ 舊規則的「top-1 太低 → 直接判 safe」分支已移除，不是漏掉：那條攔下的正是
        「庫裡沒見過」的訊息，而那是最該交給 LLM 的一批（實測 25 筆裡有 1 筆真詐騙）。

        短訊息例外（傳入 message 時生效）：≤ RAG_GATE_SHORT_MESSAGE_CHARS 字的訊息，
        「直接判詐騙」改用較高的 RAG_GATE_SHORT_SCAM_SIMILARITY，判安全那側不變。
        短句的向量幾乎只由一兩個詞決定，那種全票一致並不可信。

        Returns:
            判定結果 dict；None 表示需交由 LLM 判斷。
        """
        top_n = settings.RAG_GATE_TOP_N
        threshold = settings.RAG_GATE_SIMILARITY
        scam_threshold = threshold
        if (
            message is not None
            and len(_collapse_whitespace(message).replace(" ", ""))
            <= settings.RAG_GATE_SHORT_MESSAGE_CHARS
        ):
            scam_threshold = max(threshold, settings.RAG_GATE_SHORT_SCAM_SIMILARITY)

        # 候選不足 N 筆就湊不齊票（向量庫太小或剛建好）→ 交給 LLM。
        # ChromaDB 依距離遞增排序，cases[:top_n] 即最相似的 N 筆。
        if len(cases) < top_n:
            return None
        voters = cases[:top_n]

        # 「全部」超過門檻，不是只看 top-1：第 N 名才是這組票的下限，
        # 用 top-1 代表整組會讓一個孤立的高相似鄰居帶著 N-1 個不相干的鄰居過關。
        if any(case.similarity <= threshold for case in voters):
            return None

        scam_votes = sum(1 for case in voters if case.is_scam)
        if scam_votes not in (0, top_n):
            return None  # 兩類並存＝模糊地帶，不可只憑相似度的微小差距決定
        if scam_votes == top_n and any(case.similarity <= scam_threshold for case in voters):
            return None  # 短訊息的詐騙票未達較高門檻 → 交給 LLM（不是判安全）

        top = voters[0]
        # confidence 一律取 top-1 相似度（不是投票比例）——這是 risk_calibration
        # 擬合 ("gate", is_scam) 那組分箱時用的量，換成別的量會讓校準表對不上。
        confidence = round(top.similarity, 4)
        vote_note = (
            f"最相似的 {top_n} 筆案例相似度皆高於 {threshold:.2f}"
            f"（最高 {top.similarity:.2f}），且"
        )

        if scam_votes == top_n:
            return {
                "is_scam": True,
                "risk_level": "high",
                "scam_type": top.scam_type,
                "confidence": confidence,
                "reasons": [
                    f"{vote_note}全部屬於已知詐騙案例（{top.scam_type}），"
                    "未呼叫 LLM 直接判定為高風險"
                ],
                "advice": (
                    "此訊息與已知詐騙案例高度相似，請勿點擊連結、"
                    "勿依指示操作或匯款，可撥打 165 反詐騙專線查證。"
                ),
            }

        return {
            "is_scam": False,
            "risk_level": "safe",
            "scam_type": None,
            "confidence": confidence,
            "reasons": [
                f"{vote_note}全部屬於已知的一般（非詐騙）訊息，"
                "未呼叫 LLM 直接判定為安全"
            ],
            "advice": "此訊息與已知一般訊息高度相似，仍請保持基本警覺。",
        }

    # ------------------------------------------------------------
    # LLM 判斷（Ollama）
    # ------------------------------------------------------------

    @staticmethod
    def _format_user_prompt(
        message: str,
        scam_cases: list[SimilarCase],
        normal_cases: list[SimilarCase],
    ) -> str:
        """組裝 user 訊息：待偵測訊息 + 兩組相似案例（與 fine_tune.jsonl 注入格式一致）。

        區塊順序固定為【待偵測訊息】/【相似詐騙案例】/【相似正常訊息】；某組為空時
        該區塊寫「（無）」。案例內容以單一空格壓縮換行後截斷至 PROMPT_CASE_MAX_CHARS。
        """
        lines = ["【待偵測訊息】", message, "", "【相似詐騙案例】"]
        if scam_cases:
            for index, case in enumerate(scam_cases, start=1):
                body = _collapse_whitespace(case.content)[:PROMPT_CASE_MAX_CHARS]
                lines.append(
                    f"{index}.（類別：{case.scam_type}｜相似度 {case.similarity:.2f}）{body}"
                )
        else:
            lines.append("（無）")

        lines += ["", "【相似正常訊息】"]
        if normal_cases:
            for index, case in enumerate(normal_cases, start=1):
                body = _collapse_whitespace(case.content)[:PROMPT_CASE_MAX_CHARS]
                lines.append(f"{index}.（相似度 {case.similarity:.2f}）{body}")
        else:
            lines.append("（無）")

        return "\n".join(lines)

    @staticmethod
    def _format_user_prompt_no_rag(message: str) -> str:
        """組裝關閉 RAG 時的 user 訊息：只有待偵測訊息，不含任何相似案例區塊。

        是否保留【待偵測訊息】標頭由 NO_RAG_PROMPT_HEADER 決定——請對齊該版微調
        資料的 user 欄位格式，推論輸入才會與訓練時逐字一致。
        """
        if settings.NO_RAG_PROMPT_HEADER:
            return f"【待偵測訊息】\n{message}"
        return message

    @classmethod
    def _build_prompt(
        cls,
        message: str,
        scam_cases: list[SimilarCase],
        normal_cases: list[SimilarCase],
        *,
        use_rag: bool | None = None,
    ) -> list[dict[str, str]]:
        """組裝送給本地 LLM 的對話提示詞（與微調資料同一契約）。

        system 為與 fine_tune.jsonl 完全一致的正規 prompt（165 教科書 + 相似案例
        參考說明 + 任務說明，載自資源檔）；user 為【待偵測訊息】＋兩組相似案例。
        不再插入 few-shot 範例——微調後的模型已學會此格式，額外範例反而偏離訓練分布。
        輸出格式由 Ollama structured outputs（DETECT_RESPONSE_SCHEMA，中文鍵）強制。

        use_rag=False（或 RAG_ENABLED=false）時改用無 RAG 契約：system 換成不含
        【相似案例參考說明】的版本，user 只放待偵測訊息，兩組案例一律忽略。
        use_rag=None 表示沿用 settings.RAG_ENABLED。
        """
        if use_rag is None:
            use_rag = settings.RAG_ENABLED
        if not use_rag:
            return [
                {"role": "system", "content": SYSTEM_PROMPT_NO_RAG},
                {"role": "user", "content": cls._format_user_prompt_no_rag(message)},
            ]
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": cls._format_user_prompt(message, scam_cases, normal_cases),
            },
        ]

    @staticmethod
    async def _ask_ollama(messages: list[dict[str, str]]) -> str:
        """呼叫 Ollama /api/chat（structured outputs 強制中文鍵 JSON），回傳文字回應。

        實際的 HTTP 呼叫與失敗原因分類共用 ollama_client（階段判定服務用同一套），
        此處只負責帶入偵測這條線的模型與 schema，並把失敗轉成 RagUnavailableError。

        think=False 不是可有可無的：思考型模型（實測 gemma-4-12b）預設會先產生一段
        thinking，而 Ollama 把它放在 message.thinking、不是 message.content；
        num_predict(512) 在思考途中用完時 content 回空字串，_parse_llm_response 就會
        退回最保守的「非詐騙」——**靜默漏報**，日誌上看不出任何異常。
        2026-09-12 實測：未送這個欄位時 gemma-4-12b 在交給 LLM 的 144 筆上準確率
        只有 0.2431（333 筆詐騙漏掉 115 筆），送了之後才量得到真實能力。
        階段那條線（stage_service）本來就有送，這裡是補齊。
        非思考型模型收到這個欄位會直接忽略（實測 flash_v4.1 / flash_v6 不受影響）。
        """
        try:
            return await ollama_client.chat(
                messages,
                base_url=settings.OLLAMA_BASE_URL,
                model=settings.OLLAMA_MODEL,
                timeout=settings.OLLAMA_TIMEOUT,
                # ⚠ 送完整 schema 有一個已知副作用：Ollama 會把鍵按字碼排序
                # （見 ollama_client.chat 的說明），實際輸出順序是
                # 分析原因→可信度評分→是否為詐騙→詐騙類別→防詐建議，
                # 與微調樣本的鍵序不同。flash_v6 因此有 82% 的詐騙判定把可信度評分
                # 填成 0 或 25，risk_level 被降成 mid（真詐騙 315 筆裡 254 筆）。
                #
                # 2026-09-16 實測過改送 "json"（純 JSON 模式，模型照訓練鍵序輸出）：
                # 評分確實回到 85、high 從 61 筆升到 238 筆，**但召回率掉了**——
                #     schema  準確 0.9612  召回 0.9604  漏報 39  誤報 38
                #     json    準確 0.9470  召回 0.9138  漏報 85  誤報 20
                #     LLM 交集 450 筆：json 對而 schema 錯 25、反向 53，McNemar p = 0.002
                # 漏報多 46 筆，比 flash_v4.1(53) 與 flash_v5(55) 都差。推測是排序後
                # 「分析原因」排在最前面，等於先推理再判斷，那個效果本身在幫忙。
                # 逐筆結果留在 eval/eval_flash_v6_1983_jsonmode.jsonl。
                #
                # 結論：維持 schema。分數失真改由 risk_score（已校準）處理，
                # 不要拿召回去換一個顯示欄位。
                response_schema=DETECT_RESPONSE_SCHEMA,
                think=False,
            )
        except ollama_client.OllamaError as exc:
            raise RagUnavailableError(str(exc)) from exc

    @staticmethod
    def _parse_llm_response(raw: str, cases: list[SimilarCase]) -> dict[str, Any]:
        """解析 LLM 的中文鍵 JSON 回應，映射為 RagDetectResponse 欄位。

        微調輸出欄位：是否為詐騙（是/否）、詐騙類別、分析原因、防詐建議、
        可信度評分（0-100 整數）。映射規則：
        - is_scam ← 是否為詐騙 == 是
        - risk_level ← 非詐騙為 safe；詐騙時可信度評分 >= 門檻為 high、否則 mid
        - scam_type ← 詐騙時取詐騙類別（正常訊息／空值視為無）
        - confidence ← 可信度評分 / 100
        - reasons ← [分析原因]；advice ← 防詐建議
        解析失敗時退回以最相似案例推估的保守結果。
        """
        parsed: dict[str, Any] | None = None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            # 嘗試從回應文字中擷取第一個 JSON 物件
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                except json.JSONDecodeError:
                    parsed = None

        if not isinstance(parsed, dict):
            # 後備方案：LLM 回應無法解析時，依最相似案例做保守判斷
            # （僅當最相似案例本身是詐騙案例才視為可能詐騙）
            top = cases[0] if cases else None
            likely_scam = bool(
                top and top.is_scam and top.similarity >= FALLBACK_SCAM_SIMILARITY
            )
            return {
                "is_scam": likely_scam,
                "risk_level": "mid" if likely_scam else "safe",
                "scam_type": top.scam_type if likely_scam and top else None,
                "confidence": 0.3,
                "reasons": ["AI 回應解析失敗，僅依據向量相似度做保守判斷"],
                "advice": "建議提高警覺，勿點擊不明連結或依指示匯款。",
            }

        # 是否為詐騙：主要看「是/否」字串，並相容布林值
        verdict = parsed.get("是否為詐騙")
        if isinstance(verdict, bool):
            is_scam = verdict
        else:
            is_scam = str(verdict).strip() == "是"

        # 可信度評分：0-100 整數；容錯字串／小數／百分比
        score_raw = parsed.get("可信度評分", 0)
        try:
            score = float(score_raw)
            if 0.0 < score <= 1.0:
                # 少數情況模型誤填 0-1 小數，換算回 0-100
                score *= 100.0
            score = max(0.0, min(100.0, score))
        except (TypeError, ValueError):
            score = 50.0 if is_scam else 0.0

        if not is_scam:
            risk_level = "safe"
        elif score >= SCAM_HIGH_SCORE_THRESHOLD:
            risk_level = "high"
        else:
            risk_level = "mid"

        # 詐騙類別：非詐騙、或值為「正常訊息」/空時視為無
        scam_type = parsed.get("詐騙類別")
        if not is_scam or not scam_type or str(scam_type).strip() in ("", NORMAL_TYPE):
            scam_type = None
        elif str(scam_type).strip() not in SCAM_TYPES:
            # 保險層：schema 的 enum 已在解碼階段擋掉教科書外的類別，此處只涵蓋
            # enum 未生效的情況（Ollama 版本過舊、或改走不支援 structured outputs
            # 的推論後端）。統一成 rag_worker 入庫時的「未知」，下游只需處理一種
            # 未知值，而不是各種模型自創的名稱。
            logger.warning("LLM 回傳教科書外的詐騙類別：%r，已正規化為「未知」", scam_type)
            scam_type = "未知"

        # 兩個欄位都會直接顯示給使用者，先截掉模型吐出的對話模板碎片
        reason = _strip_template_leak(str(parsed.get("分析原因") or "")).strip()
        reasons = [reason] if reason else []
        advice = _strip_template_leak(str(parsed.get("防詐建議") or "")).strip()

        return {
            "is_scam": is_scam,
            "risk_level": risk_level,
            "scam_type": scam_type,
            "confidence": round(score / 100.0, 4),
            "reasons": reasons,
            "advice": advice or None,
        }

    # ------------------------------------------------------------
    # 對外主流程
    # ------------------------------------------------------------

    async def detect(self, message: str) -> RagDetectResponse:
        """偵測一則訊息是否為詐騙（完整 RAG 流程）。

        RAG_ENABLED=false 時走「純 LLM」路徑：完全跳過嵌入、向量檢索與相似度閘門，
        直接以無 RAG 契約的提示詞交給 LLM 判斷（此模式不需 GPU 與 ChromaDB）。

        Raises:
            RagUnavailableError: 模型／向量庫／Ollama 任一環節不可用。
        """
        if not settings.RAG_ENABLED:
            return await self._detect_without_rag(message)

        # 嵌入 + 向量檢索為阻塞運算，移至執行緒執行以免卡住事件迴圈
        candidates = await asyncio.to_thread(self._query_similar_sync, message)

        # 提示詞輸入：依 is_scam 分成兩組相似案例（各 >注入門檻、最多 N 筆）
        scam_cases, normal_cases = self._split_cases(candidates, message)
        # 回應呈現：注入那組為空時改用較低的顯示門檻，避免判定有了卻沒有任何
        # 佐證案例可看（見 _display_cases）。提示詞不受影響。
        shown_cases = self._display_cases(candidates, message)

        # 一致性閘門：最相似的 N 筆一面倒時直接回覆，不呼叫 LLM
        gate_verdict = self._similarity_gate(candidates, message)
        if gate_verdict is not None:
            gate_score = risk_calibrator.score("gate", gate_verdict["is_scam"])
            _apply_calibrated_risk_level(gate_verdict, gate_score)
            return RagDetectResponse(
                **gate_verdict,
                risk_score=gate_score,
                similar_cases=shown_cases,
                model=SIMILARITY_GATE_MODEL,
            )

        # 相似度落在區間內 → 交由本地 LLM 綜合判斷
        raw_response = await self._ask_ollama(
            self._build_prompt(message, scam_cases, normal_cases)
        )
        verdict = self._parse_llm_response(raw_response, candidates)
        # llm 兩格備有相似度微調係數（gate 那側沒有——閘門已經把訊號花掉了），
        # 故把最相似的幾筆一起帶進去；校準表沒有係數時會自動退回該格常數。
        llm_score = risk_calibrator.score(
            "llm",
            verdict["is_scam"],
            [(c.similarity, c.is_scam) for c in candidates],
        )
        _apply_calibrated_risk_level(verdict, llm_score)

        return RagDetectResponse(
            **verdict,
            risk_score=llm_score,
            similar_cases=shown_cases,
            model=settings.OLLAMA_MODEL,
        )

    async def _detect_without_rag(self, message: str) -> RagDetectResponse:
        """關閉 RAG 時的偵測路徑：不檢索、不走閘門，直接交由 LLM 判斷。

        供「有無 RAG」的準確度 A/B 比較使用。回應的 similar_cases 必為空陣列，
        model 仍為 OLLAMA_MODEL——此路徑永遠不會出現 similarity-gate 判定。
        後備解析（_parse_llm_response）在無候選案例時會退回最保守的 safe 結果。
        """
        raw_response = await self._ask_ollama(
            self._build_prompt(message, [], [], use_rag=False)
        )
        verdict = self._parse_llm_response(raw_response, [])
        llm_score = risk_calibrator.score("llm", verdict["is_scam"])
        _apply_calibrated_risk_level(verdict, llm_score)

        return RagDetectResponse(
            **verdict,
            risk_score=llm_score,
            similar_cases=[],
            model=settings.OLLAMA_MODEL,
        )


# 全域單例：模型只載入一次，所有請求共用
rag_service = RagService()


def get_rag_service() -> RagService:
    """FastAPI 相依性：取得 RAG 服務單例（測試時可覆寫）。"""
    return rag_service
