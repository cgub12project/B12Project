"""詐騙偵測準確度評測腳本。

以帶標籤的測試集（test.jsonl）評估 RAG 詐騙偵測系統的二元判斷準確度。
直接呼叫 RagService.detect()（繞過 HTTP 與登入驗證），逐筆將 text 送入偵測，
並把預測的 is_scam 與資料中的標準答案（is_scam 0/1）比對，輸出混淆矩陣、
準確率 / 精確率 / 召回率 / F1，以及「相似度閘門 vs LLM」各判定多少筆。

前置條件（與正式偵測相同的執行環境）：
1. ChromaDB 向量庫已入庫（先跑 rag_worker.py 將 training_data.jsonl 入庫）
2. Ollama 已啟動且已下載 OLLAMA_MODEL（落在相似度區間內的訊息才會呼叫）
3. 已安裝 RAG 相依套件（torch / FlagEmbedding / chromadb），建議有 CUDA GPU

測試集格式（每行一筆 JSON）：
    {"id": ..., "text": "訊息內容", "is_scam": 0 或 1, "scam_type": "...", ...}

用法：
    python -m scripts.eval_scam_detection                     # 跑完整 test.jsonl
    python -m scripts.eval_scam_detection --limit 100         # 只跑前 100 筆（快速煙霧測試）
    python -m scripts.eval_scam_detection --concurrency 8     # 併發數（預設 4）
    python -m scripts.eval_scam_detection --input test.jsonl --out results.jsonl

────────────────────────────────────────────────────────────────────────
有無 RAG 的 A/B 比較（--no-rag / --rag）
────────────────────────────────────────────────────────────────────────
`--no-rag` 會就地覆寫 settings.RAG_ENABLED=false，跳過嵌入、向量檢索與相似度閘門，
直接以無 RAG 契約的提示詞呼叫 LLM（不需 GPU 與 ChromaDB），與 .env 改設定等價。

⚠ 兩邊各自要搭配對應的微調模型，比較才有意義：有 RAG 的那版模型是看著相似案例
  訓練出來的，若在無案例的輸入下評測，等於讓它面對訓練分布外的輸入，掉分並非
  「RAG 有用」的證據。請用 --ollama-model 指定各自的版本：

    python -m scripts.eval_scam_detection --limit 300 --rag    --ollama-model flash_v3
    python -m scripts.eval_scam_detection --limit 300 --no-rag --ollama-model flash_v3_norag

報表開頭固定印出當次生效的 EMBEDDING_MODEL / OLLAMA_MODEL / RAG_ENABLED，
結果檔亦不會與別次設定混淆。

────────────────────────────────────────────────────────────────────────
門檻掃描模式（--sweep）：更換嵌入模型後重新校準相似度門檻
────────────────────────────────────────────────────────────────────────
`RAG_GATE_TOP_N` / `RAG_GATE_SIMILARITY` 決定一致性閘門的行為；換嵌入模型後
餘弦分佈整體平移，沿用舊值會讓閘門的覆蓋率與準確率一起走樣。本模式會掃描
(N, x) 網格並找出最佳組合。

  N（投票人數）是主要變因，x（相似度門檻）幾乎是擺設——實測 x 從 0.25 掃到
  0.45 只讓 F1 動 0.003，N 從 2 換到 3 卻動 0.006。所以換模型時 x 可以放心
  沿用，N 建議重掃確認。

關鍵設計 — 為何掃描很快：
    檢索結果與 LLM 提示詞**只**取決於 `RAG_CASE_*` 設定，與閘門參數無關
    （見 rag_service.detect()：_split_cases 用 RAG_CASE_SIMILARITY_THRESHOLD，
    _similarity_gate 用 RAG_GATE_*，兩者互不影響）。因此：
      階段一（昂貴，每筆各做一次）：嵌入檢索 + LLM 推論，結果快取起來
      階段二（便宜，純 CPU）：對每組門檻重播 RagService._similarity_gate()，
                              閘門放行時改用階段一快取的 LLM 判定
    因此掃描上千組門檻的結果與「每組都完整重跑一次」完全等價，但只需一次推論成本。

    ⚠ 此等價性僅適用於 RAG_GATE_* 兩個閘門參數。若要改 `RAG_CASE_SIMILARITY_THRESHOLD`
      或 `RAG_CASE_MAX_PER_GROUP`，LLM 提示詞會改變，快取失效，必須重跑階段一
      （刪除 --cache 檔或換一個檔名）。

用法：
    # 完整掃描（需 Ollama；階段一每筆各呼叫一次 LLM，較慢但結果精確）
    python -m scripts.eval_scam_detection --sweep --limit 300

    # 只比較嵌入模型的檢索品質，不需 Ollama（閘門放行的樣本不列入指標，另計覆蓋率）
    python -m scripts.eval_scam_detection --sweep --sweep-no-llm

    # 階段一結果快取後，改網格重掃是瞬間完成的（不需 GPU/Ollama）
    python -m scripts.eval_scam_detection --sweep --cache cache_bgem3.jsonl --sweep-n-max 15

────────────────────────────────────────────────────────────────────────
嵌入模型比較（--embedding-model / --no-gate / --case-threshold）
────────────────────────────────────────────────────────────────────────
比較不同嵌入模型時，同一份測試集要在「其他條件完全相同」下各跑一次：

    python -m scripts.eval_scam_detection --no-gate --case-threshold 0 \
        --embedding-model Qwen/Qwen3-Embedding-0.6B \
        --summary-json eval/summary_qwen3_0_6b.json

`--no-gate` 把相似度閘門讓開（LOW=0.0、HIGH=1.0），每一筆都交給 LLM 判定。
檢索仍照跑、相似案例照樣注入提示詞——嵌入模型正是透過「注入哪幾筆案例」
影響準確率的，關掉檢索就什麼都比不出來了。

`--case-threshold 0` 是公平比較的關鍵：注入門檻是絕對相似度，而各模型的餘弦
尺度差很多（Qwen3 明顯比 BGE-M3 壓縮），沿用同一個 0.7 會讓尺度被壓縮的模型
大量注不進案例，量到的是尺度差異而不是檢索品質。設為 0 改成純排名制：
每筆固定注入最相似的 top-3 詐騙 + top-3 正常案例。

⚠ 每個嵌入模型需要各自的向量庫（維度與向量空間都不同）。`--embedding-model`
  會自動改用 `suggested_collection_name()` 產生的集合名稱，該集合須先入庫：
      EMBEDDING_MODEL=<model> CHROMA_COLLECTION=<collection> python rag_worker.py --once
  整套流程（建庫 → 評測 → 比較表）已包成 scripts/compare_embedding_models.py。
"""

import argparse
import asyncio
import csv
import json
import sys
import time
from pathlib import Path

from app.core.config import settings
from app.schemas.rag import SimilarCase
from app.services.embedding import suggested_collection_name
from app.services.rag_service import (
    SIMILARITY_GATE_MODEL,
    RagService,
    RagUnavailableError,
    rag_service,
)

# 路徑錨定於專案根目錄，預設值不受執行時的工作目錄影響
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
EVAL_DIR = PROJECT_ROOT / "eval"


def gate_disabled() -> bool:
    """一致性閘門是否已被讓開（每筆都會走到 LLM）。

    `_similarity_gate` 要求 N 筆候選**嚴格大於** RAG_GATE_SIMILARITY，而餘弦
    相似度落在 [0, 1]，故門檻設為 1.0 時沒有任何候選能通過，等同關閉閘門。
    """
    return settings.RAG_GATE_SIMILARITY >= 1.0


# ==========================================================================
# 耗時量測
# ==========================================================================


class Timings:
    """累計評測各階段的耗時（比較嵌入模型時，速度與準確率一樣是決策依據）。

    併發數 1 時為單執行緒累加，不需鎖；併發數 >1 時「檢索 vs LLM」的拆分只是
    概估（各筆時間會重疊），總時間與準確率不受影響。
    """

    def __init__(self) -> None:
        self.model_load_seconds = 0.0  # 嵌入模型載入 + 向量庫暖機
        self.retrieval_seconds = 0.0  # 嵌入查詢 + ChromaDB 檢索（累計）
        self.retrieval_calls = 0
        self.wall_seconds = 0.0  # 評測迴圈的實際牆鐘時間
        self.embedding_dimension: int | None = None
        # 最近一次檢索的耗時，供 eval_one 記進該筆結果（併發數 1 時對應關係精確；
        # 逐筆存下來，續跑後才算得出跨多次執行的總耗時）
        self.last_retrieval_seconds = 0.0


def instrument_retrieval(timings: Timings) -> None:
    """在偵測路徑上掛一層計時，量出「嵌入 + 向量檢索」實際佔掉多少時間。

    以實例屬性覆寫 `_query_similar_sync`（`detect()` 走 `self.…`，會先找到實例
    屬性），量到的就是正式流程真正跑的那一次檢索——不必為了計時額外多跑一次
    推論，也不必改動 rag_service 的正式程式碼。
    """
    original = rag_service._query_similar_sync

    def timed(message: str) -> list[SimilarCase]:
        start = time.perf_counter()
        try:
            return original(message)
        finally:
            elapsed = time.perf_counter() - start
            timings.last_retrieval_seconds = elapsed
            timings.retrieval_seconds += elapsed
            timings.retrieval_calls += 1

    rag_service._query_similar_sync = timed


async def warmup(timings: Timings) -> None:
    """先載入嵌入模型與向量庫，把載入耗時與逐筆偵測的耗時分開計。

    不先暖機的話，模型載入（BGE-M3 約 15 秒、更大的模型更久）會全部算到第一筆
    樣本頭上，逐筆平均就失真了。
    """
    if not settings.RAG_ENABLED:
        return
    start = time.perf_counter()
    await asyncio.to_thread(rag_service._ensure_ready_sync)
    timings.model_load_seconds = time.perf_counter() - start
    timings.embedding_dimension = rag_service._model.dimension
    print(
        f"嵌入模型就緒：{settings.EMBEDDING_MODEL}"
        f"（{timings.embedding_dimension} 維，載入 {timings.model_load_seconds:.1f}s）"
    )


def print_active_config() -> None:
    """印出本次評測實際生效的設定，讓報表能自我標示是哪個組態跑出來的。

    有無 RAG 的 A/B 需同時對上「RAG 開關」與「微調模型版本」，兩者若不匹配數字
    就沒有意義；固定印出來可避免事後對不上是哪一組結果。
    """
    print("─" * 52)
    print(f"  RAG_ENABLED      {settings.RAG_ENABLED}")
    print(f"  OLLAMA_MODEL     {settings.OLLAMA_MODEL}")
    if settings.RAG_ENABLED:
        print(f"  EMBEDDING_MODEL  {settings.EMBEDDING_MODEL}")
        print(f"  CHROMA_COLLECTION {settings.CHROMA_COLLECTION}")
        gate_note = "（閘門讓開，全部交由 LLM）" if gate_disabled() else ""
        print(
            f"  一致性閘門        top_n={settings.RAG_GATE_TOP_N} "
            f"sim>{settings.RAG_GATE_SIMILARITY} {gate_note}"
        )
        print(f"  案例注入門檻      {settings.RAG_CASE_SIMILARITY_THRESHOLD}")
    else:
        print("  （無 RAG 模式：不檢索、不走相似度閘門，全部樣本交由 LLM 判定）")
    print("─" * 52)


def load_dataset(
    path: Path, limit: int | None, exclude_unverified: bool = False
) -> list[dict]:
    """讀取 JSON Lines 測試集，只保留有 text 與 is_scam 標籤的資料列。

    `exclude_unverified` 會濾掉 clean_labels.py 標為 unverified 的樣本——那些是
    label_source=category 且 scam_type=unknown 的資料列，被機械標成詐騙卻連類型
    都指不出來，實際混了大量反詐騙提醒、官方行銷與純謠言。留著它們算出來的準確率
    是在獎勵「愛喊詐騙」的模型，不反映真實判斷力。
    """
    rows: list[dict] = []
    skipped = 0
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if not row.get("text") or "is_scam" not in row:
                continue
            if exclude_unverified and row.get("label_tier") == "unverified":
                skipped += 1
                continue
            rows.append(row)
            if limit and len(rows) >= limit:
                break

    if exclude_unverified:
        if skipped:
            print(f"已排除 {skipped} 筆 label_tier=unverified 的存疑樣本")
        elif not any("label_tier" in row for row in rows):
            print(
                f"⚠ {path} 沒有 label_tier 欄位，--exclude-unverified 未濾掉任何樣本；"
                "請先跑 clean_labels.py 產生 .clean.jsonl"
            )
    return rows


async def eval_one(
    row: dict, sem: asyncio.Semaphore, timings: Timings | None = None
) -> dict:
    """偵測單筆訊息，回傳含預測與標準答案的結果列（失敗以 error 標記）。"""
    async with sem:
        expected = int(row["is_scam"])  # 標準答案：1=詐騙、0=正常
        start = time.perf_counter()
        try:
            result = await rag_service.detect(row["text"])
        except RagUnavailableError as exc:
            return {"id": row.get("id"), "expected": expected, "error": str(exc)}
        elapsed = time.perf_counter() - start

        predicted = int(result.is_scam)
        return {
            "id": row.get("id"),
            "text": row["text"][:120],
            "expected": expected,
            "predicted": predicted,
            "correct": predicted == expected,
            "risk_level": result.risk_level,
            "pred_scam_type": result.scam_type,
            "true_scam_type": row.get("scam_type"),
            "confidence": result.confidence,
            # similarity-gate 表示未呼叫 LLM，由相似度閘門直接判定
            "decided_by": "gate" if result.model == SIMILARITY_GATE_MODEL else "llm",
            "elapsed": round(elapsed, 4),  # 該筆偵測耗時（檢索 + LLM）
            "retrieval_elapsed": (
                round(timings.last_retrieval_seconds, 4) if timings else None
            ),
        }


async def run(
    rows: list[dict],
    concurrency: int,
    timings: Timings | None = None,
    sink=None,
) -> list[dict]:
    """併發跑完整個測試集，附帶簡易進度輸出。

    `sink` 為已開啟的輸出檔；每完成一筆就寫入並 flush，行程被中斷時已跑完的部分
    不會消失（搭配 `--resume` 可接續）。整批跑完才一次寫出，代表任何中斷都會
    賠掉整段推論——這個評測動輒一小時起跳，賠不起。
    """
    sem = asyncio.Semaphore(concurrency)
    tasks = [asyncio.create_task(eval_one(row, sem, timings)) for row in rows]

    results: list[dict] = []
    total = len(tasks)
    start = time.perf_counter()
    for done in asyncio.as_completed(tasks):
        result = await done
        results.append(result)
        if sink is not None:
            sink.write(json.dumps(result, ensure_ascii=False) + "\n")
            sink.flush()
        n = len(results)
        if n % 25 == 0 or n == total:
            elapsed = time.perf_counter() - start
            rate = n / elapsed if elapsed else 0
            eta = (total - n) / rate if rate else 0
            print(
                f"  進度 {n}/{total}  {rate:.1f} 筆/秒  ETA {eta:.0f}s",
                end="\r",
                flush=True,
            )
    print()
    if timings is not None:
        timings.wall_seconds = time.perf_counter() - start
    return results


def compute_metrics(pairs: list[tuple[int, int]]) -> dict:
    """由 (標準答案, 預測) 序對計算混淆矩陣與各項指標（正類 = 詐騙 is_scam=1）。"""
    tp = sum(1 for expected, predicted in pairs if expected == 1 and predicted == 1)
    fn = sum(1 for expected, predicted in pairs if expected == 1 and predicted == 0)
    fp = sum(1 for expected, predicted in pairs if expected == 0 and predicted == 1)
    tn = sum(1 for expected, predicted in pairs if expected == 0 and predicted == 0)
    n = len(pairs)

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0  # 抓到多少比例的真詐騙
    return {
        "tp": tp,
        "fn": fn,
        "fp": fp,
        "tn": tn,
        "n": n,
        "accuracy": (tp + tn) / n if n else 0.0,
        "precision": precision,
        "recall": recall,
        # 正常訊息不被誤判的比例
        "specificity": tn / (tn + fp) if (tn + fp) else 0.0,
        "f1": (
            2 * precision * recall / (precision + recall)
            if (precision + recall)
            else 0.0
        ),
    }


def compute_time_breakdown(results: list[dict], timings: Timings) -> dict:
    """把總耗時拆成「檢索」與「LLM 推論」兩段，回傳可直接寫進報表與 JSON 的欄位。

    檢索時間由 `instrument_retrieval()` 實測累加；LLM 時間以「逐筆偵測總時間
    扣掉檢索」推得——LLM 沒有另外掛計時點，而這兩段本來就構成 detect() 的全部。
    """
    ok = [r for r in results if "error" not in r]
    detect_seconds = sum(r.get("elapsed", 0.0) for r in ok)
    llm_rows = [r for r in ok if r["decided_by"] == "llm"]

    # 優先用逐筆記下的檢索耗時：續跑時本次行程的累加器只涵蓋新跑的那些筆，
    # 逐筆值則涵蓋結果檔裡的全部樣本
    per_row = [
        r["retrieval_elapsed"] for r in ok if r.get("retrieval_elapsed") is not None
    ]
    if per_row:
        retrieval_seconds = sum(per_row)
        retrieval_calls = len(per_row)
    else:
        retrieval_seconds = timings.retrieval_seconds
        retrieval_calls = timings.retrieval_calls
    llm_seconds = max(detect_seconds - retrieval_seconds, 0.0)

    return {
        "model_load_seconds": round(timings.model_load_seconds, 2),
        "embedding_dimension": timings.embedding_dimension,
        "wall_seconds": round(timings.wall_seconds, 2),
        "detect_seconds": round(detect_seconds, 2),
        "retrieval_seconds": round(retrieval_seconds, 2),
        "retrieval_calls": retrieval_calls,
        "retrieval_ms_per_call": (
            round(retrieval_seconds / retrieval_calls * 1000, 2)
            if retrieval_calls
            else None
        ),
        "llm_seconds": round(llm_seconds, 2),
        "llm_calls": len(llm_rows),
        "llm_seconds_per_call": (
            round(llm_seconds / len(llm_rows), 3) if llm_rows else None
        ),
        "seconds_per_sample": (
            round(detect_seconds / len(ok), 3) if ok else None
        ),
    }


def print_time_breakdown(breakdown: dict) -> None:
    """印出耗時明細。"""
    print("耗時")
    print(
        f"  嵌入模型載入         {breakdown['model_load_seconds']:>8.1f} s"
        f"   （{breakdown['embedding_dimension']} 維）"
    )
    if breakdown["retrieval_ms_per_call"] is not None:
        print(
            f"  檢索（嵌入+向量查詢） {breakdown['retrieval_ms_per_call']:>8.1f} ms/筆"
            f"  合計 {breakdown['retrieval_seconds']:.1f} s"
            f"（{breakdown['retrieval_calls']} 次）"
        )
    if breakdown["llm_seconds_per_call"] is not None:
        print(
            f"  LLM 推論             {breakdown['llm_seconds_per_call']:>8.2f} s/筆"
            f"  合計 {breakdown['llm_seconds']:.1f} s"
            f"（{breakdown['llm_calls']} 次）"
        )
    print(
        f"  評測總時間           {breakdown['wall_seconds'] / 60:>8.1f} 分"
        f"   （平均 {breakdown['seconds_per_sample']} s/筆）"
    )
    print("=" * 52)


def report(results: list[dict], timings: Timings | None = None) -> None:
    """依結果計算並印出混淆矩陣與各項指標。"""
    errors = [r for r in results if "error" in r]
    ok = [r for r in results if "error" not in r]

    if errors:
        print(f"\n⚠  {len(errors)} 筆偵測失敗（例如 Ollama / 向量庫未就緒）：")
        print(f"   例：{errors[0]['error']}")

    if not ok:
        print("\n沒有任何成功的偵測結果，無法計算指標。請確認前置條件是否就緒。")
        return

    metrics = compute_metrics([(r["expected"], r["predicted"]) for r in ok])
    tp, fn, fp, tn, n = (
        metrics["tp"],
        metrics["fn"],
        metrics["fp"],
        metrics["tn"],
        metrics["n"],
    )
    accuracy = metrics["accuracy"]
    precision = metrics["precision"]
    recall = metrics["recall"]
    specificity = metrics["specificity"]
    f1 = metrics["f1"]

    print("\n" + "=" * 52)
    print(f"評測樣本數：{n}（成功）/ {len(results)}（總計）")
    print("=" * 52)
    print_active_config()
    print("混淆矩陣（正類 = 詐騙）")
    print(f"                    預測:詐騙   預測:正常")
    print(f"  實際:詐騙(1)         {tp:>6}      {fn:>6}")
    print(f"  實際:正常(0)         {fp:>6}      {tn:>6}")
    print("-" * 52)
    print(f"  準確率 Accuracy      {accuracy:.4f}")
    print(f"  精確率 Precision     {precision:.4f}  （判為詐騙中真的是詐騙）")
    print(f"  召回率 Recall        {recall:.4f}  （真詐騙有被抓到）")
    print(f"  特異度 Specificity   {specificity:.4f}  （正常訊息未被誤報）")
    print(f"  F1 分數              {f1:.4f}")
    print("-" * 52)

    # 判定來源分布：多少筆由相似度閘門直接決定、多少筆呼叫了 LLM
    by_gate = [r for r in ok if r["decided_by"] == "gate"]
    by_llm = [r for r in ok if r["decided_by"] == "llm"]
    gate_acc = (
        sum(r["correct"] for r in by_gate) / len(by_gate) if by_gate else 0
    )
    llm_acc = sum(r["correct"] for r in by_llm) / len(by_llm) if by_llm else 0
    print("判定來源")
    print(f"  相似度閘門直接判定   {len(by_gate):>5} 筆  準確率 {gate_acc:.4f}")
    print(f"  交由 LLM 判定        {len(by_llm):>5} 筆  準確率 {llm_acc:.4f}")
    print("-" * 52)

    if timings is not None:
        print_time_breakdown(compute_time_breakdown(results, timings))
    else:
        print("=" * 52)


# ==========================================================================
# 門檻掃描：階段一（收集可重複使用的檢索／LLM 快取）
# ==========================================================================


async def collect_one(row: dict, sem: asyncio.Semaphore, with_llm: bool) -> dict:
    """收集單筆的檢索候選與（可選的）LLM 判定，供後續離線掃描門檻。

    刻意「無論閘門是否會放行都呼叫一次 LLM」：掃描時任一組門檻只要讓這筆落入
    區間，就能直接取用此處快取的 LLM 判定，不必重新推論。
    """
    async with sem:
        expected = int(row["is_scam"])
        record: dict = {"id": row.get("id"), "text": row["text"][:120], "expected": expected}

        try:
            candidates = await asyncio.to_thread(
                rag_service._query_similar_sync, row["text"]
            )
        except RagUnavailableError as exc:
            return {**record, "error": f"檢索失敗：{exc}"}

        # 只留掃描階段用得到的欄位（content 不影響閘門判定，省下快取檔體積）
        record["candidates"] = [
            {
                "similarity": c.similarity,
                "is_scam": c.is_scam,
                "scam_type": c.scam_type,
            }
            for c in candidates
        ]

        if not with_llm:
            record["llm_is_scam"] = None
            return record

        # 重現 detect() 的 LLM 路徑：提示詞只受 RAG_CASE_* 影響，與掃描的門檻無關
        scam_cases, normal_cases = RagService._split_cases(candidates, row["text"])
        try:
            raw = await rag_service._ask_ollama(
                RagService._build_prompt(row["text"], scam_cases, normal_cases)
            )
        except RagUnavailableError as exc:
            return {**record, "llm_is_scam": None, "error": f"LLM 失敗：{exc}"}

        verdict = RagService._parse_llm_response(raw, candidates)
        record["llm_is_scam"] = int(verdict["is_scam"])
        return record


async def run_collect(
    rows: list[dict], concurrency: int, with_llm: bool
) -> list[dict]:
    """跑完階段一收集，附帶進度輸出。"""
    sem = asyncio.Semaphore(concurrency)
    tasks = [asyncio.create_task(collect_one(row, sem, with_llm)) for row in rows]

    records: list[dict] = []
    total = len(tasks)
    start = time.perf_counter()
    for done in asyncio.as_completed(tasks):
        records.append(await done)
        n = len(records)
        if n % 25 == 0 or n == total:
            elapsed = time.perf_counter() - start
            rate = n / elapsed if elapsed else 0
            eta = (total - n) / rate if rate else 0
            print(
                f"  收集 {n}/{total}  {rate:.1f} 筆/秒  ETA {eta:.0f}s",
                end="\r",
                flush=True,
            )
    print()
    return records


def load_cache(path: Path) -> list[dict]:
    """讀取階段一快取檔。"""
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def save_cache(path: Path, records: list[dict]) -> None:
    """寫出階段一快取檔。"""
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


# ==========================================================================
# 門檻掃描：階段二（離線重播閘門邏輯）
# ==========================================================================

# 掃描時未提供 LLM 判定（--sweep-no-llm）的樣本標記
DEFERRED = -1


def _replay_gate(candidates: list[SimilarCase], top_n: int, threshold: float) -> int | None:
    """以指定參數重播一致性閘門，回傳判定（1/0）；None 表示閘門放行給 LLM。

    直接呼叫正式的 `RagService._similarity_gate`（而非在此複製一份判斷邏輯），
    確保掃描出來的最佳參數與線上實際行為完全一致，不會因兩處邏輯走樣而失準。
    閘門讀取全域 settings，故以暫時覆寫的方式傳入參數（單執行緒掃描，安全）。
    """
    original = (settings.RAG_GATE_TOP_N, settings.RAG_GATE_SIMILARITY)
    settings.RAG_GATE_TOP_N = top_n
    settings.RAG_GATE_SIMILARITY = threshold
    try:
        verdict = RagService._similarity_gate(candidates)
    finally:
        (settings.RAG_GATE_TOP_N, settings.RAG_GATE_SIMILARITY) = original
    return None if verdict is None else int(verdict["is_scam"])


def _to_similar_cases(raw_candidates: list[dict]) -> list[SimilarCase]:
    """把快取的候選欄位還原成閘門所需的 SimilarCase（content 未參與閘門判定）。"""
    return [
        SimilarCase(
            content="",
            scam_type=c["scam_type"],
            similarity=c["similarity"],
            is_scam=c["is_scam"],
        )
        for c in raw_candidates
    ]


def sweep(
    records: list[dict], top_ns: list[int], thresholds: list[float], with_llm: bool
) -> list[dict]:
    """對門檻網格逐組計算指標。

    with_llm=True：閘門放行的樣本以快取的 LLM 判定計入，指標涵蓋全部樣本，
        與「每組門檻都完整重跑一次」等價。
    with_llm=False：閘門放行的樣本無判定可用，故排除在指標之外，僅計算
        「閘門自行判定的子集」並另外報告覆蓋率——用於比較嵌入模型的檢索品質，
        此時指標不可跨門檻直接比大小（分母不同），須連同覆蓋率一起看。
    """
    usable = [r for r in records if r.get("candidates") is not None]
    # 先把候選還原成 SimilarCase：網格內每組門檻都會用到，只轉一次
    prepared = [
        (
            r["expected"],
            _to_similar_cases(r["candidates"]),
            r.get("llm_is_scam") if r.get("llm_is_scam") is not None else DEFERRED,
        )
        for r in usable
    ]

    grid: list[dict] = []
    for top_n in top_ns:
        for threshold in thresholds:
            pairs: list[tuple[int, int]] = []
            gate_decided = 0
            gate_correct = 0
            for expected, candidates, llm_verdict in prepared:
                predicted = _replay_gate(candidates, top_n, threshold)
                if predicted is None:
                    # 票數不齊或兩類並存 → 交由 LLM
                    if not with_llm or llm_verdict == DEFERRED:
                        continue  # 無 LLM 判定可用，排除此樣本
                    predicted = llm_verdict
                else:
                    gate_decided += 1
                    gate_correct += predicted == expected
                pairs.append((expected, predicted))

            metrics = compute_metrics(pairs)
            metrics["top_n"] = top_n
            metrics["threshold"] = round(threshold, 4)
            metrics["gate_decided"] = gate_decided
            # 閘門自留那批的準確率：與整體準確率**分母不同**，不可直接比大小。
            # 它回答的是「閘門敢判的時候有多準」，是選擇性分類器的核心指標。
            metrics["gate_accuracy"] = (
                gate_correct / gate_decided if gate_decided else 0.0
            )
            metrics["llm_calls"] = len(prepared) - gate_decided
            # 閘門覆蓋率：越高代表越少樣本需要呼叫 LLM（延遲與算力成本越低）
            metrics["gate_coverage"] = (
                gate_decided / len(prepared) if prepared else 0.0
            )
            grid.append(metrics)
    return grid


def report_similarity_distribution(records: list[dict]) -> None:
    """印出詐騙／正常樣本各自的 top-1 相似度分佈。

    這是校準門檻最直接的依據：兩類分佈的重疊區間就是閘門該放行給 LLM 的地帶，
    分佈本身也能一眼看出換模型後相似度尺度整體平移了多少。
    """

    def percentiles(values: list[float]) -> str:
        if not values:
            return "（無樣本）"
        ordered = sorted(values)

        def at(q: float) -> float:
            return ordered[min(len(ordered) - 1, int(q * len(ordered)))]

        return (
            f"p05={at(0.05):.3f}  p25={at(0.25):.3f}  中位數={at(0.50):.3f}  "
            f"p75={at(0.75):.3f}  p95={at(0.95):.3f}"
        )

    scam_top1: list[float] = []
    normal_top1: list[float] = []
    for record in records:
        candidates = record.get("candidates")
        if not candidates:
            continue
        top1 = candidates[0]["similarity"]
        (scam_top1 if record["expected"] == 1 else normal_top1).append(top1)

    print("\n" + "=" * 74)
    print("top-1 相似度分佈（校準門檻的依據）")
    print("=" * 74)
    print(f"  詐騙樣本 ({len(scam_top1):>5} 筆)   {percentiles(scam_top1)}")
    print(f"  正常樣本 ({len(normal_top1):>5} 筆)   {percentiles(normal_top1)}")
    print(
        "  提示：兩類分佈重疊得很嚴重（實測中位數只差 0.08），所以單看相似度"
        "\n        分不出詐騙與正常——閘門的準確率是 top-N 一致性投票給的，"
        "\n        不是相似度門檻給的。x 只要落在兩類分佈的低位、讓票投得出來"
        "\n        即可，真正要調的是 N。"
    )


def report_sweep(
    grid: list[dict], with_llm: bool, min_precision: float, top_n: int
) -> None:
    """印出掃描結果：最佳門檻組合與 P/R 取捨表。"""
    if not grid:
        print("\n掃描網格為空，請檢查 --sweep-* 範圍設定。")
        return

    print("\n" + "=" * 74)
    print("門檻掃描結果" + ("" if with_llm else "（--sweep-no-llm：僅計閘門判定的子集）"))
    print("=" * 74)

    def show(title: str, rows: list[dict]) -> None:
        print(f"\n{title}")
        print(
            f"  {'N':>3} {'x':>6} │ {'F1':>7} {'準確率':>7} {'精確率':>7} "
            f"{'召回率':>7} {'特異度':>7} │ {'閘門覆蓋':>8} {'閘門準確':>8} "
            f"{'LLM呼叫':>7} {'樣本':>6}"
        )
        print("  " + "─" * 92)
        for r in rows:
            print(
                f"  {r['top_n']:>3} {r['threshold']:>6.2f} │ {r['f1']:>7.4f} "
                f"{r['accuracy']:>7.4f} {r['precision']:>7.4f} {r['recall']:>7.4f} "
                f"{r['specificity']:>7.4f} │ {r['gate_coverage']:>7.1%} "
                f"{r['gate_accuracy']:>7.1%} {r['llm_calls']:>7} {r['n']:>6}"
            )

    show(f"▸ F1 最高的 {top_n} 組", sorted(grid, key=lambda r: -r["f1"])[:top_n])

    # 實務取捨：防詐系統漏報（真詐騙沒抓到）的代價高於誤報，故另外列出
    # 「精確率達標前提下召回率最高」的組合
    qualified = [r for r in grid if r["precision"] >= min_precision]
    if qualified:
        show(
            f"▸ 精確率 ≥ {min_precision:.2f} 前提下，召回率最高的 {top_n} 組"
            "（漏報代價高時採用）",
            sorted(qualified, key=lambda r: -r["recall"])[:top_n],
        )
    else:
        print(f"\n▸ 沒有任何組合的精確率達到 {min_precision:.2f}（可調 --sweep-min-precision）")

    # 閘門覆蓋率高 = 少呼叫 LLM = 延遲低；在 F1 幾乎不掉的前提下越高越好
    best_f1 = max(r["f1"] for r in grid)
    near_best = [r for r in grid if r["f1"] >= best_f1 - 0.01]
    show(
        f"▸ F1 距最佳值 0.01 內、閘門覆蓋率最高的 {top_n} 組（延遲最低）",
        sorted(near_best, key=lambda r: -r["gate_coverage"])[:top_n],
    )

    best = max(grid, key=lambda r: r["f1"])
    print("\n" + "=" * 74)
    print("建議寫入 .env（F1 最佳組合）：")
    print(f"  RAG_GATE_TOP_N={best['top_n']}")
    print(f"  RAG_GATE_SIMILARITY={best['threshold']}")
    # x 在很寬的一段區間內都等價，把那段區間印出來，免得有人看到「最佳
    # x=0.35」就以為那個小數點有意義而去精調它。
    #
    # ⚠ 只報「與最佳值幾乎等價」的那一段，不報整條 x 的全距：x 拉得夠高時
    #   覆蓋率會崩掉、F1 跟著大跌，把那一段算進來會得到一個很大的數字，
    #   反而像是在說 x 很敏感——與這裡要傳達的訊息相反。
    plateau = [
        r["threshold"]
        for r in grid
        if r["top_n"] == best["top_n"] and r["f1"] >= best["f1"] - 0.005
    ]
    if len(plateau) > 1:
        print(
            f"  （N={best['top_n']} 時，x 在 {min(plateau):.2f}~{max(plateau):.2f} "
            f"之間 F1 都在最佳值 0.005 內——x 不必精調，N 才是主要變因。"
            f"\n    但 x 高過這段之後覆蓋率會崩，仍不可任意放大）"
        )
    if not with_llm:
        print(
            "  ⚠ 此結果由 --sweep-no-llm 產生，未涵蓋交由 LLM 判定的樣本；"
            "\n    僅適合用來比較不同嵌入模型的檢索品質，正式定案請跑完整掃描。"
        )
    print("=" * 74)


def frange(start: float, stop: float, step: float) -> list[float]:
    """產生浮點數等差序列（含終點，四捨五入避免累積誤差）。"""
    values: list[float] = []
    current = start
    while current <= stop + 1e-9:
        values.append(round(current, 4))
        current += step
    return values


async def run_sweep(args: argparse.Namespace) -> None:
    """門檻掃描主流程：階段一收集（或讀快取）→ 階段二網格掃描。"""
    cache_path = Path(args.cache) if args.cache else None
    with_llm = not args.sweep_no_llm

    if cache_path and cache_path.exists():
        records = load_cache(cache_path)
        print(f"已載入階段一快取：{cache_path}（{len(records)} 筆），跳過檢索與 LLM 推論")
        cached_with_llm = any(r.get("llm_is_scam") is not None for r in records)
        if with_llm and not cached_with_llm:
            print("⚠ 快取內無 LLM 判定，自動改以 --sweep-no-llm 模式掃描")
            with_llm = False
    else:
        rows = load_dataset(Path(args.input), args.limit, args.exclude_unverified)
        scam = sum(1 for r in rows if int(r["is_scam"]) == 1)
        print(f"載入 {len(rows)} 筆測試資料（詐騙 {scam} / 正常 {len(rows) - scam}）")
        print(
            f"階段一：收集檢索候選"
            f"{'與 LLM 判定（每筆各一次推論，較慢）' if with_llm else '（不呼叫 LLM）'}"
            f"，併發數 {args.concurrency}…"
        )
        records = await run_collect(rows, args.concurrency, with_llm)
        if cache_path:
            save_cache(cache_path, records)
            print(f"階段一結果已快取至 {cache_path}（之後重掃網格不需再推論）")

    failed = [r for r in records if "error" in r]
    if failed:
        print(f"\n⚠  {len(failed)} 筆收集失敗：{failed[0]['error']}")

    report_similarity_distribution(records)

    top_ns = list(range(args.sweep_n_min, args.sweep_n_max + 1))
    thresholds = frange(args.sweep_sim_min, args.sweep_sim_max, args.sweep_step)
    print(
        f"\n階段二：掃描 {len(top_ns)}×{len(thresholds)} 參數網格"
        f"（N={args.sweep_n_min}~{args.sweep_n_max}，x 步長 {args.sweep_step}）…"
    )
    start = time.perf_counter()
    grid = sweep(records, top_ns, thresholds, with_llm)
    print(f"  完成 {len(grid)} 組有效組合，耗時 {time.perf_counter() - start:.1f}s")

    report_sweep(grid, with_llm, args.sweep_min_precision, args.sweep_top)

    # 完整網格寫成 CSV，可直接畫 P/R 曲線或跨模型比較
    out_path = Path(args.sweep_out)
    with out_path.open("w", encoding="utf-8-sig", newline="") as fh:
        fields = [
            "top_n", "threshold", "f1", "accuracy", "precision", "recall",
            "specificity", "gate_coverage", "gate_accuracy", "gate_decided",
            "llm_calls", "tp", "fn", "fp", "tn", "n",
        ]
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows({k: row[k] for k in fields} for row in grid)
    print(f"\n完整網格已寫入 {out_path}（可用於畫 P/R 曲線與跨模型比較）")


async def main() -> None:
    parser = argparse.ArgumentParser(description="詐騙偵測準確度評測")
    parser.add_argument(
        "--input", default=DATA_DIR / "test.jsonl", help="測試集路徑（JSON Lines）"
    )
    parser.add_argument("--limit", type=int, default=None, help="只評測前 N 筆")
    # 預設 1：RagService 曾有冷啟動併發 bug——BGE-M3 首次前向傳播併發競爭會產生失真
    # 向量，使 top-1 相似度全部塌成 ~1.0，相似度閘門因而把每筆都誤判為詐騙。已加暖機
    # 修正並通過隔離驗證，但端到端併發收斂尚未驗證；在驗證通過前，量測準確度務必維持
    # concurrency=1，數字才可信。
    parser.add_argument("--concurrency", type=int, default=1, help="併發偵測數（見上方註解）")
    parser.add_argument(
        "--out",
        default=EVAL_DIR / "eval_results.jsonl",
        help="逐筆結果輸出路徑（供錯誤分析）",
    )
    parser.add_argument(
        "--exclude-unverified",
        action="store_true",
        help="排除 clean_labels.py 標為 unverified 的存疑樣本（需搭配 .clean.jsonl）",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="接續既有的 --out 結果檔：已評測過的樣本直接沿用，只跑沒跑到的",
    )

    ab_group = parser.add_argument_group(
        "有無 RAG A/B", "就地覆寫 .env 設定，方便同一份測試集連跑兩種組態"
    )
    rag_switch = ab_group.add_mutually_exclusive_group()
    rag_switch.add_argument(
        "--no-rag",
        dest="rag_enabled",
        action="store_false",
        default=None,
        help="停用 RAG（不檢索、不走閘門，直接交由 LLM），等同 RAG_ENABLED=false",
    )
    rag_switch.add_argument(
        "--rag",
        dest="rag_enabled",
        action="store_true",
        default=None,
        help="強制啟用 RAG，等同 RAG_ENABLED=true（預設沿用 .env）",
    )
    ab_group.add_argument(
        "--ollama-model",
        default=None,
        help="覆寫 OLLAMA_MODEL；A/B 時請為有／無 RAG 各指定對應的微調模型版本",
    )

    emb_group = parser.add_argument_group(
        "嵌入模型比較", "同一份測試集在相同條件下逐一評測各嵌入模型（見模組說明）"
    )
    emb_group.add_argument(
        "--embedding-model",
        default=None,
        help="覆寫 EMBEDDING_MODEL；未另指定 --collection 時自動改用該模型專屬集合",
    )
    emb_group.add_argument(
        "--collection",
        default=None,
        help="覆寫 CHROMA_COLLECTION（每個嵌入模型各一個集合，維度不同無法共用）",
    )
    emb_group.add_argument(
        "--no-gate",
        action="store_true",
        help="讓開相似度閘門（LOW=0.0、HIGH=1.0），每一筆都交由 LLM 判定",
    )
    emb_group.add_argument(
        "--case-threshold",
        type=float,
        default=None,
        help=(
            "覆寫 RAG_CASE_SIMILARITY_THRESHOLD；比較嵌入模型時建議設 0，"
            "改以純排名注入 top-N 案例，避免各模型餘弦尺度不同造成誤判"
        ),
    )
    emb_group.add_argument(
        "--summary-json",
        default=None,
        help="將指標與耗時寫成 JSON（供 compare_embedding_models.py 彙整比較表）",
    )

    sweep_group = parser.add_argument_group(
        "門檻掃描模式", "掃描 RAG_GATE_TOP_N × RAG_GATE_SIMILARITY 網格（換嵌入模型後重新校準）"
    )
    sweep_group.add_argument(
        "--sweep", action="store_true", help="啟用門檻掃描模式（取代一般評測）"
    )
    sweep_group.add_argument(
        "--sweep-no-llm",
        action="store_true",
        help="階段一不呼叫 LLM（不需 Ollama）；僅評測閘門自行判定的子集，用於比較嵌入模型",
    )
    sweep_group.add_argument(
        "--cache",
        default=None,
        help="階段一快取檔路徑；已存在則直接載入（改網格重掃不需重新推論）",
    )
    sweep_group.add_argument(
        "--sweep-step", type=float, default=0.05, help="相似度門檻 x 的網格步長"
    )
    # x 的靈敏度極低（實測 0.25~0.45 只讓 F1 動 0.003），步長 0.02 只是把
    # 網格撐大、不會找到更好的解，故預設放寬到 0.05。
    sweep_group.add_argument("--sweep-sim-min", type=float, default=0.20)
    sweep_group.add_argument("--sweep-sim-max", type=float, default=0.60)
    # N 是主要變因；1 也掃是為了讓「沒有一致性檢查」這條退化基線出現在同一張表上。
    sweep_group.add_argument("--sweep-n-min", type=int, default=1)
    sweep_group.add_argument("--sweep-n-max", type=int, default=10)
    sweep_group.add_argument(
        "--sweep-min-precision",
        type=float,
        default=0.90,
        help="「精確率達標下召回率最高」榜單的精確率下限",
    )
    sweep_group.add_argument("--sweep-top", type=int, default=8, help="各榜單顯示筆數")
    sweep_group.add_argument(
        "--sweep-out",
        default=EVAL_DIR / "threshold_sweep.csv",
        help="完整網格 CSV 輸出路徑",
    )

    args = parser.parse_args()

    # CLI 覆寫先於任何評測流程套用：偵測路徑一律讀全域 settings
    if args.rag_enabled is not None:
        settings.RAG_ENABLED = args.rag_enabled
    if args.ollama_model:
        settings.OLLAMA_MODEL = args.ollama_model
    if args.embedding_model:
        settings.EMBEDDING_MODEL = args.embedding_model
        # 換模型必換集合：維度與向量空間都不同，沿用舊集合不是報錯就是拿兩套
        # 不相容的向量做比對（check_collection_dimension 會擋下前者）
        if not args.collection:
            settings.CHROMA_COLLECTION = suggested_collection_name(
                settings.CHROMA_COLLECTION, args.embedding_model
            )
    if args.collection:
        settings.CHROMA_COLLECTION = args.collection
    if args.case_threshold is not None:
        settings.RAG_CASE_SIMILARITY_THRESHOLD = args.case_threshold
    if args.no_gate:
        # 門檻設 1.0：閘門要求候選**嚴格大於**門檻，而餘弦相似度上限就是 1.0，
        # 因此沒有任何候選能通過，等同關閉閘門（gate_disabled() 判的也是這個）。
        settings.RAG_GATE_SIMILARITY = 1.0

    if args.sweep:
        if not settings.RAG_ENABLED:
            parser.error(
                "門檻掃描需要 RAG：--sweep 掃的正是相似度閘門的門檻，"
                "與 --no-rag / RAG_ENABLED=false 互斥"
            )
        await run_sweep(args)
        return

    rows = load_dataset(Path(args.input), args.limit, args.exclude_unverified)
    scam = sum(1 for r in rows if int(r["is_scam"]) == 1)
    print(f"載入 {len(rows)} 筆測試資料（詐騙 {scam} / 正常 {len(rows) - scam}）")
    print_active_config()

    # 續跑：沿用結果檔中已評測過的樣本，只補跑缺的（測試集的 id 唯一，可當鍵）
    out_path = Path(args.out)
    done: list[dict] = []
    if args.resume and out_path.exists():
        previous = [
            json.loads(line)
            for line in out_path.open(encoding="utf-8")
            if line.strip()
        ]
        # 只有「成功」的樣本算跑過：失敗的多半是 Ollama 逾時或通道中斷等外部狀況，
        # 把它們一併跳過等於把環境故障永久固化成缺漏樣本，而缺漏往往集中在故障
        # 那段時間，不是隨機抽樣，會讓指標失真
        by_id: dict = {}
        for record in previous:
            if "error" in record and record.get("id") in by_id:
                continue  # 已有成功結果就不讓失敗紀錄覆蓋
            by_id[record.get("id")] = record
        done = [r for r in by_id.values() if "error" not in r]
        failed = len(by_id) - len(done)

        done_ids = {r.get("id") for r in done}
        pending = [row for row in rows if row.get("id") not in done_ids]
        print(
            f"續跑：已完成 {len(done)} 筆"
            f"（另有 {failed} 筆先前失敗，會重試），尚需評測 {len(pending)} 筆"
        )
        rows = pending
        # 以「僅保留成功樣本」重寫結果檔，再往後追加；否則失敗紀錄會與這次的成功
        # 結果同時留在檔裡，同一個 id 出現兩列
        with out_path.open("w", encoding="utf-8") as fh:
            for record in done:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    # 即使續跑後已無待評測樣本也要暖機：摘要裡的嵌入維度得靠載入模型才拿得到
    timings = Timings()
    instrument_retrieval(timings)
    await warmup(timings)  # 先載入模型，載入時間才不會算到第一筆樣本頭上
    print(f"併發數 {args.concurrency}，開始評測…\n")

    # 逐筆即時寫檔：被中斷時已跑完的推論不會白費
    with out_path.open("a" if done else "w", encoding="utf-8") as sink:
        results = done + await run(rows, args.concurrency, timings, sink)
    print(f"逐筆結果已寫入 {out_path}（{len(results)} 筆）")

    report(results, timings)

    if args.summary_json:
        ok = [r for r in results if "error" not in r]
        summary = {
            "embedding_model": settings.EMBEDDING_MODEL,
            "collection": settings.CHROMA_COLLECTION,
            "ollama_model": settings.OLLAMA_MODEL,
            "rag_enabled": settings.RAG_ENABLED,
            "gate_disabled": gate_disabled(),
            "case_threshold": settings.RAG_CASE_SIMILARITY_THRESHOLD,
            "samples": len(results),
            "samples_ok": len(ok),
            "metrics": compute_metrics(
                [(r["expected"], r["predicted"]) for r in ok]
            ),
            "timings": compute_time_breakdown(results, timings),
        }
        Path(args.summary_json).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"摘要已寫入 {args.summary_json}")


if __name__ == "__main__":
    # Windows 主控台預設 cp950，導向檔案時會把報表裡的中文寫成 cp950，
    # 之後用 utf-8 讀就整份炸掉（eval_stage.py 早就有這一行，這裡補齊）。
    # stderr 也要一起改：這支腳本的常見用法是 `> log 2>&1`，而 tqdm 的進度條
    # （FlagEmbedding 載入權重時）與警告訊息走 stderr——只改 stdout 的話，
    # 同一個檔案裡會混兩種編碼，比全部都是 cp950 更難讀。
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    asyncio.run(main())
