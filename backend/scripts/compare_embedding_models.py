"""嵌入模型橫向比較：同一份測試集、同一顆 LLM，只換嵌入模型。

對每個嵌入模型依序做兩件事，最後彙整成一張比較表：

    1. 建庫：以該模型把 vector_db.jsonl 全量入庫到「該模型專屬的 ChromaDB 集合」
       （維度與向量空間都不同，集合不能共用；集合名稱由
        `suggested_collection_name()` 產生，可並存、重跑不必重建）
    2. 評測：以 test.jsonl 跑 scripts.eval_scam_detection，記錄準確率與耗時

【比較條件】
- `--no-gate`：讓開相似度閘門，每一筆都交由 LLM 判定。檢索仍照跑、相似案例
  照樣注入提示詞——嵌入模型正是透過「注入哪幾筆案例」影響準確率的。
- `--case-threshold 0`：案例注入改為純排名制（固定注入最相似的 top-3 詐騙 +
  top-3 正常案例）。注入門檻是絕對相似度，而各模型的餘弦尺度差很多，沿用同一個
  0.7 會讓尺度被壓縮的模型大量注不進案例，量到的就變成尺度差異而非檢索品質。

【為何用子行程逐一跑】
嵌入模型是行程內的單例，且每顆都要吃掉數 GB VRAM。一個行程換一次模型得自行
釋放顯存並重設單例，稍有殘留就會 OOM 或拿到上一顆模型的向量；分行程跑則由
作業系統保證每次都是乾淨的環境，時間量測也不會被前一顆模型的殘留影響。

【可中斷續跑】
每個模型的摘要各自寫成一個 JSON，已存在就跳過（`--force` 可強制重跑）；
向量庫也是既有數量對得上就不重建。整批跑數小時，中途斷掉直接再跑一次即可。

用法：
    python -m scripts.compare_embedding_models
    python -m scripts.compare_embedding_models --limit 300        # 快速煙霧測試
    python -m scripts.compare_embedding_models --models BAAI/bge-m3  # 只跑指定模型
    python -m scripts.compare_embedding_models --report-only      # 只重印比較表
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from app.core.config import settings
from app.services.embedding import suggested_collection_name

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
EVAL_DIR = PROJECT_ROOT / "eval"
SUMMARY_DIR = EVAL_DIR / "embedding_compare"

# 預設比較清單。
# 註：`Qwen/Qwen3-Embedding-4B` 不在清單內——40 億參數 FP16 權重約 8 GB，
# 放不進本機 RTX 4050 Laptop 的 6.4 GB VRAM；要測請改用記憶體更大的顯卡，
# 或加上 EMBEDDING_DEVICE=cpu 跑（會慢上數小時）。
DEFAULT_MODELS = [
    "Qwen/Qwen3-Embedding-0.6B",
    "Alibaba-NLP/gte-multilingual-base",
    "intfloat/multilingual-e5-large",
    "BAAI/bge-large-zh-v1.5",
]


def model_slug(model: str) -> str:
    """模型名稱轉為可當檔名的短代號。"""
    return model.split("/")[-1].replace(".", "_").lower()


def expected_vector_count() -> int:
    """算出 vector_db.jsonl 會入庫幾筆（與 rag_worker 的取捨規則一致）。

    用來判斷某個集合是否已完整入庫；數量對不上就重建（upsert 冪等，重跑安全）。
    """
    path = Path(settings.TRAINING_DATA_PATH)
    seen: set[str] = set()
    for line_no, line in enumerate(path.open(encoding="utf-8"), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        metadata = record.get("metadata") or {}
        if metadata.get("is_scam") not in (0, 1):
            continue
        if not (record.get("text") or "").strip():
            continue
        record_id = str(record.get("id") or "").strip() or f"line{line_no}"
        seen.add(record_id)
    return len(seen)


def collection_count(name: str) -> int:
    """回傳 ChromaDB 集合現有向量數；集合不存在時回傳 0。"""
    import chromadb

    client = chromadb.PersistentClient(path=settings.CHROMA_DIR)
    try:
        return client.get_collection(name).count()
    except Exception:
        return 0


def child_env(model: str, collection: str) -> dict[str, str]:
    """組出子行程的環境變數（環境變數的優先序高於 .env，故可就地覆寫設定）。"""
    env = dict(os.environ)
    env["EMBEDDING_MODEL"] = model
    env["CHROMA_COLLECTION"] = collection
    # Windows 主控台預設非 UTF-8，中文輸出轉向檔案時會炸掉或變亂碼
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_child(argv: list[str], env: dict[str, str], title: str) -> float:
    """執行子行程並回傳耗時（秒）；子行程輸出直接串到本行程的 stdout。

    Raises:
        subprocess.CalledProcessError: 子行程以非 0 結束。
    """
    print(f"\n{'=' * 74}\n▶ {title}\n{'=' * 74}", flush=True)
    start = time.perf_counter()
    subprocess.run(argv, cwd=PROJECT_ROOT, env=env, check=True)
    elapsed = time.perf_counter() - start
    print(f"◀ {title} 完成，耗時 {elapsed / 60:.1f} 分", flush=True)
    return elapsed


def ingest(model: str, collection: str, expected: int, force: bool) -> float | None:
    """確保該模型的向量庫已就緒；回傳入庫耗時（跳過時為 None）。"""
    existing = collection_count(collection)
    if not force and existing == expected:
        print(f"集合 {collection} 已有 {existing} 筆向量，跳過建庫", flush=True)
        return None
    if existing:
        print(f"集合 {collection} 現有 {existing} 筆、預期 {expected} 筆，重新入庫", flush=True)

    return run_child(
        [sys.executable, "rag_worker.py", "--once"],
        child_env(model, collection),
        f"建庫 {model} → {collection}（{expected} 筆）",
    )


def evaluate(
    model: str, collection: str, summary_path: Path, args: argparse.Namespace
) -> None:
    """跑一次評測，結果寫進 summary_path。"""
    argv = [
        sys.executable,
        "-m",
        "scripts.eval_scam_detection",
        "--no-gate",
        # 中斷後重跑時沿用已評測的樣本；逐筆結果是即時寫檔的，接得回來
        "--resume",
        "--case-threshold",
        str(args.case_threshold),
        "--concurrency",
        str(args.concurrency),
        "--input",
        str(args.input),
        "--out",
        str(EVAL_DIR / f"eval_emb_{model_slug(model)}.jsonl"),
        "--summary-json",
        str(summary_path),
    ]
    if args.limit:
        argv += ["--limit", str(args.limit)]
    run_child(argv, child_env(model, collection), f"評測 {model}")


def print_comparison(summaries: list[dict]) -> None:
    """印出橫向比較表（依 F1 遞減排序）。"""
    if not summaries:
        print("\n沒有任何可用的評測摘要。")
        return

    rows = sorted(summaries, key=lambda s: s["metrics"]["f1"], reverse=True)
    print("\n" + "=" * 108)
    print("嵌入模型橫向比較（相似度閘門讓開，每筆皆由 LLM 判定）")
    print("=" * 108)
    header = (
        f"{'嵌入模型':<34}{'維度':>6}{'樣本':>7}{'準確率':>9}{'精確率':>9}{'召回率':>9}"
        f"{'F1':>9}{'建庫(分)':>10}{'檢索(ms)':>10}{'評測(分)':>10}"
    )
    print(header)
    print("-" * 108)
    for row in rows:
        metrics, timings = row["metrics"], row["timings"]
        ingest_minutes = (
            f"{row['ingest_seconds'] / 60:.1f}"
            if row.get("ingest_seconds")
            else "（沿用）"
        )
        print(
            f"{row['embedding_model']:<34}"
            f"{timings['embedding_dimension']:>6}"
            # 樣本數逐一列出：各模型的失敗筆數不同，n 不一樣時指標不能直接對比
            f"{row['samples_ok']:>7}"
            f"{metrics['accuracy']:>9.4f}"
            f"{metrics['precision']:>9.4f}"
            f"{metrics['recall']:>9.4f}"
            f"{metrics['f1']:>9.4f}"
            f"{ingest_minutes:>10}"
            f"{timings['retrieval_ms_per_call']:>10.1f}"
            f"{timings['wall_seconds'] / 60:>10.1f}"
        )
    print("-" * 108)
    first = rows[0]
    print(
        f"測試集 {first['samples']} 筆　"
        f"LLM {first['ollama_model']}　"
        f"案例注入門檻 {first['case_threshold']}"
    )
    incomplete = [r for r in rows if r["samples_ok"] < r["samples"] * 0.98]
    for row in incomplete:
        missing = row["samples"] - row["samples_ok"]
        print(
            f"⚠ {row['embedding_model']} 缺 {missing} 筆（偵測失敗）。"
            "缺漏多半集中在 LLM 故障那段時間、不是隨機抽樣，指標不宜與其他模型並列比較；"
            "請以 --resume 補跑。"
        )
    print(
        "註：「檢索」為嵌入查詢 + ChromaDB 查詢的平均單筆耗時，是嵌入模型之間"
        "真正的速度差異；\n"
        "　　「評測」總時間由 LLM 推論主導（各模型共用同一顆 LLM），不宜用來比較嵌入模型快慢。"
    )
    print("=" * 108)


def write_csv(summaries: list[dict], path: Path) -> None:
    """把比較結果寫成 CSV（可直接貼進報告或畫圖）。"""
    fields = [
        "embedding_model", "dimension", "samples", "accuracy", "precision",
        "recall", "specificity", "f1", "tp", "fn", "fp", "tn",
        "ingest_seconds", "model_load_seconds", "retrieval_ms_per_call",
        "llm_seconds_per_call", "eval_wall_seconds",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in summaries:
            metrics, timings = row["metrics"], row["timings"]
            writer.writerow(
                {
                    "embedding_model": row["embedding_model"],
                    "dimension": timings["embedding_dimension"],
                    "samples": row["samples_ok"],
                    **{
                        k: metrics[k]
                        for k in (
                            "accuracy", "precision", "recall", "specificity",
                            "f1", "tp", "fn", "fp", "tn",
                        )
                    },
                    "ingest_seconds": row.get("ingest_seconds"),
                    "model_load_seconds": timings["model_load_seconds"],
                    "retrieval_ms_per_call": timings["retrieval_ms_per_call"],
                    "llm_seconds_per_call": timings["llm_seconds_per_call"],
                    "eval_wall_seconds": timings["wall_seconds"],
                }
            )
    print(f"比較表已寫入 {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="嵌入模型橫向比較")
    parser.add_argument(
        "--models", nargs="+", default=DEFAULT_MODELS, help="要比較的嵌入模型清單"
    )
    parser.add_argument(
        "--input", default=DATA_DIR / "test.jsonl", help="測試集路徑"
    )
    parser.add_argument("--limit", type=int, default=None, help="只評測前 N 筆")
    parser.add_argument(
        "--concurrency", type=int, default=1,
        help="併發偵測數（預設 1；見 eval_scam_detection 的說明）",
    )
    parser.add_argument(
        "--case-threshold", type=float, default=0.0,
        help="RAG_CASE_SIMILARITY_THRESHOLD；預設 0 = 純排名注入 top-N 案例",
    )
    parser.add_argument(
        "--force", action="store_true", help="即使摘要與向量庫已存在也重跑"
    )
    parser.add_argument(
        "--report-only", action="store_true", help="不執行評測，只用既有摘要重印比較表"
    )
    parser.add_argument(
        "--out", default=EVAL_DIR / "embedding_model_comparison.csv",
        help="比較表 CSV 輸出路徑",
    )
    args = parser.parse_args()

    # Windows 主控台預設 cp950，中文報表轉向檔案時會出亂碼
    sys.stdout.reconfigure(encoding="utf-8")
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)

    expected = expected_vector_count() if not args.report_only else 0
    summaries: list[dict] = []

    for model in args.models:
        collection = suggested_collection_name(settings.CHROMA_COLLECTION, model)
        summary_path = SUMMARY_DIR / f"{model_slug(model)}.json"
        ingest_seconds: float | None = None

        if not args.report_only:
            if summary_path.exists() and not args.force:
                print(f"\n{model}：摘要已存在（{summary_path.name}），跳過", flush=True)
            else:
                try:
                    ingest_seconds = ingest(model, collection, expected, args.force)
                    evaluate(model, collection, summary_path, args)
                except subprocess.CalledProcessError as exc:
                    # 一顆模型掛掉（下載失敗、VRAM 不足）不該讓整批數小時的比較中斷
                    print(f"\n⚠ {model} 執行失敗（結束碼 {exc.returncode}），跳過", flush=True)
                    continue

        if not summary_path.exists():
            print(f"⚠ 找不到 {summary_path}，{model} 不列入比較表", flush=True)
            continue

        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if ingest_seconds is not None:
            # 建庫耗時屬於本次執行的資訊，一併留在摘要裡供之後 --report-only 重印
            summary["ingest_seconds"] = ingest_seconds
            summary_path.write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        summaries.append(summary)

    print_comparison(summaries)
    if summaries:
        write_csv(summaries, Path(args.out))


if __name__ == "__main__":
    main()
