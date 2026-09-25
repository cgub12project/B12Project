"""由評測結果擬合風險分數校準表（四格實測詐騙率）。

為什麼需要校準
────────────────────────────────────────────────────────────────────────
偵測回應的 `confidence` 是「模型對自己這個判斷的信心」，不是「這則訊息是詐騙的
機率」。兩者在前端是完全不同的東西：判定為正常、confidence 0.95 的訊息，拿
0.95 去畫風險條會變成滿格紅色，但它的意思其實是「很確定安全」。

所以正確做法不是換一個閾值，而是把判定結果映射到實測的詐騙機率，另外輸出成
`risk_score`；`confidence` 維持原語意不動。

擬合方法：四格實測詐騙率 + llm 兩格的相似度微調
────────────────────────────────────────────────────────────────────────
依 (decided_by, predicted) 分成四格——閘門與 LLM、判詐騙與判正常是四種性質
不同的狀態——各自計算實測詐騙率，並做 Laplace 平滑（見下）。這四個數字已經
帶走幾乎全部的資訊量。

llm 那兩格另外再用檢索特徵做微調（邏輯迴歸，每格 3 個係數）。只有 llm 有，
因為實測 gate 那側加了完全沒有增益：

    gate  n=1534  只看判定 Brier 0.0211 → 加相似度 0.0211（+0.0000）
    llm   n= 449  只看判定 Brier 0.0800 → 加相似度 0.0753（+0.0047）

原因是**閘門已經把相似度訊號花掉了**——它的觸發條件就是「最相似的 N 筆全部
超過門檻且標籤一致」，等你知道閘門開火且判詐騙，母體已經純到 97.8%。這是條件
獨立，不是相似度沒用；llm 那側閘門沒開火，訊號還在。

整體效果（1,983 筆，5-fold 交叉驗證）：
    四格常數            Brier 0.0345  ECE 0.0108  AUC 0.9704
    四格 + 相似度微調   Brier 0.0334  ECE 0.0121  AUC 0.9762
    等張迴歸分箱（舊）  Brier 0.0340  ECE 0.0087  AUC 0.9766

微調也讓 risk_level 的 mid 回來了，而且是有內容的 mid：llm 判詐騙的 350 筆中
有 90 筆（25.7%）落在 RISK_HIGH_SCORE 以下，那 90 筆的實際詐騙率是 0.789，
其餘 260 筆是 0.969——差 18 個百分點，確實代表「比較不確定」。

⚠ 2026-09-25 之前這裡是「組內對 confidence 做等張迴歸（PAVA）+ 分箱合併」的
  11 分箱版本。改掉的原因是實測發現 **confidence 這一維幾乎沒有貢獻**
  （1,983 筆，5-fold 交叉驗證）：

      只用四格基礎率（4 個數字）      Brier 0.0345  ECE 0.0108  AUC 0.9704
      等張迴歸分箱（舊版，11 分箱）   Brier 0.0340  ECE 0.0087  AUC 0.9766

  整套 PAVA + 分箱合併 + 最近鄰查表換到的是小數點後第四位。拆開來看更清楚：

      gate 路徑  只看判定 Brier 0.0211 → 加上 confidence 0.0210（+0.0001）
      llm  路徑  只看判定 Brier 0.0800 → 加上 confidence 0.0811（−0.0011）

  llm 那側是負的：模型自報的分數與真實標籤反向（AUC 0.3317），放進去只會變糟。
  gate 那側的 confidence 是 top-1 相似度、單獨看 AUC 0.7153 確實有鑑別力，但
  **閘門已經把這個訊號花掉了**——它的觸發條件就是「最相似的 N 筆全部超過門檻且
  標籤一致」，等你知道閘門開火且判詐騙，母體已經純到 97.8%，top-1 的確切數值
  再也區別不出什麼。這是條件獨立，不是相似度沒用。

  若日後要讓 risk_score 更細，該加的是**閘門沒花掉的**檢索特徵（top-3 平均、
  相似度加權的詐騙票佔比），而且只在 llm 那兩格有效：
      四格 + 相似度微調  Brier 0.0334（gate +0.0000、llm +0.0047）
  當時評估為「多存 8 個係數、只在 23% 的流量上換到 0.0011」而未採用。

Laplace 平滑
────────────────────────────────────────────────────────────────────────
分子加 1、分母加 2（等於每格各加一筆詐騙、一筆非詐騙），避免 644/644 這種
有限樣本直接輸出機率 1.0——那是「還沒看到反例」，不是「沒有反例」。

重要：校準表與整條管線綁定
────────────────────────────────────────────────────────────────────────
四個數字看起來像常數，其實依賴很多東西，任何一項變動都會讓它悄悄失真：

  - 換 LLM         → llm 兩格的純度變了
  - 換嵌入模型     → 餘弦尺度位移，閘門的觸發母體整個改變，gate 兩格全錯
  - 改閘門參數     → RAG_GATE_TOP_N / RAG_GATE_SIMILARITY 直接重劃四格的邊界
  - 向量庫長大     → rag_worker 持續灌入使用者回報，gate 的純度會隨 KB 漂移

前兩項由 risk_calibration.py 的欄位比對擋下（不符就整個停用）。後兩項**沒有
自動保護**，改完請重跑評測並重新擬合。

用法：
    # 先產生相似度快取（對當前向量庫重跑檢索，需 GPU 與 ChromaDB）
    python -m scripts.build_sim_cache --input data/test.jsonl

    python -m scripts.fit_risk_calibration --eval eval/eval_v6_maxlen.jsonl
    python -m scripts.fit_risk_calibration --eval eval/eval_v6_maxlen.jsonl --dry-run
    # 不給 --sim-cache 就只產生四格常數（llm 兩格沒有係數，行為退回四格版）
"""

import argparse
import json
import math
from collections import defaultdict
from datetime import date
from pathlib import Path

from app.core.config import settings
from app.services.risk_calibration import FEATURE_NAMES, extract_features

# 路徑錨定於專案根目錄，預設值不受執行時的工作目錄影響
# （校準表本身留在根目錄：app/services/risk_calibration.py 從那裡讀）
PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = PROJECT_ROOT / "eval"

# Laplace 平滑的虛擬計數（等於在每格各加一筆詐騙、一筆非詐騙）
SMOOTH = 1.0

# 低於此樣本數的格子只印警告、不阻止寫檔：平滑會把它拉向 0.5，
# 那比硬給一個由十幾筆算出來的極端值安全。
MIN_CELL = 30

# 哪些判定來源要另外做相似度微調。只有 llm——gate 那側實測增益為 0，
# 見模組註解的「閘門已經把相似度訊號花掉了」。
SIMILARITY_SOURCES = {"llm"}

# 微調所需的最少樣本數：係數只有 3 個，但樣本太少時擬合出來的是雜訊，
# 不如退回該格的常數（不寫 coef 即可，執行期會自動退回）。
MIN_CELL_FOR_COEF = 60

# 邏輯迴歸的 L2 正則強度（作用在損失「總和」上，與 scikit-learn 的 C=1 同量級）。
# ⚠ 別調小：1e-3 幾乎等於沒有正則，實測會讓 llm 判詐騙那格的樣本內 risk 散到
#   0.041~0.997——那格的實際詐騙率是 0.92，0.041 只可能是擬合到了離群點。
#   兩個特徵本來就高度相關（鄰域越近、票也越容易一致），Hessian 接近奇異。
L2 = 1.0

# 交叉驗證的折數。係數只有 3 個，5 折足夠判斷「微調有沒有真的幫上忙」。
CV_FOLDS = 5


def _solve(matrix: list[list[float]], rhs: list[float]) -> list[float] | None:
    """高斯消去（部分樞軸）解線性方程組；奇異時回 None。"""
    n = len(rhs)
    aug = [row[:] + [rhs[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-12:
            return None
        aug[col], aug[pivot] = aug[pivot], aug[col]
        for row in range(n):
            if row == col:
                continue
            factor = aug[row][col] / aug[col][col]
            for k in range(col, n + 1):
                aug[row][k] -= factor * aug[col][k]
    return [aug[i][n] / aug[i][i] for i in range(n)]


def fit_logistic(
    rows: list[list[float]], labels: list[int], iters: int = 30
) -> list[float] | None:
    """以 IRLS（Newton-Raphson）擬合邏輯迴歸，回傳 [截距, w1, w2]。

    刻意不用 scikit-learn：本專案的 requirements.txt 沒有它，而這裡只有兩個
    特徵、幾百筆樣本，為一個離線腳本增加相依不划算。
    """
    design = [[1.0, *row] for row in rows]
    dim = len(design[0])
    weights = [0.0] * dim
    for _ in range(iters):
        grad = [0.0] * dim
        hess = [[0.0] * dim for _ in range(dim)]
        for xi, yi in zip(design, labels):
            z = sum(w * x for w, x in zip(weights, xi))
            prob = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            var = max(prob * (1.0 - prob), 1e-9)
            for a in range(dim):
                grad[a] += (yi - prob) * xi[a]
                for b in range(dim):
                    hess[a][b] += var * xi[a] * xi[b]
        for a in range(dim):
            grad[a] -= L2 * weights[a]
            hess[a][a] += L2
        step = _solve(hess, grad)
        if step is None:
            return None
        weights = [w + s for w, s in zip(weights, step)]
        if max(abs(s) for s in step) < 1e-9:
            break
    return weights


def _apply(weights: list[float], row: list[float]) -> float:
    z = weights[0] + sum(w * x for w, x in zip(weights[1:], row))
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


def cv_brier(feats: list[list[float]], labels: list[int]) -> tuple[float, float] | None:
    """回傳 (常數版 Brier, 微調版 Brier)，皆為 CV_FOLDS 折交叉驗證。

    用途是把關：係數只有在**留出資料上**真的比常數好時才值得寫進校準表。
    樣本內一定看起來更好，那個數字不能拿來做決定。

    折的切法用 index % k，不打亂——評測輸出的順序來自測試集，本身沒有排序意義，
    而固定切法讓同一份資料重跑得到同一組數字（可重現比隨機打亂更重要）。
    """
    n = len(feats)
    if n < CV_FOLDS * 2:
        return None
    pred_const = [0.0] * n
    pred_coef = [0.0] * n
    for fold in range(CV_FOLDS):
        train = [i for i in range(n) if i % CV_FOLDS != fold]
        test = [i for i in range(n) if i % CV_FOLDS == fold]
        ys = [labels[i] for i in train]
        if not test or len(set(ys)) < 2:
            return None
        const = (sum(ys) + SMOOTH) / (len(ys) + 2 * SMOOTH)
        weights = fit_logistic([feats[i] for i in train], ys)
        if weights is None:
            return None
        for i in test:
            pred_const[i] = const
            pred_coef[i] = _apply(weights, feats[i])
    brier = lambda p: sum((pi - yi) ** 2 for pi, yi in zip(p, labels)) / n
    return brier(pred_const), brier(pred_coef)


def load_sim_cache(path: Path) -> dict[str, list[tuple[float, bool]]]:
    """讀入 build_sim_cache.py 產生的檢索快取。"""
    cache: dict[str, list[tuple[float, bool]]] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            record = json.loads(line)
            cache[record["id"]] = [
                (float(c["similarity"]), bool(c["is_scam"]))
                for c in record["candidates"]
            ]
    return cache


def main() -> None:
    parser = argparse.ArgumentParser(description="擬合風險分數校準表（四格）")
    parser.add_argument(
        "--eval",
        default=EVAL_DIR / "eval_v6_maxlen.jsonl",
        help="評測逐筆結果（JSON Lines）",
    )
    parser.add_argument(
        "--out",
        default=PROJECT_ROOT / "risk_calibration.json",
        help="校準表輸出路徑",
    )
    parser.add_argument(
        "--sim-cache",
        default=EVAL_DIR / "sim_cache_current_kb.jsonl",
        help="檢索特徵快取（由 build_sim_cache.py 產生）；省略則只做四格常數",
    )
    parser.add_argument("--dry-run", action="store_true", help="只印結果，不寫檔")
    args = parser.parse_args()

    with Path(args.eval).open(encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    rows = [r for r in rows if "predicted" in r and "expected" in r]
    print(f"評測樣本 {len(rows)} 筆")

    sim_cache: dict[str, list[tuple[float, bool]]] = {}
    sim_path = Path(args.sim_cache) if args.sim_cache else None
    if sim_path and sim_path.exists():
        sim_cache = load_sim_cache(sim_path)
        print(f"檢索特徵快取：{sim_path}（{len(sim_cache)} 筆）")
    else:
        print(f"⚠ 找不到檢索特徵快取（{sim_path}），只產生四格常數；"
              "llm 兩格將沒有相似度微調，risk_level 的 mid 不會出現")

    groups: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["decided_by"], int(r["predicted"]))].append(r)

    cells: list[dict] = []
    print()
    for (decided_by, predicted), group in sorted(groups.items()):
        labels = [int(r["expected"]) for r in group]
        n = len(labels)
        scam = sum(labels)
        risk = round((scam + SMOOTH) / (n + 2 * SMOOTH), 4)
        warn = f"   ⚠ 樣本不足 {MIN_CELL} 筆，此格的機率可信度低" if n < MIN_CELL else ""
        print(
            f"  {decided_by:>4} / predicted={predicted}  n={n:>4}  "
            f"實際詐騙率 {scam / n:.4f}  → risk_score {risk}{warn}"
        )
        cell = {
            "decided_by": decided_by,
            "predicted": predicted,
            "n": n,
            "scam": scam,
            "risk": risk,
        }

        if decided_by in SIMILARITY_SOURCES and sim_cache:
            feats, ys = [], []
            for r in group:
                f = extract_features(sim_cache.get(r["id"], []))
                if f is not None:
                    feats.append(f)
                    ys.append(int(r["expected"]))
            if len(feats) < MIN_CELL_FOR_COEF or len(set(ys)) < 2:
                print(f"        （可用樣本 {len(feats)} 筆，不足 {MIN_CELL_FOR_COEF} "
                      "或標籤單一，不做相似度微調）")
            else:
                scores = cv_brier(feats, ys)
                weights = fit_logistic(feats, ys)
                if weights is None or scores is None:
                    print("        （IRLS 未收斂或樣本不足以交叉驗證，不做相似度微調）")
                elif scores[1] >= scores[0]:
                    # 把關：留出資料上沒有比常數好就不寫係數，執行期自動退回常數
                    print(f"        （CV Brier 常數 {scores[0]:.4f} → 微調 "
                          f"{scores[1]:.4f}，沒有改善，不寫係數）")
                else:
                    cell["coef"] = {
                        "features": FEATURE_NAMES,
                        "intercept": round(weights[0], 6),
                        "weights": [round(w, 6) for w in weights[1:]],
                        "n": len(feats),
                    }
                    preds = sorted(_apply(weights, f) for f in feats)
                    p5 = preds[int(len(preds) * 0.05)]
                    p95 = preds[int(len(preds) * 0.95)]
                    print(f"        + 相似度微調（n={len(feats)}）："
                          f"CV Brier {scores[0]:.4f} → {scores[1]:.4f}"
                          f"（{scores[0] - scores[1]:+.4f}）"
                          f"，risk 的 p5~p95 = {p5:.3f}~{p95:.3f}")

        cells.append(cell)

    missing = {("gate", 0), ("gate", 1), ("llm", 0), ("llm", 1)} - set(groups)
    if missing:
        print(f"\n⚠ 評測結果缺少這些格子：{sorted(missing)}；"
              "缺的格子在執行期會讓 risk_score 回 None。")

    payload = {
        "model": settings.OLLAMA_MODEL,
        "embedding_model": settings.EMBEDDING_MODEL,
        "gate_top_n": settings.RAG_GATE_TOP_N,
        "gate_similarity": settings.RAG_GATE_SIMILARITY,
        "eval_file": str(args.eval),
        "eval_samples": len(rows),
        "fitted_at": date.today().isoformat(),
        "smoothing": SMOOTH,
        "cells": cells,
    }
    if args.dry_run:
        print("\n（--dry-run：未寫檔）")
        return
    Path(args.out).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n校準表已寫入 {args.out}（綁定模型 {settings.OLLAMA_MODEL}）")


if __name__ == "__main__":
    main()
