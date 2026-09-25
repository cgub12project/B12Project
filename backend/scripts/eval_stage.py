"""詐騙階段判定的準確度評測。

為什麼不沿用 eval_scam_detection.py
────────────────────────────────────────────────────────────────────────
那支是**二元**分類的評測（正類＝詐騙），compute_metrics() 只回 tp/fn/fp/tn 那一組，
report() 還硬取 r["decided_by"]——把階段結果混進去會直接 KeyError。

更根本的差別是：階段是**序數**分類。把「鋪陳誘餌」判成「索取財物」與判成「接觸建立」
在一般 accuracy 眼中是同一種錯，但實際代價差很多——前者只是早一步示警，後者是
在對方已經開口要錢時告訴使用者「還在打招呼」。所以主要指標是：

  MAE      平均差幾階（唯一會因為「錯得遠」而變差的指標）
  ±1 準確率 容許差一階的命中率（產品上差一階多半還可接受）
  exact    完全命中率
  另附 5×5 混淆矩陣與 per-stage / per-type 召回率，讓偏斜看得見

三種評測對象
────────────────────────────────────────────────────────────────────────
  --rules-only  只跑關鍵詞規則，不需要任何模型。**這是可以現在就量的基線**，
                也是模型至少要贏過的下限。
  （預設）        走 StageService.classify() 的完整線上路徑（LLM + 規則地板 +
                單調性調和），量到的是使用者實際會拿到的結果。
  --sequential  同一段對話的前綴依序評測，並把上一個前綴的結果當 previous_stage
                傳下去——這才是 App 的真實用法（階段狀態由用戶端攜帶）。
                不加此旗標則每個前綴獨立判定，量的是模型單獨的能力。

用法：
    python -m scripts.eval_stage --rules-only
    python -m scripts.eval_stage --model qwen2.5:7b
    python -m scripts.eval_stage --model flash_stage_v1 --sequential --out eval/stage_v1.jsonl
"""

import argparse
import asyncio
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

from app.core.config import settings
from app.schemas.rag import ConversationMessage
from scripts.build_stage_dataset import REAL_SOURCES
from app.services.stage_service import (
    STAGE_INDEX,
    STAGE_LABELS,
    STAGES,
    StageService,
    StageUnavailableError,
)

# 路徑錨定於專案根目錄，預設值不受執行時的工作目錄影響
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
EVAL_DIR = PROJECT_ROOT / "eval"

TEST_PATH = DATA_DIR / "stage_test.jsonl"
OUT_PATH = EVAL_DIR / "stage_eval.jsonl"


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def to_messages(turns: list[dict]) -> list[ConversationMessage]:
    return [ConversationMessage(sender=t["sender"], text=t["text"]) for t in turns]


# ---------------------------------------------------------------------------
# 預測
# ---------------------------------------------------------------------------


def rules_only_predict(turns: list[dict]) -> str | None:
    """只用關鍵詞規則預測，不呼叫任何模型。

    直接沿用 label_stage_turns 的規則投票器與前綴聚合，確保基線量到的
    就是弱標註器本身的能力——若模型贏不過這條線，那顆模型不值得上線。
    """
    from scripts.label_stage_turns import aggregate, rule_stage

    stages = [
        rule_stage(turn["text"]) if turn["sender"] == "them" else None for turn in turns
    ]
    prefix = aggregate(stages)
    return prefix[-1] if prefix else None


async def model_predict(
    service: StageService,
    turns: list[dict],
    *,
    scam_type: str | None,
    previous_stage: str | None,
) -> tuple[str | None, str]:
    """走線上路徑預測；回傳（階段, 判定來源）。"""
    try:
        verdict = await service.classify(
            to_messages(turns), scam_type=scam_type, previous_stage=previous_stage
        )
        return verdict.stage, verdict.model
    except StageUnavailableError:
        return None, "stage-unavailable"


# ---------------------------------------------------------------------------
# 指標
# ---------------------------------------------------------------------------


def compute_metrics(pairs: list[tuple[str, str]]) -> dict:
    """序數分類指標。pairs 為（正確答案, 預測）的 slug 配對。"""
    if not pairs:
        return {"n": 0}

    distances = [abs(STAGE_INDEX[truth] - STAGE_INDEX[pred]) for truth, pred in pairs]
    total = len(pairs)
    return {
        "n": total,
        "exact_accuracy": sum(d == 0 for d in distances) / total,
        "within_1_accuracy": sum(d <= 1 for d in distances) / total,
        "mae": sum(distances) / total,
        # 把階段判早（偏嚴）與判晚（偏鬆）分開看：判晚才是會害到使用者的方向
        "over_predicted": sum(
            STAGE_INDEX[p] > STAGE_INDEX[t] for t, p in pairs
        )
        / total,
        "under_predicted": sum(
            STAGE_INDEX[p] < STAGE_INDEX[t] for t, p in pairs
        )
        / total,
    }


def print_confusion(pairs: list[tuple[str, str]]) -> None:
    matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for truth, pred in pairs:
        matrix[truth][pred] += 1

    header = "".join(f"{STAGE_LABELS[s][:4]:>8}" for s, _ in STAGES)
    print(f"\n混淆矩陣（列＝正確答案，欄＝預測）\n{'':<12}{header}{'召回率':>10}")
    for truth, _ in STAGES:
        row = matrix.get(truth, {})
        total = sum(row.values())
        cells = "".join(f"{row.get(pred, 0):>8}" for pred, _ in STAGES)
        recall = f"{row.get(truth, 0) / total:.2f}" if total else "—"
        print(f"  {STAGE_LABELS[truth]:<10}{cells}{recall:>10}")


def print_by_type(results: list[dict]) -> None:
    grouped: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for row in results:
        if row.get("predicted"):
            grouped[row["scam_type"] or "（未知）"].append((row["expected"], row["predicted"]))

    print("\n依詐騙類型（樣本數少的類型數字不可信，列出來是為了讓偏斜看得見）")
    print(f"  {'類型':<22}{'樣本':>6}{'exact':>8}{'±1':>8}{'MAE':>8}")
    for scam_type, pairs in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
        metrics = compute_metrics(pairs)
        print(
            f"  {scam_type:<22}{metrics['n']:>6}"
            f"{metrics['exact_accuracy']:>8.2f}"
            f"{metrics['within_1_accuracy']:>8.2f}"
            f"{metrics['mae']:>8.2f}"
        )


def warn_if_circular(results: list[dict], *, rules_only: bool) -> None:
    """測試集若沒有人工標籤，這份報表就不能當成績單看——把話講死。

    弱標籤是規則投票器產生的，拿它去評測同一套規則必然接近滿分：實測
    --rules-only 對未經人工審核的測試集是 exact 1.0000。那不是模型很準，
    是在拿自己的答案考自己。這個陷阱不能靠使用者「看到 1.00 覺得怪怪的」來發現。
    """
    gold = sum(1 for row in results if row.get("label_tier") == "gold")
    if gold:
        print(f"\n測試集中經人工審核的樣本：{gold} / {len(results)}")
        if gold < len(results):
            print("  （下列指標涵蓋全部樣本；只看人工標籤的數字請用 --gold-only）")
        return

    print("\n" + "!" * 62)
    print("警告：測試集裡沒有任何一筆經過人工審核，標籤全部是規則產生的弱標籤。")
    if rules_only:
        print("     你正在用規則去評測產生這些標籤的同一套規則——分數必然接近滿分，")
        print("     這個數字沒有任何意義，不可以寫進報告或拿來決定要不要微調。")
    else:
        print("     模型分數會被系統性地推向「與規則一致」的方向，而非真正的正確答案。")
    print("     請先用 Excel 開 eval/stage_review.csv 標一批（建議 50 段以上），")
    print("     再跑 build_stage_dataset，測試集才會有 gold 標籤。")
    print("!" * 62)


def report(results: list[dict], *, subject: str, rules_only: bool) -> None:
    scored = [row for row in results if row.get("predicted")]
    skipped = len(results) - len(scored)
    pairs = [(row["expected"], row["predicted"]) for row in scored]
    metrics = compute_metrics(pairs)

    print("=" * 62)
    print(f"評測對象：{subject}")
    print(f"樣本 {len(results)} 筆，其中 {skipped} 筆判不出階段（未計入指標）")
    print("=" * 62)
    warn_if_circular(results, rules_only=rules_only)

    if not pairs:
        print("沒有任何可計分的預測")
        return

    print(f"  完全命中 exact       {metrics['exact_accuracy']:.4f}")
    print(f"  容許差一階 ±1        {metrics['within_1_accuracy']:.4f}")
    print(f"  平均差幾階 MAE       {metrics['mae']:.4f}")
    print(f"  判得比實際晚（危險）  {metrics['under_predicted']:.4f}")
    print(f"  判得比實際早（保守）  {metrics['over_predicted']:.4f}")

    timed = [row for row in results if row.get("elapsed") is not None]
    if timed:
        total_seconds = sum(row["elapsed"] for row in timed)
        print(
            f"  平均每筆耗時         {total_seconds / len(timed):.3f}s"
            f"（{len(timed)} 筆合計 {total_seconds:.1f}s）"
        )

    print_confusion(pairs)
    print_by_type(scored)

    sources = {row.get("decided_by") for row in scored}
    if sources - {"rules"}:
        counts: dict[str, int] = defaultdict(int)
        for row in scored:
            counts[row.get("decided_by") or "?"] += 1
        print("\n判定來源：" + "、".join(f"{k} {v} 筆" for k, v in counts.items()))


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


async def run(rows: list[dict], args: argparse.Namespace) -> list[dict]:
    service = StageService()
    results: list[dict] = []
    # --sequential：同一段對話的前綴依序評測，把上一個結果當 previous_stage 傳下去
    previous_by_conversation: dict[str, str | None] = {}

    for index, row in enumerate(rows, start=1):
        start = time.perf_counter()
        if args.rules_only:
            predicted, decided_by = rules_only_predict(row["turns"]), "rules"
        else:
            previous = (
                previous_by_conversation.get(row["conversation_id"])
                if args.sequential
                else None
            )
            predicted, decided_by = await model_predict(
                service,
                row["turns"],
                scam_type=row.get("scam_type"),
                previous_stage=previous,
            )
            if args.sequential:
                previous_by_conversation[row["conversation_id"]] = predicted
            print(f"  [{index}/{len(rows)}]", end="\r")

        elapsed = time.perf_counter() - start
        results.append(
            {
                "id": row["id"],
                "conversation_id": row["conversation_id"],
                "scam_type": row.get("scam_type"),
                "turns": len(row["turns"]),
                "expected": row["stage"],
                "predicted": predicted,
                "correct": predicted == row["stage"],
                "distance": (
                    abs(STAGE_INDEX[row["stage"]] - STAGE_INDEX[predicted])
                    if predicted
                    else None
                ),
                "decided_by": decided_by,
                # 該筆判定耗時（秒）：規則基線是純 CPU，模型則含網路往返
                "elapsed": round(elapsed, 4),
                "label_tier": row.get("label_tier", "weak"),
            }
        )
    if not args.rules_only:
        print(" " * 30, end="\r")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="詐騙階段判定的準確度評測")
    parser.add_argument("--test", default=TEST_PATH, help="測試集（stage_test.jsonl）")
    parser.add_argument("--out", default=OUT_PATH, help="逐筆結果輸出路徑")
    parser.add_argument(
        "--rules-only", action="store_true", help="只跑關鍵詞規則基線（不需要模型）"
    )
    parser.add_argument("--model", default=None, help="階段模型（預設沿用 .env 設定）")
    parser.add_argument(
        "--sequential",
        action="store_true",
        help="同一段對話的前綴依序評測並傳遞 previous_stage（模擬 App 的實際用法）",
    )
    parser.add_argument(
        "--gold-only",
        action="store_true",
        help="只評測審核過的樣本（2026-08-31 覆核完成後，測試集 444 筆全部是 gold，"
        "這個旗標已篩不掉東西；慣例與盲審一致度見 data/answer_reviews/README.txt）",
    )
    parser.add_argument(
        "--think",
        action="store_true",
        help="讓思考型模型（如 gemma4）先輸出推理過程再作答（慢約 4 倍）",
    )
    parser.add_argument("--limit", type=int, default=0, help="只評測前 N 筆")
    parser.add_argument("--dry-run", action="store_true", help="只印報表，不寫檔")
    args = parser.parse_args()

    test_path = Path(args.test)
    if not test_path.exists():
        raise SystemExit(
            f"找不到 {test_path}，請先執行 python -m scripts.build_stage_dataset"
        )
    rows = load_jsonl(test_path)
    if args.gold_only:
        rows = [row for row in rows if row.get("label_tier") == "gold"]
        if not rows:
            raise SystemExit(
                "測試集裡沒有任何人工審核過的樣本。請先填 eval/stage_review.csv "
                "的 verdict_stage 欄，再重跑 build_stage_dataset。"
            )
    if args.limit:
        rows = rows[: args.limit]

    # 測試集必須 100% 是真實對話——這是整條管線唯一能信的基準，
    # 混進合成資料就等於拿自己的產物考自己
    synthetic = {row["source"] for row in rows} - REAL_SOURCES
    if synthetic:
        raise SystemExit(f"測試集混入了非真實來源：{synthetic}，請重新產生測試集")

    if args.model:
        settings.OLLAMA_STAGE_MODEL = args.model
    if args.think:
        settings.OLLAMA_STAGE_THINK = True
    subject = (
        "關鍵詞規則基線"
        if args.rules_only
        else f"{StageService.model_name()}（{'循序' if args.sequential else '獨立'}判定）"
    )

    results = asyncio.run(run(rows, args))
    report(results, subject=subject, rules_only=args.rules_only)

    if args.dry_run:
        print("\n（--dry-run：未寫檔）")
        return

    EVAL_DIR.mkdir(exist_ok=True)
    with Path(args.out).open("w", encoding="utf-8") as fh:
        for row in results:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"\n逐筆結果已寫入 {args.out}")


if __name__ == "__main__":
    # Windows 主控台預設 cp950，會把報表裡的中文印成亂碼
    sys.stdout.reconfigure(encoding="utf-8")
    main()
