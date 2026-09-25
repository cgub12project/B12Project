"""RAG 向量入庫程式（獨立執行，與 FastAPI 後端分開的長駐程序）。

功能：
1. 啟動時讀取 training_data.jsonl（JSON Lines，每行一筆
   {"id", "text", "metadata": {"is_scam", "scam_type", ...}}），
   將詐騙（is_scam=1）與一般（is_scam=0）樣本全數
   以嵌入模型（EMBEDDING_MODEL，預設 BGE-M3；GPU 加速）將 text 轉為稠密向量，
   連同原文、scam_type 與 is_scam 標籤存入本地 ChromaDB 向量資料庫
   （偵測端閘門依 metadata.is_scam 區分詐騙／一般案例）。
2. 之後常駐執行：每分鐘透過後端 API（GET /api/v1/rag/reports）
   查詢有無新的使用者詐騙回報，有則以相同方式向量化入庫。

冪等設計：
- 所有向量以「確定性 ID」upsert（訓練資料：train-{資料 id}；
  使用者回報：report-{來源表}-{紀錄 ID}），程式重啟或資料重複回傳皆不會產生重複向量。

執行方式：
    python rag_worker.py
（設定值讀取 .env，見 app/core/config.py 的 RAG 區段）
"""

import argparse
import asyncio
import hashlib
import json
import logging
import signal
import sys
from datetime import datetime
from pathlib import Path

import httpx

from app.core.config import settings
from app.services.embedding import (
    check_collection_dimension,
    embed_texts_sync,
    load_embedding_model,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [rag_worker] %(message)s",
)
logger = logging.getLogger("rag_worker")

# 單批嵌入＋寫入的筆數上限：避免大量入庫時單次寫入超過 ChromaDB 批次上限，
# 也讓長時間的 GPU 編碼過程有進度日誌可觀察
UPSERT_CHUNK_SIZE = 1000


class RagWorker:
    """RAG 向量入庫工作程序。"""

    def __init__(self) -> None:
        self._model = None  # 嵌入模型後端（EMBEDDING_MODEL）
        self._collection = None  # ChromaDB 集合
        self._stop_event = asyncio.Event()  # 優雅停止旗標
        self._state_path = Path(settings.RAG_WORKER_STATE_PATH)

    # ------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------

    def setup(self) -> None:
        """載入嵌入模型（GPU）並連線 ChromaDB（同步、僅啟動時執行一次）。"""
        import chromadb

        logger.info(
            "正在載入嵌入模型 %s（首次執行會自動下載模型檔）...",
            settings.EMBEDDING_MODEL,
        )
        self._model = load_embedding_model()

        logger.info("正在連線本地 ChromaDB（目錄：%s）...", settings.CHROMA_DIR)
        client = chromadb.PersistentClient(path=settings.CHROMA_DIR)
        # 與後端偵測端點共用同一集合，統一採用餘弦距離
        self._collection = client.get_or_create_collection(
            name=settings.CHROMA_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        # 換嵌入模型後若沿用舊集合，維度不符會在此直接報錯（而非寫入不相容的向量）
        check_collection_dimension(self._collection, self._model)
        logger.info(
            "ChromaDB 就緒（集合：%s，現有向量數：%s）",
            settings.CHROMA_COLLECTION,
            self._collection.count(),
        )

    # ------------------------------------------------------------
    # 同步狀態檔（記錄上次輪詢時間點）
    # ------------------------------------------------------------

    def _load_last_sync(self) -> str | None:
        """讀取上次同步時間點（ISO 8601 字串）；首次執行回傳 None。"""
        try:
            state = json.loads(self._state_path.read_text(encoding="utf-8"))
            return state.get("last_sync")
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def _save_last_sync(self, server_time: str) -> None:
        """儲存本次同步時間點（使用伺服器時間，避免本機時鐘偏差）。"""
        self._state_path.write_text(
            json.dumps({"last_sync": server_time}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ------------------------------------------------------------
    # 向量入庫（共用）
    # ------------------------------------------------------------

    def _upsert_sync(
        self,
        ids: list[str],
        contents: list[str],
        scam_types: list[str],
        is_scam_flags: list[bool],
    ) -> None:
        """將文字分批向量化後 upsert 至 ChromaDB（同步；於執行緒中呼叫）。

        除向量外，同時儲存原文（documents）與 scam_type、is_scam（metadata）。
        以 UPSERT_CHUNK_SIZE 分批處理，避免單次寫入超過 ChromaDB 批次上限。
        """
        total = len(ids)
        for start in range(0, total, UPSERT_CHUNK_SIZE):
            end = min(start + UPSERT_CHUNK_SIZE, total)
            # is_query=False：入庫的是「被檢索文件」，非對稱模型須套用文件側前綴
            embeddings = embed_texts_sync(
                self._model, contents[start:end], is_query=False
            )
            self._collection.upsert(
                ids=ids[start:end],
                embeddings=embeddings,
                documents=contents[start:end],
                metadatas=[
                    {"scam_type": scam_type, "is_scam": flag}
                    for scam_type, flag in zip(
                        scam_types[start:end], is_scam_flags[start:end]
                    )
                ],
            )
            if total > UPSERT_CHUNK_SIZE:
                logger.info("入庫進度：%s / %s", end, total)

    # ------------------------------------------------------------
    # 步驟一：訓練資料初始入庫
    # ------------------------------------------------------------

    async def ingest_training_data(self, prune: bool = False) -> None:
        """讀取 training_data.jsonl 並將全部樣本向量化入庫（確定性 ID，可重複執行）。

        檔案為 JSON Lines 格式：每行一筆
        {"id", "text", "metadata": {"is_scam", "scam_type", ...}}。
        詐騙（is_scam=1）與一般（is_scam=0）樣本皆入庫，
        並於 metadata 儲存 is_scam 標籤，供偵測端閘門區分
        「與詐騙案例高相似 → 高風險」與「與一般訊息高相似 → 安全」。

        Args:
            prune: 一併刪除訓練資料檔中已不存在的 train-* 向量（見
                `_prune_removed_sync`）。常駐模式預設關閉，避免訓練資料檔
                一時讀取不完整就把線上向量刪掉；手動重新同步時才開啟。
        """
        path = Path(settings.TRAINING_DATA_PATH)
        if not path.exists():
            logger.warning("找不到訓練資料檔 %s，略過初始入庫", path)
            return

        ids: list[str] = []
        contents: list[str] = []
        scam_types: list[str] = []
        is_scam_flags: list[bool] = []
        seen_ids: set[str] = set()
        total_lines = 0
        skipped_invalid_label = 0
        with path.open(encoding="utf-8") as file:
            for line_no, line in enumerate(file, start=1):
                line = line.strip()
                if not line:
                    continue
                total_lines += 1
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    logger.warning("第 %s 行 JSON 解析失敗，已略過：%s", line_no, exc)
                    continue

                metadata = record.get("metadata") or {}
                is_scam = metadata.get("is_scam")
                if is_scam not in (0, 1):
                    skipped_invalid_label += 1
                    logger.warning(
                        "第 %s 行 is_scam 標籤無效（%r），已略過", line_no, is_scam
                    )
                    continue

                content = (record.get("text") or "").strip()
                if not content:
                    logger.warning("第 %s 行缺少 text，已略過", line_no)
                    continue

                # 確定性 ID：優先採用資料本身的唯一 id（重跑程式不會重複入庫），
                # 缺 id 時退回「行號 + 內容雜湊」
                record_id = str(record.get("id") or "").strip()
                if not record_id:
                    digest = hashlib.md5(content.encode("utf-8")).hexdigest()[:8]
                    record_id = f"line{line_no}-{digest}"
                vector_id = f"train-{record_id}"
                if vector_id in seen_ids:
                    logger.warning("第 %s 行 id 重複（%s），已略過", line_no, record_id)
                    continue
                seen_ids.add(vector_id)

                if is_scam == 1:
                    scam_type = str(metadata.get("scam_type") or "").strip()
                    # 資料中的 unknown / none 統一正規化為「未知」，維持提示詞用語一致
                    if scam_type.lower() in ("", "unknown", "none"):
                        scam_type = "未知"
                else:
                    # 一般樣本統一標為「非詐騙」，提示詞與偵測回應可直接呈現
                    scam_type = "非詐騙"

                ids.append(vector_id)
                contents.append(content)
                scam_types.append(scam_type)
                is_scam_flags.append(bool(is_scam))

        if not ids:
            logger.warning("訓練資料無有效樣本，略過初始入庫")
            return

        scam_count = sum(is_scam_flags)
        logger.info(
            "訓練資料共 %s 行，取得詐騙樣本 %s 筆、一般樣本 %s 筆"
            "（略過無效標籤 %s 筆），開始向量化（BGE-M3，GPU 批次編碼）...",
            total_lines,
            scam_count,
            len(ids) - scam_count,
            skipped_invalid_label,
        )
        # 嵌入為阻塞的 GPU 運算，移至執行緒執行
        await asyncio.to_thread(
            self._upsert_sync, ids, contents, scam_types, is_scam_flags
        )

        if prune:
            await asyncio.to_thread(self._prune_removed_sync, seen_ids)

        logger.info(
            "訓練資料入庫完成，集合現有向量數：%s", self._collection.count()
        )

    def _prune_removed_sync(self, current_ids: set[str]) -> None:
        """刪除訓練資料檔中已不存在的 train-* 向量（同步；於執行緒中呼叫）。

        upsert 只會新增與覆寫，不會刪除。若從訓練資料移除了一筆條目（例如經
        kb_label_audit.py 判定為不適合檢索的污染樣本），舊向量會留在 ChromaDB
        裡繼續被檢索到——修正等於沒做。因此提供這個對帳步驟。

        只清理 train-* 前綴的向量：report-* 來自使用者回報，不在訓練資料檔中，
        絕不能被這裡誤刪。
        """
        existing = self._collection.get(include=[])["ids"]
        stale = [i for i in existing if i.startswith("train-") and i not in current_ids]
        if not stale:
            logger.info("對帳完成：沒有需要清除的過期向量")
            return
        self._collection.delete(ids=stale)
        logger.info("已清除 %s 筆訓練資料檔中已不存在的向量：%s",
                    len(stale), stale[:5])

    # ------------------------------------------------------------
    # 步驟二：每分鐘輪詢使用者回報
    # ------------------------------------------------------------

    async def poll_new_reports(self, client: httpx.AsyncClient) -> None:
        """向後端 API 查詢新的使用者回報，有則向量化入庫。"""
        last_sync = self._load_last_sync()
        params: dict[str, str] = {}
        if last_sync:
            params["since"] = last_sync

        # 呼叫後端內部端點（X-API-Key 驗證）
        response = await client.get(
            f"{settings.RAG_BACKEND_URL}{settings.API_V1_PREFIX}/rag/reports",
            params=params,
            headers={"X-API-Key": settings.RAG_API_KEY},
        )
        response.raise_for_status()
        data = response.json()

        items = data.get("items", [])
        if items:
            # 確定性 ID：report-{來源表}-{紀錄 ID}，upsert 保證冪等
            ids = [f"report-{item['source']}-{item['id']}" for item in items]
            contents = [item["content"] for item in items]
            scam_types = [item.get("scam_type") or "未知" for item in items]

            logger.info("收到 %s 筆新回報，開始向量化入庫...", len(items))
            # 使用者回報一律為詐騙案例
            await asyncio.to_thread(
                self._upsert_sync, ids, contents, scam_types, [True] * len(items)
            )
            logger.info("入庫完成，集合現有向量數：%s", self._collection.count())
        else:
            logger.info("本次輪詢無新回報")

        # 以伺服器時間為下次查詢起點（避免本機時鐘偏差漏資料）
        server_time = data.get("server_time")
        if server_time:
            self._save_last_sync(server_time)

    async def run_polling_loop(self) -> None:
        """常駐輪詢主迴圈：每 RAG_POLL_INTERVAL_SECONDS 秒查詢一次。"""
        logger.info(
            "進入輪詢模式：每 %s 秒查詢一次使用者回報（後端：%s）",
            settings.RAG_POLL_INTERVAL_SECONDS,
            settings.RAG_BACKEND_URL,
        )
        async with httpx.AsyncClient(timeout=30) as client:
            while not self._stop_event.is_set():
                try:
                    await self.poll_new_reports(client)
                except httpx.HTTPError as exc:
                    # 後端暫時不可用不中斷程式，下一輪重試
                    logger.error("輪詢失敗（將於下一輪重試）：%s", exc)
                except Exception:
                    logger.exception("輪詢發生未預期錯誤（將於下一輪重試）")

                # 等待下一輪；收到停止訊號時立即結束等待
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=settings.RAG_POLL_INTERVAL_SECONDS,
                    )
                except asyncio.TimeoutError:
                    pass  # 正常逾時 → 進入下一輪

    def request_stop(self) -> None:
        """要求優雅停止（由訊號處理器呼叫）。"""
        logger.info("收到停止訊號，將於本輪結束後關閉...")
        self._stop_event.set()


async def main() -> None:
    """程式進入點：初始化 → 訓練資料入庫 → 常駐輪詢。"""
    parser = argparse.ArgumentParser(description="RAG 向量入庫程序")
    parser.add_argument(
        "--once", action="store_true",
        help="只做一次訓練資料入庫就結束，不進入常駐輪詢（改完訓練資料重新同步用）",
    )
    parser.add_argument(
        "--prune", action="store_true",
        help="一併刪除訓練資料檔中已不存在的 train-* 向量（upsert 不會刪除舊向量）",
    )
    args = parser.parse_args()

    worker = RagWorker()

    # 註冊 Ctrl+C / SIGTERM 優雅停止（Windows 僅支援 SIGINT）
    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, worker.request_stop)
    except NotImplementedError:
        # Windows 事件迴圈不支援 add_signal_handler，改由 KeyboardInterrupt 處理
        pass

    # 模型載入為重度阻塞操作，移至執行緒執行
    await asyncio.to_thread(worker.setup)
    await worker.ingest_training_data(prune=args.prune)
    if args.once:
        logger.info("--once：入庫完成，不進入輪詢")
        return
    await worker.run_polling_loop()
    logger.info("RAG Worker 已停止")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("RAG Worker 已由使用者中斷")
        sys.exit(0)
