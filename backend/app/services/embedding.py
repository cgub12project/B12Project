"""嵌入模型後端抽象層。

將「載入模型」與「文字轉向量」從特定套件（原本硬綁 FlagEmbedding 的 BGE-M3）
抽離，改以 `.env` 的 `EMBEDDING_MODEL` 決定實際後端，讓不同嵌入模型可直接
A/B 比較，無須改動 RAG 服務與入庫程式的程式碼。

目前支援兩種後端：
- `flagembedding`：FlagEmbedding 的 `BGEM3FlagModel`（BGE-M3 專用 API）
- `sentence_transformers`：`SentenceTransformer`（Qwen3-Embedding、gte、E5、
  bge-zh 等絕大多數 HuggingFace 嵌入模型的通用介面）

後端預設由模型名稱自動判斷（`EMBEDDING_BACKEND=auto`），亦可明確指定。

## 兩件會安靜掉分的事

1. **非對稱前綴**：多數檢索模型的「查詢」與「被檢索文件」要用不同前綴
   （E5 的 query:/passage:、Qwen3 的 Instruct 格式），漏加會顯著掉分。
   故 embed_texts_sync() 以 is_query 區分，前綴由 MODEL_PRESETS 依模型名自動套用。
2. **換模型要重建向量庫並重新校準門檻**：餘弦分佈不同；維度不同時
   check_collection_dimension() 會在啟動時擋下，維度剛好相同時不報錯但結果無意義。
"""

import logging
import re
from typing import Protocol

from app.core.config import settings

logger = logging.getLogger(__name__)

# 供 Qwen3-Embedding 等 instruct 型模型使用的任務描述：以本系統的實際任務
# （而非預設的網頁搜尋）描述，讓查詢向量偏向「找出語意相近的詐騙／正常訊息」
SCAM_RETRIEVAL_TASK = "Given a message, retrieve semantically similar scam or legitimate messages"

# Qwen3-Embedding／E5-instruct 系列的查詢前綴格式（文件側不加前綴）
_INSTRUCT_QUERY_PREFIX = f"Instruct: {SCAM_RETRIEVAL_TASK}\nQuery: "


class ModelPreset:
    """單一模型的預設參數（前綴、是否需信任遠端程式碼）。"""

    def __init__(
        self,
        *,
        backend: str,
        query_prefix: str = "",
        passage_prefix: str = "",
        trust_remote_code: bool = False,
        dtype: str = "float16",
    ) -> None:
        self.backend = backend
        self.query_prefix = query_prefix
        self.passage_prefix = passage_prefix
        self.trust_remote_code = trust_remote_code
        # GPU 上的推論精度。預設 float16（對齊 BGE-M3 的 use_fp16），
        # 但 Gemma 系列在 fp16 會溢位成 NaN，必須改用 bfloat16——見下方 preset 註解。
        self.dtype = dtype


# 已驗證模型的預設值；鍵為模型名稱的小寫子字串（比對 EMBEDDING_MODEL）。
# 順序即比對優先序：較長／較specific 的鍵須排在前面。
MODEL_PRESETS: list[tuple[str, ModelPreset]] = [
    # --- BGE-M3：本系統原始模型，對稱式檢索，查詢與文件皆不加前綴 ---
    ("bge-m3", ModelPreset(backend="flagembedding")),
    # --- Qwen3-Embedding：多語 MTEB 榜首級，Apache 2.0，支援 MRL 降維 ---
    (
        "qwen3-embedding",
        ModelPreset(
            backend="sentence_transformers",
            query_prefix=_INSTRUCT_QUERY_PREFIX,
        ),
    ),
    # --- gte-multilingual-base：約 BGE-M3 一半體積，需 trust_remote_code ---
    (
        "gte-multilingual",
        ModelPreset(backend="sentence_transformers", trust_remote_code=True),
    ),
    (
        "gte-qwen2",
        ModelPreset(
            backend="sentence_transformers",
            query_prefix=_INSTRUCT_QUERY_PREFIX,
            trust_remote_code=True,
        ),
    ),
    # --- EmbeddingGemma：Google 的端上嵌入模型（現行預設）---
    # 前綴取自模型卡的 Retrieval 任務，是訓練時綁定的任務標記，換字或省略會顯著掉分。
    # ⚠ HuggingFace 上是 gated repo：要先接受授權並登入（HF_TOKEN）才下載得到。
    # ⚠ dtype 必須 bfloat16：float16 下第一次前向傳播就整條輸出 NaN，**且不拋例外**
    #   （照常入庫、照常跑完評測，只是分數全變噪音），故載入時另加了探針檢查。
    (
        "embeddinggemma",
        ModelPreset(
            backend="sentence_transformers",
            query_prefix="task: search result | query: ",
            passage_prefix="title: none | text: ",
            dtype="bfloat16",
        ),
    ),
    # --- E5 系列：instruct 版查詢用 Instruct 格式，一般版用 query:/passage: ---
    (
        "e5-large-instruct",
        ModelPreset(
            backend="sentence_transformers",
            query_prefix=_INSTRUCT_QUERY_PREFIX,
        ),
    ),
    (
        "e5-base-instruct",
        ModelPreset(
            backend="sentence_transformers",
            query_prefix=_INSTRUCT_QUERY_PREFIX,
        ),
    ),
    (
        "e5",
        ModelPreset(
            backend="sentence_transformers",
            query_prefix="query: ",
            passage_prefix="passage: ",
        ),
    ),
    # --- bge 中文系列（v1.5）：查詢側加中文指令句，文件側不加 ---
    (
        "bge-large-zh",
        ModelPreset(
            backend="sentence_transformers",
            query_prefix="為這個句子生成表示以用於檢索相關文章：",
        ),
    ),
    (
        "bge-base-zh",
        ModelPreset(
            backend="sentence_transformers",
            query_prefix="為這個句子生成表示以用於檢索相關文章：",
        ),
    ),
]

# 未知模型的保底預設：走通用的 SentenceTransformer，不加前綴
DEFAULT_PRESET = ModelPreset(backend="sentence_transformers")


def resolve_preset(model_name: str) -> ModelPreset:
    """依模型名稱取得預設參數；未收錄的模型回傳 DEFAULT_PRESET。"""
    lowered = model_name.lower()
    for key, preset in MODEL_PRESETS:
        if key in lowered:
            return preset
    return DEFAULT_PRESET


def resolve_device() -> str:
    """解析嵌入模型的運算裝置。

    EMBEDDING_DEVICE=auto 時自動偵測：有 CUDA GPU 就用 GPU，否則退回 CPU。
    """
    if settings.EMBEDDING_DEVICE != "auto":
        return settings.EMBEDDING_DEVICE

    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def _tune_gpu_backend(device: str) -> None:
    """GPU 效能最佳化設定（僅 CUDA 裝置適用）。"""
    import torch

    if not device.startswith("cuda"):
        logger.warning("未偵測到 CUDA GPU，嵌入模型將以 CPU 執行（效能較差）")
        return

    # cuDNN 自動挑選最快的卷積演算法（輸入尺寸固定時效果最佳）
    torch.backends.cudnn.benchmark = True
    # 允許 TF32 矩陣運算（Ampere 以上顯卡大幅加速，精度損失可忽略）
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    torch.set_float32_matmul_precision("high")
    logger.info("偵測到 CUDA GPU：%s", torch.cuda.get_device_name(0))


def _repair_position_ids(model) -> None:
    """重填未初始化的 `position_ids` buffer（載入後、推論前呼叫）。

    部分需 `trust_remote_code` 的模型（實測 gte-multilingual-base）把 position_ids
    存成 non-persistent buffer，transformers 5.x 從 meta device materialize 時不會
    填值，模型拿那段未初始化記憶體去索引 rope 表就會炸（GPU 上是 device-side
    assert，錯誤訊息看不出真正原因）。正確內容恆為 arange，故無條件重填；
    以 view_as 保持原形狀（BERT 系列是 [1, max_len]，攤平會反過來弄壞它們）。
    """
    import torch

    for module in model.modules():
        buffer = getattr(module, "position_ids", None)
        if not isinstance(buffer, torch.Tensor):
            continue
        # 只處理已實體化的整數索引 buffer：meta device 上的張量不能比較也不能填值，
        # 誤踩會讓「所有」模型的載入都掛掉，而不只是有問題的那一個
        if buffer.device.type == "meta" or buffer.dtype.is_floating_point:
            continue
        expected = torch.arange(
            buffer.numel(), device=buffer.device, dtype=buffer.dtype
        ).view_as(buffer)
        if not torch.equal(buffer, expected):
            logger.warning(
                "偵測到未初始化的 position_ids buffer（%s），已重填為 arange",
                settings.EMBEDDING_MODEL,
            )
        module.position_ids = expected


class EmbeddingBackend(Protocol):
    """嵌入後端介面：RAG 服務與入庫程式只依賴此介面。"""

    def encode(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        """將文字批次轉為稠密向量（同步、阻塞）。"""
        ...

    @property
    def dimension(self) -> int:
        """輸出向量維度（用於檢查 ChromaDB 集合是否相容）。"""
        ...


class _BaseBackend:
    """後端共用邏輯：套用查詢／文件前綴。"""

    def __init__(self, preset: ModelPreset) -> None:
        # `.env` 明確設定時覆寫預設（空字串代表「明確不加前綴」，故用 None 判斷）
        self._query_prefix = (
            preset.query_prefix
            if settings.EMBEDDING_QUERY_PREFIX is None
            else settings.EMBEDDING_QUERY_PREFIX
        )
        self._passage_prefix = (
            preset.passage_prefix
            if settings.EMBEDDING_PASSAGE_PREFIX is None
            else settings.EMBEDDING_PASSAGE_PREFIX
        )

    def _apply_prefix(self, texts: list[str], is_query: bool) -> list[str]:
        prefix = self._query_prefix if is_query else self._passage_prefix
        if not prefix:
            return texts
        return [prefix + text for text in texts]


class FlagEmbeddingBackend(_BaseBackend):
    """BGE-M3 後端（FlagEmbedding 的 BGEM3FlagModel）。

    僅取用 dense_vecs（稠密向量）；BGE-M3 另可輸出 sparse／ColBERT 向量，
    目前流程未使用。
    """

    def __init__(self, preset: ModelPreset) -> None:
        super().__init__(preset)
        from FlagEmbedding import BGEM3FlagModel

        device = resolve_device()
        _tune_gpu_backend(device)

        # use_fp16：半精度推論，GPU 上速度約為 FP32 兩倍且記憶體減半
        self._model = BGEM3FlagModel(
            settings.EMBEDDING_MODEL,
            use_fp16=device.startswith("cuda"),
            device=device,
        )
        self._dimension = 0
        logger.info(
            "嵌入模型載入完成：%s（後端=flagembedding, device=%s）",
            settings.EMBEDDING_MODEL,
            device,
        )

    def encode(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        output = self._model.encode(
            self._apply_prefix(texts, is_query),
            batch_size=settings.EMBEDDING_BATCH_SIZE,
            max_length=settings.EMBEDDING_MAX_LENGTH,
        )
        # dense_vecs 為 numpy 陣列（FP16/FP32），轉為 Python list 供 ChromaDB 使用
        vectors = [vector.tolist() for vector in output["dense_vecs"]]
        if vectors and not self._dimension:
            self._dimension = len(vectors[0])
        return vectors

    @property
    def dimension(self) -> int:
        if not self._dimension:
            # 尚未編碼過任何文字時，以一次極短推論取得維度
            self.encode(["dim"])
        return self._dimension


class SentenceTransformerBackend(_BaseBackend):
    """通用 SentenceTransformer 後端（Qwen3-Embedding、gte、E5、bge-zh 等）。

    輸出一律做 L2 正規化，使餘弦相似度等同內積，與 ChromaDB 的 cosine
    空間及 BGE-M3（本身即輸出正規化向量）行為一致。
    """

    def __init__(self, preset: ModelPreset) -> None:
        super().__init__(preset)
        import torch
        from sentence_transformers import SentenceTransformer

        device = resolve_device()
        _tune_gpu_backend(device)

        kwargs = {
            "device": device,
            "trust_remote_code": settings.EMBEDDING_TRUST_REMOTE_CODE
            or preset.trust_remote_code,
        }
        if device.startswith("cuda"):
            # 半精度推論（預設 float16，對齊 BGE-M3 的 use_fp16）。
            # 個別模型可由 preset 指定，例如 Gemma 系列必須用 bfloat16。
            kwargs["model_kwargs"] = {"torch_dtype": getattr(torch, preset.dtype)}
        if settings.EMBEDDING_DIMENSION > 0:
            # MRL 降維（Qwen3-Embedding 等支援；不支援的模型會直接截斷，
            # 請確認模型本身以 Matryoshka 訓練後再啟用）
            kwargs["truncate_dim"] = settings.EMBEDDING_DIMENSION

        self._dtype = preset.dtype if device.startswith("cuda") else "float32"
        self._model = SentenceTransformer(settings.EMBEDDING_MODEL, **kwargs)
        # 統一最大長度，避免不同模型的預設值造成比較基準不一致
        self._model.max_seq_length = settings.EMBEDDING_MAX_LENGTH
        # 必須在任何一次推論之前修，否則第一次前向傳播就會炸在 GPU 上
        _repair_position_ids(self._model)
        self._assert_finite_output()
        logger.info(
            "嵌入模型載入完成：%s（後端=sentence_transformers, device=%s, dim=%s）",
            settings.EMBEDDING_MODEL,
            device,
            self.dimension,
        )

    def _assert_finite_output(self) -> None:
        """載入後編碼一句探針，確認輸出不是 NaN／Inf（半精度溢位是最常見的成因）。

        成本是一次極短的前向傳播，換掉的是一整輪「分數怎麼這麼低」的無效實驗。
        """
        import math

        vector = self._model.encode(
            ["檢查編碼輸出是否為有限數值"],
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )[0]
        if not all(math.isfinite(float(value)) for value in vector):
            raise ValueError(
                f"嵌入模型 `{settings.EMBEDDING_MODEL}` 的輸出含 NaN/Inf"
                f"（dtype={self._dtype}）。半精度溢位是最常見的原因："
                "請在 MODEL_PRESETS 為這顆模型指定 dtype=\"bfloat16\"，"
                "或設定 EMBEDDING_DEVICE=cpu 以 fp32 執行。"
            )

    def encode(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        vectors = self._model.encode(
            self._apply_prefix(texts, is_query),
            batch_size=settings.EMBEDDING_BATCH_SIZE,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [vector.tolist() for vector in vectors]

    @property
    def dimension(self) -> int:
        # sentence-transformers 於新版將 get_sentence_embedding_dimension 更名為
        # get_embedding_dimension（舊名仍可用但會發出 FutureWarning），故優先取新名
        getter = getattr(
            self._model,
            "get_embedding_dimension",
            None,
        ) or self._model.get_sentence_embedding_dimension
        return int(getter())


def load_embedding_model() -> EmbeddingBackend:
    """依 `.env` 設定載入嵌入模型（同步、阻塞；請在執行緒中呼叫）。

    後端由 `EMBEDDING_BACKEND` 決定；`auto`（預設）時依 `EMBEDDING_MODEL`
    名稱查 `MODEL_PRESETS` 自動判斷。

    Returns:
        EmbeddingBackend 實例。
    """
    preset = resolve_preset(settings.EMBEDDING_MODEL)
    backend = settings.EMBEDDING_BACKEND
    if backend == "auto":
        backend = preset.backend

    if backend == "flagembedding":
        return FlagEmbeddingBackend(preset)
    if backend == "sentence_transformers":
        return SentenceTransformerBackend(preset)
    raise ValueError(
        f"未知的 EMBEDDING_BACKEND：{backend}"
        "（可用值：auto / flagembedding / sentence_transformers）"
    )


def embed_texts_sync(
    model: EmbeddingBackend, texts: list[str], *, is_query: bool = False
) -> list[list[float]]:
    """將文字批次轉為稠密向量（同步、阻塞）。

    Args:
        model: `load_embedding_model()` 取得的後端實例。
        texts: 待編碼文字。
        is_query: True 表示這批文字是「查詢」（套用查詢前綴）；
            False 表示是「入庫的被檢索文件」（套用文件前綴）。
            非對稱模型（E5、Qwen3、bge-zh）用錯會顯著掉分。
    """
    return model.encode(texts, is_query=is_query)


def collection_dimension(collection) -> int | None:
    """取得 ChromaDB 集合中既有向量的維度；空集合回傳 None。"""
    if collection.count() == 0:
        return None
    peeked = collection.peek(limit=1)
    embeddings = peeked.get("embeddings")
    if embeddings is None or len(embeddings) == 0:
        return None
    return len(embeddings[0])


def check_collection_dimension(collection, model: EmbeddingBackend) -> None:
    """檢查 ChromaDB 集合的向量維度是否與目前模型相符，不符則直接報錯。

    換嵌入模型做 A/B 時最容易踩的坑：沿用舊集合會在查詢時才爆出難懂的錯誤，
    或（維度剛好相同時）靜默地拿兩套不相容的向量空間做比對，得到無意義的
    相似度。故在啟動階段就擋下來。

    Raises:
        ValueError: 集合既有維度與目前模型輸出維度不符。
    """
    existing = collection_dimension(collection)
    if existing is None:
        return  # 空集合：接下來寫入什麼維度都可以

    current = model.dimension
    if existing != current:
        raise ValueError(
            f"ChromaDB 集合 `{settings.CHROMA_COLLECTION}` 既有向量維度為 {existing}，"
            f"但目前模型 `{settings.EMBEDDING_MODEL}` 輸出 {current} 維。"
            "更換嵌入模型後必須重建向量庫："
            "請改用新的 CHROMA_COLLECTION 名稱（建議每個模型一個集合以便 A/B 比較），"
            "或刪除 CHROMA_DIR 後重跑 rag_worker.py 全量入庫。"
        )


def suggested_collection_name(base: str, model_name: str) -> str:
    """依模型名稱產生建議的集合名稱（如 `scam_messages__qwen3_embedding_0_6b`）。

    A/B 比較時每個模型各自一個集合，可並存、免重複入庫、切換 `.env` 即可比較。
    """
    slug = re.sub(r"[^a-z0-9]+", "_", model_name.lower()).strip("_")
    return f"{base}__{slug}"
