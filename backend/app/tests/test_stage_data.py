"""階段訓練資料管線的把關測試。

這條管線的失效多半是**靜默**的：訓練與推論的提示詞差一個空格、前綴切片
洩題到測試集、測試集混進合成資料、階段標籤與線上的聚合邏輯對不上——
四種都不會報錯，只會讓評測數字變成一個看起來很漂亮的假象。所以這裡釘的
不是「程式跑得動」，而是那幾條會靜默壞掉的約束。

不需要 MySQL / GPU / Ollama；不依賴已產生的資料檔（缺檔的整合檢查會 skip）。
"""

import csv
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

from app.services.stage_service import (
    STAGE_BY_LABEL,
    STAGE_INDEX,
    STAGE_KEY_ORDER,
    STAGES,
    StageService,
)
from scripts.build_stage_corpus import (
    build_from_layout,
    looks_like_transcript,
    segment_messages,
    split_compressed,
    to_turns,
)
from scripts.build_stage_dataset import (
    MIN_REAL_RATIO,
    REAL_SOURCE,
    REAL_SOURCES,
    SENDER_RANK,
    apply_verdict,
    balance_synthetic,
    build_sample,
    conversation_key,
    dedupe_by_conversation,
    expand,
    pick_prefix_lengths,
    prefix_tier,
    split_ids,
)
from scripts.export_label_sheet import (
    COLUMN_SENDER,
    COLUMNS as SHEET_COLUMNS,
    build_rows,
    rows_from_text,
    shard,
)
from scripts.detect_explicit_images import apply_confirmed, tile_boxes
from scripts.export_review_page import (
    build as build_review_pages,
    read_blocklist,
    stratify,
    to_rows,
)
from scripts.import_label_sheet import build_records, merge_into_corpus
from scripts.layout_transcribe import (
    confidence_reason,
    is_chrome,
    merge_same_line,
    resolve_sides,
    side_of,
)
from scripts.label_stage_turns import aggregate, combine, rule_stage
from scripts.transplant_ocr_text import source_lines, transplant_record

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"


def _issues() -> dict[str, list[str]]:
    """import_label_sheet.build_records() 用來回報問題的空殼。"""
    return {
        "blank": [],
        "unknown": [],
        "orphan_merge": [],
        "too_short": [],
        "no_counterpart": [],
    }


def _record(*texts: str) -> dict:
    """組一段全部由對方發言的對話。"""
    return {
        "id": "conv-test-1",
        "source": "synthetic-split",
        "scam_type": "假投資詐騙",
        "turns": [{"sender": "them", "text": text} for text in texts],
    }


# ---------------------------------------------------------------------------
# 1. 訓練與推論的提示詞必須逐字一致
# ---------------------------------------------------------------------------


def test_training_user_prompt_matches_inference_verbatim():
    """微調樣本的 user 訊息必須與 StageService.format_user_prompt() 逐字相同。

    這個專案已經為「訓練與推論不一致」付過學費（README：推論端多加一段提示詞，
    347 筆子集上誤報 54 → 67）。差一個字元不會有人發現，只會讓模型在線上
    面對訓練分布外的輸入。
    """
    turns = [
        {"sender": "them", "text": "老師帶單穩賺不賠"},
        {"sender": "me", "text": "真的嗎"},
        {"sender": "them", "text": "先匯三萬到這個帳號"},
    ]
    sample = build_sample(turns, "extraction", "假投資詐騙", "先匯三萬")

    from app.schemas.rag import ConversationMessage
    from app.services.stage_service import trim_conversation

    expected = StageService.format_user_prompt(
        trim_conversation(
            [ConversationMessage(sender=t["sender"], text=t["text"]) for t in turns]
        ),
        "假投資詐騙",
    )
    assert sample["messages"][1]["content"] == expected
    # system 也必須是同一份 prompt 檔，不能是複製的字串
    from app.services.stage_service import STAGE_SYSTEM_PROMPT

    assert sample["messages"][0]["content"] == STAGE_SYSTEM_PROMPT


def test_training_assistant_key_order_and_enum():
    """assistant 的鍵序必須等於 STAGE_KEY_ORDER，階段名必須在 STAGES 內。

    鍵序是微調契約的一部分；階段名對不回 slug 的話，線上解析會直接把
    整個判定丟掉（parse_response 回 None），等於階段功能靜默失效。
    """
    sample = build_sample(
        [{"sender": "them", "text": "你好"}], "contact", None, "你好"
    )
    assistant = json.loads(sample["messages"][2]["content"])
    assert list(assistant) == STAGE_KEY_ORDER
    assert assistant["詐騙階段"] in {label for _, label in STAGES}
    assert STAGE_BY_LABEL[assistant["詐騙階段"]] == "contact"


# ---------------------------------------------------------------------------
# 2. 標籤定義必須與線上的聚合邏輯一致
# ---------------------------------------------------------------------------


def test_prefix_aggregation_is_cumulative_max():
    """前綴階段 = 前綴內所有輪次的 max，與 stage_service._higher() 同一個定義。

    標籤若用別的定義（例如取最後一輪的階段），訓練出來的模型在線上
    會與單調性調和互相打架。
    """
    stages = ["contact", None, "baiting", "grooming", "extraction", None]
    assert aggregate(stages) == [
        "contact",
        "contact",
        "baiting",
        "baiting",  # grooming 比 baiting 早，不得讓階段退回
        "extraction",
        "extraction",
    ]


def test_prefix_aggregation_never_decreases():
    """性質檢查：聚合結果必須單調不減。"""
    stages = ["extraction", "contact", "grooming", "closing", "contact"]
    result = aggregate(stages)
    indices = [STAGE_INDEX[s] for s in result if s]
    assert indices == sorted(indices)


def test_combine_takes_latest_stage_and_flags_disagreement():
    """投票合成取最晚的階段，並把跨越索取財物的分歧標出來。"""
    assert combine({"a": "baiting", "b": "baiting"}) == ("baiting", "agree")
    assert combine({"a": "grooming", "b": "extraction"}) == (
        "extraction",
        "cross-extraction",
    )
    assert combine({"a": "contact", "b": "grooming"}) == ("grooming", "split2")
    assert combine({"a": None}) == (None, "no-vote")


# ---------------------------------------------------------------------------
# 3. 切分不得洩題，測試集不得混入合成資料
# ---------------------------------------------------------------------------


def test_split_never_leaks_a_conversation_across_sets():
    """同一段對話的前綴必須整段落在同一側。

    前綴之間高度重疊（前 3 輪是前 4 輪的子集），以樣本切分等於直接洩題，
    評測數字會虛高且完全查不出原因。
    """
    labels = [
        {"id": f"conv-cofacts-{i}", "source": REAL_SOURCE, "stage": "extraction"}
        for i in range(10)
    ] + [
        {"id": f"conv-syn-{i}", "source": "synthetic-split", "stage": "baiting"}
        for i in range(10)
    ]
    train, test = split_ids(labels, {}, test_size=4)

    assert not (train & test)
    assert len(test) == 4
    # 測試集只能收真實對話
    assert all(row_id.startswith("conv-cofacts-") for row_id in test)


def test_test_set_prefers_human_reviewed_conversations():
    """有人工審核的對話優先進測試集——那是唯一能信的基準。"""
    labels = [
        {"id": f"conv-cofacts-{i}", "source": REAL_SOURCE, "stage": "extraction"}
        for i in range(10)
    ]
    verdicts = {"conv-cofacts-7": {"stage": "closing", "extraction_turn": 2}}
    _, test = split_ids(labels, verdicts, test_size=3)
    assert "conv-cofacts-7" in test


@pytest.mark.skipif(
    not (DATA_DIR / "stage_test.jsonl").exists(), reason="尚未產生測試集"
)
def test_generated_test_set_is_entirely_real():
    """已產生的測試集必須 100% 來自真實對話轉錄，一筆合成的都不能有。"""
    with (DATA_DIR / "stage_test.jsonl").open(encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    assert rows, "測試集是空的"
    # 允許多個真實來源（規則分派的 cofacts-transcript 與人工分派的 cofacts-manual），
    # 但一筆合成的都不行
    assert {row["source"] for row in rows} <= set(REAL_SOURCES)
    assert all(row["stage"] in STAGE_INDEX for row in rows)


@pytest.mark.skipif(
    not (DATA_DIR / "stage_finetune.jsonl").exists(), reason="尚未產生訓練集"
)
def test_generated_train_set_has_no_test_conversations():
    """訓練集不得含有測試集裡的任何一段對話（以 user 提示詞比對）。"""
    with (DATA_DIR / "stage_test.jsonl").open(encoding="utf-8") as fh:
        test_rows = [json.loads(line) for line in fh if line.strip()]
    test_prompts = {
        StageService.format_user_prompt(
            [
                __import__("app.schemas.rag", fromlist=["ConversationMessage"]).ConversationMessage(
                    sender=t["sender"], text=t["text"]
                )
                for t in row["turns"]
            ],
            row.get("scam_type"),
        )
        for row in test_rows[:40]  # 抽樣即可，全比對太慢
    }
    with (DATA_DIR / "stage_finetune.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            prompt = json.loads(line)["messages"][1]["content"]
            assert prompt not in test_prompts, "訓練集出現了測試集的對話"


# ---------------------------------------------------------------------------
# 4. 合成資料佔比的防護
# ---------------------------------------------------------------------------


def test_balance_reaches_the_real_data_floor():
    """--balance 必須把真實對話佔比拉到 MIN_REAL_RATIO 以上。"""
    real = [{"messages": []} for _ in range(50)]
    synthetic = [{"messages": []} for _ in range(5000)]
    balanced = balance_synthetic(real, synthetic)
    assert len(real) / len(balanced) >= MIN_REAL_RATIO


def test_balance_keeps_everything_when_already_balanced():
    """本來就達標時不該白白丟掉資料。"""
    real = [{"messages": []} for _ in range(50)]
    synthetic = [{"messages": []} for _ in range(100)]
    assert len(balance_synthetic(real, synthetic)) == 150


# ---------------------------------------------------------------------------
# 5. 人工審核結果的套用
# ---------------------------------------------------------------------------


def test_apply_verdict_rebuilds_the_whole_prefix_sequence():
    """人工只填兩格，整條前綴序列要能被正確還原。"""
    weak = ["contact", "extraction", "extraction", "extraction", "extraction"]
    verdict = {"stage": "closing", "extraction_turn": 4}
    result = apply_verdict(weak, verdict)

    # 第 4 輪之前不得高於鋪陳誘餌（弱標籤把階段抬過頭要被壓回來）
    assert result[:3] == ["contact", "baiting", "baiting"]
    # 第 4 輪起至少是索取財物
    assert STAGE_INDEX[result[3]] >= STAGE_INDEX["extraction"]
    # 最後一個前綴等於人工填的最終階段
    assert result[-1] == "closing"


def test_apply_verdict_without_extraction_turn():
    """沒有索取行為的對話（extraction_turn 留空）不得被推到索取財物。"""
    weak = ["contact", "grooming", "extraction"]
    result = apply_verdict(weak, {"stage": "baiting", "extraction_turn": 0})
    assert all(STAGE_INDEX[s] < STAGE_INDEX["extraction"] for s in result if s)
    assert result[-1] == "baiting"


# ---------------------------------------------------------------------------
# 6. 語料切分
# ---------------------------------------------------------------------------


def test_transcript_detection_rejects_webpage_screenshots():
    """判別條件要擋掉詐騙網頁截圖——它們也有時間戳與問號，但不是對話。

    寬鬆的條件實測會撈出 878 筆，其中絕大多數是一頁式賣場與社團貼文；
    把網頁截圖當對話餵進訓練集，比沒有資料更糟。
    """
    webpage = "23:46\n離線.hkgift.xyz\n親愛的顧客:\n恭喜您中獎\n請問您滿意嗎?\nOK"
    assert not looks_like_transcript(webpage)

    dialogue = (
        "8:25\n你好 我看你想找工作\n已讀\n請問是什麼類型的呢?\n11:03\n"
        "圓珠筆組裝\n已讀\n公司在哪裡呢?\n12:40\n在新北\n"
    )
    assert looks_like_transcript(dialogue)


def test_segment_messages_splits_on_boundaries_not_on_lines():
    """一「行」是截圖的換行片段，不是一則訊息——要照時間戳／已讀切。"""
    text = "21:16\n群裡也有很\n多知識我。\n已讀\n已經出來了\n21:42\n可以開始了"
    messages = segment_messages(text)
    assert "群裡也有很多知識我。" in messages
    assert len(messages) >= 2


def test_to_turns_does_not_merge_consecutive_same_sender():
    """不得合併連續同一說話者的訊息。

    合併會在說話者判錯時把整段對話塌成一輪（實測 118 段有大半塌成 1 輪），
    也會抹掉「一來一往的節奏」——那是真實轉錄唯一勝過合成資料的地方。
    """
    turns = to_turns(["第一則", "第二則", "第三則"], ["them", "them", "me"])
    assert len(turns) == 3
    assert [t["sender"] for t in turns] == ["them", "them", "me"]


def test_split_compressed_breaks_multi_stage_message_into_turns():
    """壓縮的多階段話術要被拆成多輪，而不是留成一整段。"""
    text = (
        "我在澳洲做礦業投資，最近想回台灣定居。"
        "我在玩泰達幣USDT的搬磚套利，價差穩定，我可以教你。"
        "你先入金六萬，我教你第一單怎麼下。"
    )
    turns = split_compressed(text)
    assert len(turns) >= 2
    assert all(turn["sender"] == "them" for turn in turns)
    # 拆完之後最後一輪應該落在索取財物（規則看得出來）
    assert rule_stage(turns[-1]["text"]) == "extraction"


def test_prefix_lengths_start_at_one_and_include_the_full_conversation():
    """必須含 1 輪的前綴：接觸建立幾乎只在第一則訊息成立。

    從 2 輪起跳的話，訓練集裡「接觸建立」只剩 0.1%（實測），
    等於訓練出一顆永遠不會判接觸建立的模型。
    """
    lengths = pick_prefix_lengths(5)
    assert lengths[0] == 1
    assert lengths[-1] == 5


def test_expand_skips_unlabelled_prefixes_without_dropping_the_conversation():
    """沒有標籤的前綴跳過即可，不該連整段對話一起丟。"""
    record = _record("你好", "保證獲利", "先匯款")
    label = {
        "turn_stages": [None, "baiting", "extraction"],
        "prefix_stages": [None, "baiting", "extraction"],
    }
    samples = expand(record, label, as_eval=False)
    assert len(samples) == 2  # 第一個前綴無標籤被跳過，其餘保留


def test_expand_eval_format_carries_turns_for_the_online_pipeline():
    """評測格式必須帶原始 turns，才能餵進 StageService 走完整線上路徑。"""
    record = _record("你好", "先匯款到這個帳號")
    label = {
        "turn_stages": ["contact", "extraction"],
        "prefix_stages": ["contact", "extraction"],
    }
    samples = expand(record, label, as_eval=True)
    assert samples[0]["turns"] == record["turns"][:1]
    assert samples[-1]["stage"] == "extraction"
    assert samples[-1]["conversation_id"] == record["id"]


# ---------------------------------------------------------------------------
# 11. 人工標註工作表：匯出 → 填寫 → 收回的往返
# ---------------------------------------------------------------------------
#
# 這一段釘的是「人工花幾十小時填的東西不能在收回時被默默改掉」。
# 往返過程有四個會靜默出錯的地方：欄位對不上、序號排序用字串比、
# 「接上一列」併錯對象、以及未填的列被當成某個預設值收進訓練資料。


def _sheet(tmp_path, rows: list[list], name: str = "sheet.csv") -> Path:
    """寫一份工作表；欄位順序與 export_label_sheet 一致。"""
    path = tmp_path / name
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(SHEET_COLUMNS)
        writer.writerows(rows)
    return path


def test_export_splits_to_raw_lines_not_to_guessed_messages():
    """一列是一行 OCR 原文，而不是自動切好的訊息。

    切得比較細是刻意的：人工在 Excel 裡「併起來」只要打一個字，
    「拆開」卻要插列剪貼。所以自動斷句寧可切碎，不可切粗。
    """
    text = "你好我是專員\n下午1:39\n因為我們賺的是美金\n我們是不是要\n已讀\n好的"
    rows = rows_from_text(text)
    contents = [text for text, _ in rows]

    assert "因為我們賺的是美金" in contents
    assert "我們是不是要" in contents, "被換行切開的兩半不可以在匯出時就併掉"
    assert not any("下午1:39" in text for text in contents), "時間戳不是訊息內容"


def test_export_keeps_read_mark_as_a_hint_not_as_content():
    """已讀是判斷「這則是我傳的」最有力的客觀線索，要留在線索欄。"""
    rows = rows_from_text("我再想想\n已讀 下午1:40")
    assert rows[0][0] == "我再想想"
    assert "已讀" in rows[0][1]


def test_export_answer_column_is_always_blank():
    """答案欄一律留空——預填的錯猜測比空白更糟，人會直接放行。"""
    record = {
        "article_id": "a1",
        "text": "你好我是專員\n請問公司在哪\n我們公司在台北\n好的",
        "transcript_signals": {"timestamps": 3, "read_marks": 2, "replies": 2},
    }
    rows, used = build_rows([record])
    assert used == 1
    sender_column = SHEET_COLUMNS.index(COLUMN_SENDER)
    assert all(row[sender_column] == "" for row in rows)


def test_shard_never_splits_one_conversation_across_annotators():
    """同一段對話不能拆給兩個人——說話者要靠上下文推斷，切開就毀了判斷依據。"""
    rows = [[f"conv{c}", i, "", f"訊息{i}", "", "", ""] for c in range(6) for i in range(5)]
    buckets = shard(rows, 3)

    assert sum(len(bucket) for bucket in buckets) == len(rows)
    for bucket in buckets:
        owned = {row[0] for row in bucket}
        for other in buckets:
            if other is not bucket:
                assert owned.isdisjoint({row[0] for row in other})


def test_import_merges_continuation_rows_into_the_previous_turn(tmp_path):
    """填「3」的列要接到上一列，中文之間不加空白。"""
    path = _sheet(
        tmp_path,
        [
            ["a1", 1, "1", "因為我們賺的是美金", "", "假投資詐騙", ""],
            ["a1", 2, "3", "我們是不是要換成台幣", "", "", ""],
            ["a1", 3, "2", "好的", "", "", ""],
            ["a1", 4, "1", "你先下載交易所", "", "", ""],
        ],
    )
    issues = _issues()
    records = build_records([path], {}, issues)

    assert len(records) == 1
    turns = records[0]["turns"]
    assert turns[0] == {"sender": "them", "text": "因為我們賺的是美金我們是不是要換成台幣"}
    assert [turn["sender"] for turn in turns] == ["them", "me", "them"]


def test_import_sorts_inserted_rows_by_numeric_sequence(tmp_path):
    """插列用小數序號（3 和 4 之間填 3.5），排序必須照數值不是照字串。

    字串排序會把 "10" 排在 "2" 前面，整段對話的順序就毀了——
    而順序錯掉之後階段標籤全部跟著錯，卻不會有任何錯誤訊息。
    """
    path = _sheet(
        tmp_path,
        [
            ["a1", 1, "1", "第一句", "", "", ""],
            ["a1", 10, "1", "第十句", "", "", ""],
            ["a1", 2, "1", "第二句", "", "", ""],
            ["a1", "1.5", "2", "插進來的", "", "", ""],
        ],
    )
    records = build_records([path], {}, _issues())
    assert [turn["text"] for turn in records[0]["turns"]] == [
        "第一句",
        "插進來的",
        "第二句",
        "第十句",
    ]


def test_import_drops_blank_rows_and_reports_them(tmp_path):
    """未填的列要丟掉並列進待辦，不可以套用任何預設值。

    「沒填」與「填了對方」是完全不同的事。把未填當成對方，等於把人工還沒
    看過的資料混進 gold 標註裡，而且無聲無息。
    """
    path = _sheet(
        tmp_path,
        [
            ["a1", 1, "1", "你好我是專員", "", "", ""],
            ["a1", 2, "", "這列還沒標", "", "", ""],
            ["a1", 3, "2", "好的", "", "", ""],
            ["a1", 4, "0", "介面雜訊", "", "", ""],
            ["a1", 5, "1", "你先下載交易所", "", "", ""],
        ],
    )
    issues = _issues()
    records = build_records([path], {}, issues)

    texts = [turn["text"] for turn in records[0]["turns"]]
    assert "這列還沒標" not in texts
    assert "介面雜訊" not in texts
    assert len(issues["blank"]) == 1


def test_import_accepts_the_aliases_people_actually_type(tmp_path):
    """多人協作時每個人習慣不同，數字、中文、英文都要收。"""
    path = _sheet(
        tmp_path,
        [
            ["a1", 1, "對方", "你好我是專員", "", "", ""],
            ["a1", 2, "我", "好的", "", "", ""],
            ["a1", 3, "them", "下載這個", "", "", ""],
            ["a1", 4, "ME", "嗯", "", "", ""],
        ],
    )
    records = build_records([path], {}, _issues())
    assert [turn["sender"] for turn in records[0]["turns"]] == [
        "them",
        "me",
        "them",
        "me",
    ]


def test_import_skips_conversations_with_no_counterpart_message(tmp_path):
    """整段都是「我」在說話的，不是詐騙對話，不能進語料。"""
    path = _sheet(
        tmp_path,
        [
            ["a1", 1, "2", "早安", "", "", ""],
            ["a1", 2, "2", "在嗎", "", "", ""],
            ["a1", 3, "2", "好", "", "", ""],
        ],
    )
    issues = _issues()
    records = build_records([path], {}, issues)
    assert records == []
    assert issues["no_counterpart"] == ["a1"]


def test_import_is_idempotent_on_reruns(tmp_path):
    """同一段對話重複匯入要覆蓋而不是長出第二筆。

    標一半先匯入看結果、之後再補標，是很自然的用法。
    """
    corpus = tmp_path / "corpus.jsonl"
    record = {
        "id": "conv-manual-a1",
        "source": "cofacts-manual",
        "scam_type": "假投資詐騙",
        "turns": [{"sender": "them", "text": "你好"}],
    }
    merge_into_corpus(corpus, [record])
    added, replaced, _ = merge_into_corpus(corpus, [record])

    rows = [json.loads(line) for line in corpus.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert (added, replaced) == (0, 1)


def test_import_preserves_other_sources_in_the_corpus(tmp_path):
    """覆寫語料檔時不可以動到別批資料。"""
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text(
        json.dumps(
            {"id": "conv-syn-1", "source": "synthetic-split", "turns": []},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    merge_into_corpus(
        corpus,
        [{"id": "conv-manual-a1", "source": "cofacts-manual", "turns": []}],
    )

    rows = [json.loads(line) for line in corpus.read_text(encoding="utf-8").splitlines()]
    assert {row["id"] for row in rows} == {"conv-syn-1", "conv-manual-a1"}


def test_manual_source_counts_as_real_for_the_test_set():
    """人工標的那批也是真實對話，必須能進測試集。

    測試集只收真實資料的規則若只認得舊的 source 值，新標的資料就會被
    默默排除，人工的工夫等於白費。
    """
    assert "cofacts-manual" in REAL_SOURCES
    assert REAL_SOURCE in REAL_SOURCES


# ---------------------------------------------------------------------------
# 12. 版面重建：從截圖座標判訊息邊界與發送者
# ---------------------------------------------------------------------------
#
# 這一段釘的是「用座標判發送者」這件事會靜默壞掉的四個地方：
# 短的末行被丟掉（內容遺失）、判不出左右時用擲硬幣的方式硬塞（標籤汙染）、
# 裁切過的截圖被當成介面外框切掉、以及同一段對話的三個版本
# （規則／版面／人工）同時存在時造成的洩題。


def _box(x0, x1, y0, y1, text="訊息", side=None):
    return {"text": text, "score": 0.9, "x0": x0, "x1": x1, "y0": y0, "y1": y1, "side": side}


def test_same_line_boxes_merge_before_side_is_decided():
    """OCR 把一行切成兩個框時要先併起來再判左右。

    不先併，短的那半會兩邊邊界都碰不到而被丟掉——那是實質的內容遺失
    （實測「每個人都是實名戶」與「提領也是這樣」是同一行的兩個框）。
    """
    merged = merge_same_line(
        [
            _box(83, 285, 554, 576, "每個人都是實名戶"),
            _box(298, 432, 556, 574, "提領也是這樣"),
            _box(95, 370, 620, 644, "下一行"),
        ]
    )

    assert len(merged) == 2
    assert merged[0]["text"] == "每個人都是實名戶提領也是這樣"
    assert merged[0]["x0"] == 83 and merged[0]["x1"] == 432


def test_short_last_line_of_a_right_bubble_keeps_its_sender():
    """靠右泡泡的末行比較短時，兩邊邊界都碰不到，要繼承上一行。

    泡泡整體靠右，但泡泡內的文字是靠左排的。實測「換轉給我就好了」
    x 只到 0.69W，用邊界判會判不出來。
    """
    width = 600
    boxes = [
        _box(217, 568, 262, 286, "我剛本來想你教我", side="me"),
        _box(217, 415, 288, 314, "換轉給我就好了", side=None),
    ]
    resolved = resolve_sides(boxes, width)

    assert [box["side"] for box in resolved] == ["me", "me"]


def test_unresolvable_line_is_dropped_not_guessed():
    """左緣對不上任何鄰居的框寧可丟掉，不可猜。

    猜錯的發送者會直接變成訓練標籤裡的錯誤，而且不會有任何徵兆；
    少一行只是少一行。
    """
    width = 600
    boxes = [
        _box(90, 400, 100, 124, "對方說的話", side="them"),
        _box(300, 380, 200, 224, "置中的系統列", side=None),
    ]
    resolved = resolve_sides(boxes, width)

    assert [box["text"] for box in resolved] == ["對方說的話"]


def test_side_is_decided_by_which_margin_the_box_touches():
    width = 600
    assert side_of(_box(81, 260, 141, 167), width) == "them"
    assert side_of(_box(228, 568, 348, 372), width) == "me"
    # 橫跨整個畫面＝OCR 把左右兩欄讀成同一行，不能當成任何一方
    assert side_of(_box(60, 570, 400, 424), width) is None


def test_cropped_screenshot_keeps_its_first_message():
    """頂端帶狀區內字數夠多的框要留下。

    有些截圖是裁切過或多張拼接的，第一則訊息就貼在最上面
    （實測 0hlYu5oBElZa 的首則訊息在 y=20）。純用 y 座標切會把它當狀態列丟掉。
    """
    width, height = 600, 2915
    message = _box(20, 500, 18, 44, "你有用密戀私密眼號我加你好友")
    header = _box(82, 138, 84, 113, "王之岑")

    assert is_chrome(message, width, height) is False
    assert is_chrome(header, width, height) is True


def test_low_confidence_conversations_are_not_pre_filled():
    """機器判不出來的段落一律留白，逼標註者自己看圖。

    預填的前提是「原圖就在旁邊、確認一眼就好」。信心低的沒有這個前提，
    預填只會變成橡皮圖章。
    """
    record = {
        "article_id": "a1",
        "source_url": "https://cofacts.tw/article/a1",
        "turns": [
            {"sender": "them", "text": "你好", "confidence": "low"},
            {"sender": "me", "text": "嗯", "confidence": "low"},
        ],
    }
    assert [row[2] for row in to_rows(record)] == ["", ""]

    record["turns"] = [{"sender": "them", "text": "你好", "confidence": "high"}]
    assert to_rows(record)[0][2] == "1"


def test_review_page_csv_round_trips_through_the_importer(tmp_path):
    """審核頁匯出的 CSV 要能被既有的匯入腳本原樣讀回。

    頁面是新的、匯入腳本是舊的，欄位只要差一個字就會在收回時整批失效，
    而那時人工的時間已經花掉了。
    """
    record = {
        "article_id": "a1",
        "source_url": "https://cofacts.tw/article/a1",
        "turns": [
            {"sender": "them", "text": "您好我是專員", "confidence": "high"},
            {"sender": "me", "text": "請問是什麼工作", "confidence": "high"},
            {"sender": "them", "text": "先加我LINE", "confidence": "high"},
            {"sender": "them", "text": "然後匯保證金", "confidence": "high"},
        ],
    }
    rows = to_rows(record)
    sheet = _sheet(tmp_path, rows, name="review.csv")

    records = build_records([sheet], {}, _issues())

    assert len(records) == 1
    assert [turn["text"] for turn in records[0]["turns"]] == [
        "您好我是專員",
        "請問是什麼工作",
        "先加我LINE",
        "然後匯保證金",
    ]
    assert [turn["sender"] for turn in records[0]["turns"]] == ["them", "me", "them", "them"]


def test_layout_source_counts_as_real_but_ranks_below_manual():
    """版面判的也是真實對話，但可信度排在人工之後。"""
    assert "cofacts-layout" in REAL_SOURCES
    assert SENDER_RANK["cofacts-manual"] < SENDER_RANK["cofacts-layout"] < SENDER_RANK[REAL_SOURCE]


def test_same_screenshot_never_appears_as_two_conversations():
    """同一張截圖的三個版本只留最可信的一個。

    不去重的話，規則版可能進訓練集、人工版進測試集——同一段對話兩邊都在，
    這是不會報錯的洩題；而且真實對話會被重複計數，讓真實佔比的檢查
    過得莫名其妙地漂亮。
    """
    labels = [
        {"id": "conv-cofacts-a1", "source": "cofacts-transcript", "stage": "baiting"},
        {"id": "conv-layout-a1", "source": "cofacts-layout", "stage": "baiting"},
        {"id": "conv-manual-a1", "source": "cofacts-manual", "stage": "baiting"},
        {"id": "conv-syn-9", "source": "synthetic-split", "stage": "contact"},
    ]
    kept = dedupe_by_conversation(labels)

    assert {row["id"] for row in kept} == {"conv-manual-a1", "conv-syn-9"}
    assert conversation_key("conv-layout-a1") == conversation_key("conv-manual-a1") == "a1"


def test_review_selection_keeps_the_corpus_confidence_mix():
    """挑給人審的 300 段不能全是「機器有把握」的那些。

    照信心排序會讓 300 段全是 high——那批機器本來就 95.6% 準，人工只是在
    確認容易的，而且測試集會變成「只有乾淨截圖」的樣本，量出來的準確率
    對真實流量沒有代表性。這是不會報錯、只會讓數字好看的那種錯。
    """
    records = (
        [{"confidence": "high", "turns": [{"sender": "them", "text": "x"}] * 12} for _ in range(74)]
        + [{"confidence": "medium", "turns": [{"sender": "me", "text": "x"}] * 12} for _ in range(16)]
        + [{"confidence": "low", "turns": [{"sender": "them", "text": "x"}] * 12} for _ in range(10)]
    )
    picked, _ = stratify(records, 50)
    mix = Counter(record["confidence"] for record in picked)

    assert len(picked) == 50
    # 語料是 74/16/10，抽出來的比例要跟得上（各層容許 ±4 段的整數誤差）
    assert abs(mix["high"] - 37) <= 4
    assert abs(mix["medium"] - 8) <= 4
    assert abs(mix["low"] - 5) <= 4


def test_blind_sample_is_representative_too():
    """盲測是從最前面切走的，所以任何前綴的層別比例都要接近語料。

    照層別依序排的話盲測會整批都是 high，量出來的準確率虛高，
    而盲測的全部意義就是量一個不虛高的數字。
    """
    records = (
        [{"confidence": "high", "turns": [{"sender": "them", "text": "x"}] * 12} for _ in range(80)]
        + [{"confidence": "low", "turns": [{"sender": "them", "text": "x"}] * 12} for _ in range(20)]
    )
    prefix = Counter(record["confidence"] for record in stratify(records, 100)[0][:20])

    assert prefix["low"] >= 2  # 20 段裡至少該有 2 段低信心（語料佔 20%）
    assert prefix["high"] >= 12


def test_conflicting_senders_never_reach_the_corpus(tmp_path):
    """已讀與左右邊界互相矛盾的段落不進語料。

    實測那批的已讀一致率只有 39.9%，放進訓練集是在教模型認錯人。
    它們仍然留在 cofacts_layout.jsonl 裡讓審核頁用——人修好之後
    會以 cofacts-manual 的身分回來。
    """
    good = {
        "id": "conv-layout-a1", "article_id": "a1", "confidence": "high",
        "read_mark_checked": 4, "read_mark_agree": 4,
        "turns": [{"sender": "them", "text": "你好"}, {"sender": "me", "text": "嗯"},
                  {"sender": "them", "text": "匯款"}, {"sender": "me", "text": "好"}],
    }
    conflict = {
        "id": "conv-layout-a2", "article_id": "a2", "confidence": "low",
        "read_mark_checked": 5, "read_mark_agree": 1,
        "turns": [{"sender": "them", "text": "你好"}, {"sender": "me", "text": "嗯"},
                  {"sender": "them", "text": "匯款"}, {"sender": "me", "text": "好"}],
    }
    only_me = {
        "id": "conv-layout-a3", "article_id": "a3", "confidence": "low",
        "read_mark_checked": 0, "read_mark_agree": 0,
        "turns": [{"sender": "me", "text": f"第{i}句"} for i in range(4)],
    }
    path = tmp_path / "layout.jsonl"
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in (good, conflict, only_me)) + "\n",
        encoding="utf-8",
    )

    assert confidence_reason(conflict) == "conflict"
    assert confidence_reason(only_me) == "single-side"
    assert [row["id"] for row in build_from_layout(path)] == ["conv-layout-a1"]
    # 需要時仍可整批收進來，但要自己指定
    assert len(build_from_layout(path, include_conflicts=True)) == 2


# ---------------------------------------------------------------------------
# 13. 文字移植：座標用我們的，文字用 Cofacts 的
# ---------------------------------------------------------------------------
#
# 本機 OCR 讀 600px 預覽圖，錯字多（薪資→薪腎、要麻煩老師撥空回覆一下→
# 要爆老酵報空回覆一下）；Cofacts 用原圖跑過一次，文字乾淨但順序亂。
#
# 所以這是一個**一對一指派**問題，不是「幫每個泡泡找一段相似文字」。差別在排他性：
# 逐泡泡搜尋只能孤立地看一對，門檻必須訂高，於是漏掉一堆（實測某段對話 Cofacts
# 有 69 行乾淨文字只用掉 49 行，而沒用到的行裡就有答案）。這一節釘的就是
# 排他性、以及不能把標記或別人的話接到這一則上。


def _layout(*turns: tuple[str, list[str]]) -> dict:
    """組一段版面重建的紀錄：(sender, lines)。"""
    return {
        "article_id": "a1",
        "turns": [
            {"sender": sender, "text": "".join(lines), "lines": list(lines), "confidence": "high"}
            for sender, lines in turns
        ],
    }


def _source(*lines: str) -> dict:
    return {"text": "\n".join(lines)}


def test_transplant_replaces_local_typos_with_cofacts_text():
    """本機讀錯的字要換成 Cofacts 的正確版本。"""
    record = _layout(
        ("them", ["老我想間一下那份工作的薪腎是怎領取"]),
        ("me", ["要爆老酵報空回覆一下"]),
    )
    out = transplant_record(record, _source(
        "老師我想問一下那份工作的薪資是怎麼領取",
        "要麻煩老師撥空回覆一下",
    ))

    assert out["turns"][0]["text"] == "老師我想問一下那份工作的薪資是怎麼領取"
    assert out["turns"][1]["text"] == "要麻煩老師撥空回覆一下"
    # 原文要留著當退路，也用來事後量移植改動了多少
    assert "薪腎" in out["turns"][0]["text_local"]


def test_transplant_reassembles_a_wrapped_bubble_line_by_line():
    """多行泡泡的每一行各自配一行，再接回同一則。"""
    record = _layout(("them", [
        "我們可以直接你跟銀行貨款一定能",
        "過件，但金額會落在20~200萬，我們",
        "有配合的銀行以及行員主管，也會",
        "你做財力證明。",
    ]))
    out = transplant_record(record, _source(
        "我們可以直接幫你跟銀行貸款一定能",
        "過件,但金額會落在20~200萬,我們",
        "有配合的銀行以及行員主管,也會幫",
        "你做財力證明。",
        "完全不相干的另一則訊息",
    ))

    assert "幫你跟銀行貸款" in out["turns"][0]["text"]   # 本機掉了「幫」、把「貸」讀成「貨」
    assert "完全不相干" not in out["turns"][0]["text"]


def test_exclusivity_rescues_a_badly_garbled_line():
    """相似度只有 0.5 的一對，靠排他性也要落在對的位置。

    這是把逐泡泡搜尋換成全域指派的理由：實測
    「即那那需買8月份理快至」對「那那那 希望8月份趕快到」相似度約 0.5，
    舊做法的 0.6 門檻直接放棄，正確答案就躺在來源裡沒被用到。
    """
    record = _layout(
        ("them", ["你就可以領到資跟收益了"]),
        ("me", ["即那那需買8月份理快至"]),
        ("them", ["含的妹妹不用撞心"]),
    )
    out = transplant_record(record, _source(
        "你就可以領到薪資跟收益了",
        "那那那 希望8月份趕快到",
        "會的 妹妹不用擔心",
    ))

    assert out["turns"][1]["text"] == "那那那 希望8月份趕快到"
    assert out["turns"][2]["text"] == "會的 妹妹不用擔心"


def test_one_source_line_is_never_used_by_two_turns():
    """同一段來源行不得配給兩則訊息。

    詐騙話術大量重複，沒有排他性的話第二則會接到第一則的文字。
    """
    record = _layout(
        ("them", ["請問您是要報名活動的人嗎"]),
        ("them", ["請問您是要報名活動的人員"]),
    )
    out = transplant_record(record, _source(
        "請問您是要報名活動的人員嗎",
        "打擾了,請問是要參加我們環島活動的嗎",
    ))

    first, second = (turn["text"] for turn in out["turns"])
    assert first != second, "兩則配到同一段來源文字"


def test_transplant_never_carries_read_marks_into_content():
    """來源行裡的已讀與時間戳不能被當成內容移植進去。

    Cofacts 的 OCR 會把「已讀」黏在內文行裡，不清掉會出現
    「到時候我帳戶變黑的**已讀** 雖然對你來說…」這種句子。
    """
    lines = source_lines("到時候我帳戶變黑的已讀 雖然對你來說這樣講不公平\n已讀\n下午1:40\n11:23")

    assert lines == ["到時候我帳戶變黑的 雖然對你來說這樣講不公平"]


def test_unmatched_lines_keep_local_text_and_get_flagged():
    """配不到就保留原文並標記，不可硬塞一段勉強相近的。

    塞錯的文字比留著錯字更糟：錯字看得出來，塞錯的看起來很通順。
    """
    record = _layout(("them", ["完全不存在於來源的一段話"]))
    out = transplant_record(record, _source("今天天氣真好我們去公園散步吧"))

    assert out["turns"][0]["text"] == "完全不存在於來源的一段話"
    assert out["turns"][0]["text_verified"] is False


def test_transplant_is_idempotent():
    """重跑不得把「已經修好的文字」當成原文存起來。

    text_local 是出錯時的退路，也是事後量改動幅度的基準；被覆蓋就沒了。
    """
    record = _layout(("them", ["老我想間一下那份工作的薪腎是怎領取"]))
    source = _source("老師我想問一下那份工作的薪資是怎麼領取")

    once = transplant_record(record, source)
    twice = transplant_record(once, source)

    assert twice["turns"][0]["text"] == once["turns"][0]["text"]
    assert twice["turns"][0]["text_local"] == "老我想間一下那份工作的薪腎是怎領取"


def test_unverified_turns_are_flagged_for_the_annotator():
    """沒對回 Cofacts 的訊息要在審核頁標「未校對」。

    標註者才知道該優先校哪幾則，不必每一則都逐字比對。
    """
    record = {
        "article_id": "a1",
        "source_url": "https://cofacts.tw/article/a1",
        "turns": [
            {"sender": "them", "text": "已校對過的", "confidence": "high", "text_verified": True},
            {"sender": "me", "text": "沒對上的", "confidence": "high", "text_verified": False},
        ],
    }
    hints = [row[4] for row in to_rows(record)]

    assert "未校對" not in hints[0]
    assert "未校對" in hints[1]


def test_timestamps_inside_a_message_survive():
    """時間戳只清行首行尾，句子中間的不能動。

    版面殘留的時間戳一定貼在行的兩端，但訊息內容本身很可能就在講時間——
    實測「明天中午12:00左右」被整段清成「明天左右」。
    """
    assert source_lines("11:23 你好嗎") == ["你好嗎"]
    assert source_lines("我們都能幫您貸款下來 下午1:40") == ["我們都能幫您貸款下來"]
    assert source_lines("明天中午12:00左右") == ["明天中午12:00左右"]
    assert source_lines("下午1:39") == []


def test_turn_that_lost_content_is_not_marked_verified():
    """移植後大幅變短的訊息不算校對過。

    我們的一行有時是兩行黏起來的（merge_same_line 併過），一對一指派只配得到
    其中一行，另一半就無聲消失——實測 0.7% 的訊息這樣掉了內容，
    而且原本還被標成「已校對」，沒有任何徵兆。
    """
    record = _layout(("them", ["中華民國國防部國家通認傅播委員會"]))
    out = transplant_record(record, _source("中華民國國防部", "另一則完全不同的訊息"))

    assert out["turns"][0]["text_verified"] is False, "掉了一半內容卻標成已校對"


# ── 14. 封鎖清單：把沒救的截圖換掉，但不能動到別人標到一半的進度 ──────
#
# 有些來源截圖是兩張手機畫面橫向並排貼成一張，左右兩欄同一高度的字被 OCR
# 接成同一句，順序沒救、人工也修不了，只能整段換掉。難的不是「換」，
# 是**換的時候不可以讓其他段落跨份**——審核進度是按份存在瀏覽器的
# localStorage，跨份就等於把組員標到一半的東西丟掉。


def _review_record(index: int, confidence: str, turns: int = 12) -> dict:
    """一段夠像樣的審核用紀錄（欄位取 to_rows / page_data 會用到的那些）。"""
    return {
        "article_id": f"a{index:03d}",
        "confidence": confidence,
        "source_url": f"https://cofacts.tw/article/a{index:03d}",
        "turns": [
            {"sender": "them" if i % 2 else "me", "text": f"訊息{i}", "confidence": confidence}
            for i in range(turns)
        ],
    }


def _review_pool() -> list[dict]:
    """語料的縮影：層別比例與長度都不齊，才逼得出 shard() 的裝箱行為。"""
    pool = []
    for index in range(120):
        confidence = "high" if index % 5 else ("medium" if index % 3 else "low")
        pool.append(_review_record(index, confidence, turns=8 + index % 11))
    return pool


def _ids_by_shard(buckets: list[list[list]]) -> list[list[str]]:
    out = []
    for bucket in buckets:
        seen: list[str] = []
        for row in bucket:
            if row[0] not in seen:
                seen.append(row[0])
        out.append(seen)
    return out


def test_blocklist_reads_comments_and_blank_lines(tmp_path):
    """清單是人手動維護的，註解與空行是一定會出現的東西。"""
    path = tmp_path / "blocklist.txt"
    path.write_text(
        "# 這行是說明\n\n  abc123  \ndef456  # 行末註解\n\n",
        encoding="utf-8",
    )
    assert read_blocklist(path) == {"abc123", "def456"}


def test_missing_blocklist_is_not_an_error(tmp_path):
    """新 clone 還沒有這個檔時要當成「沒有封鎖」，不是炸掉。"""
    assert read_blocklist(tmp_path / "not_there.txt") == set()


def test_blocked_segments_disappear_and_are_replaced_in_kind():
    """被封鎖的段落要消失，並且補上**同一信心層**的段落。

    同層補是為了不動到分層比例——那個比例決定測試集有多接近真實流量。
    """
    pool = _review_pool()
    plain, *_ = build_review_pages(pool, limit=40, shards=4)
    blocked = {_ids_by_shard(plain)[1][0], _ids_by_shard(plain)[3][2]}
    patched, chosen, _, swaps = build_review_pages(pool, limit=40, shards=4, blocked=blocked)

    flat = [article_id for lane in _ids_by_shard(patched) for article_id in lane]
    by_id = {record["article_id"]: record for record in pool}

    assert not (blocked & set(flat))
    assert len(flat) == 40
    assert len(swaps) == 2
    for swap in swaps:
        assert swap["in"] is not None, "備取池夠深卻沒補上"
        assert by_id[swap["in"]]["confidence"] == by_id[swap["out"]]["confidence"]


def test_replacing_a_segment_never_moves_anyone_else_across_shards():
    """核心不變式：沒被封鎖的段落，所屬的份不能變。

    shard() 是依列數裝箱的，所以「先剔除再抽樣」會讓四份的內容整個重排。
    這條測試就是在擋那個寫法——它不會報錯，只會無聲地清掉別人的進度。
    """
    pool = _review_pool()
    plain, *_ = build_review_pages(pool, limit=40, shards=4, blind=8)
    blocked = {_ids_by_shard(plain)[0][3], _ids_by_shard(plain)[2][1], _ids_by_shard(plain)[2][5]}
    patched, *_ = build_review_pages(pool, limit=40, shards=4, blind=8, blocked=blocked)

    before, after = _ids_by_shard(plain), _ids_by_shard(patched)
    for index, lane in enumerate(before):
        for article_id in lane:
            if article_id in blocked:
                continue
            assert article_id in after[index], f"{article_id} 從第 {index + 1} 份跑掉了"


def test_blind_page_is_untouched_when_nothing_in_it_is_blocked():
    """盲測頁沒有被封鎖的段落時要一段都不動——它量的是準確率，換人就白量了。"""
    pool = _review_pool()
    plain, _, plain_blind, _ = build_review_pages(pool, limit=40, shards=4, blind=8)
    blind_ids = {record["article_id"] for record in plain_blind}
    blocked = {_ids_by_shard(plain)[0][0]}

    _, _, after_blind, _ = build_review_pages(
        pool, limit=40, shards=4, blind=8, blocked=blocked
    )
    assert {record["article_id"] for record in after_blind} == blind_ids


def test_one_shard_growing_its_blocklist_does_not_disturb_the_others():
    """補位走的是每份自己的跨步子序列，不是大家排隊依序拿。

    依序拿的話，第 1 份多一個洞會把後面每一份拿到的段落全部往後推一格——
    下一輪回報就等於害別人的段落跨份。
    """
    pool = _review_pool()
    plain, *_ = build_review_pages(pool, limit=40, shards=4)
    first, second = _ids_by_shard(plain)[0][0], _ids_by_shard(plain)[0][1]

    one, *_ = build_review_pages(pool, limit=40, shards=4, blocked={first})
    two, *_ = build_review_pages(pool, limit=40, shards=4, blocked={first, second})

    assert _ids_by_shard(one)[1:] == _ids_by_shard(two)[1:]


def test_replacements_are_never_reused():
    """同一段不可以同時補到兩個洞，也不可以補成本來就已經選中的那些。"""
    pool = _review_pool()
    plain, *_ = build_review_pages(pool, limit=40, shards=4)
    blocked = set(_ids_by_shard(plain)[0][:2] + _ids_by_shard(plain)[1][:2])
    patched, *_ = build_review_pages(pool, limit=40, shards=4, blocked=blocked)

    flat = [article_id for lane in _ids_by_shard(patched) for article_id in lane]
    assert len(flat) == len(set(flat))


def test_blocked_segments_stay_out_of_the_training_corpus(tmp_path):
    """審核頁換掉了，語料也要擋——順序亂掉的對話正是階段模型最不該學的東西。"""
    path = tmp_path / "layout.jsonl"
    rows = [
        {
            "id": f"conv-layout-{name}",
            "article_id": name,
            "confidence": "high",
            "read_mark_agree": 3,
            "read_mark_checked": 3,
            "turns": [
                {"sender": "them", "text": "你好"},
                {"sender": "me", "text": "嗨"},
                {"sender": "them", "text": "在嗎"},
                {"sender": "me", "text": "在"},
            ],
        }
        for name in ("keep", "stitched")
    ]
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )

    kept = build_from_layout(path, blocked={"stitched"})
    assert [record["id"] for record in kept] == ["conv-layout-keep"]
    assert len(build_from_layout(path)) == 2, "沒有封鎖清單時不該少收"


def test_merge_into_corpus_removes_dropped_ids(tmp_path):
    """語料檔是附加式的：上游不再產生某段，已經寫進去的那份不會自己消失。"""
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text(
        "".join(
            json.dumps({"id": name, "source": "cofacts-layout", "turns": []}) + "\n"
            for name in ("conv-layout-keep", "conv-layout-stitched")
        ),
        encoding="utf-8",
    )
    added, replaced, dropped = merge_into_corpus(
        corpus,
        [{"id": "conv-layout-keep", "source": "cofacts-layout", "turns": []}],
        drop_ids={"conv-layout-stitched"},
    )

    rows = [json.loads(line) for line in corpus.read_text(encoding="utf-8").splitlines()]
    assert {row["id"] for row in rows} == {"conv-layout-keep"}
    assert (added, replaced, dropped) == (0, 1, 1)


# ── 15. 不雅照片：模型只負責排序，刪除一律要人確認 ──────────────────
#
# LINE 截圖九成是白色 UI，照片常常只佔一小塊，整張丟進分類器會被稀釋掉；
# 而分數分佈很軟（0.5 以上佔 46%），所以自動刪一定誤刪。


def test_sliding_window_covers_the_right_and_bottom_edges():
    """滑窗最後一格要貼齊邊界，否則右側／底部的照片永遠掃不到。"""
    boxes = tile_boxes(600, 594)
    right = max(x for x, _ in boxes)
    bottom = max(y for _, y in boxes)

    assert right + 300 >= 600, "右邊界沒被任何方塊蓋到"
    assert bottom + 300 >= 594, "下邊界沒被任何方塊蓋到"


def test_tall_screenshots_are_tiled_in_both_directions():
    """長截圖實測到 2915px 高：只切 y 不切 x，橫向偏一邊的照片就漏了。"""
    boxes = tile_boxes(600, 2900)

    assert len({x for x, _ in boxes}) > 1, "x 方向沒切"
    assert len({y for _, y in boxes}) > 5, "y 方向切得太少"


def test_applying_confirmed_list_blocks_and_deletes(tmp_path):
    """確認名單要同時做兩件事：加進封鎖清單、刪掉圖檔。

    只加清單的話，不雅圖仍然躺在 eval/cofacts_images/ 裡；
    只刪圖的話，審核頁會出現破圖、語料也還留著那段。
    """
    blocklist = tmp_path / "blocklist.txt"
    blocklist.write_text("# 說明\nold-one\n", encoding="utf-8")
    images = tmp_path / "img"
    images.mkdir()
    for name in ("old-one", "new-one"):
        (images / f"{name}.webp").write_bytes(b"x")
    confirmed = tmp_path / "confirmed.txt"
    confirmed.write_text("# 確認過的\nold-one\nnew-one\n", encoding="utf-8")

    apply_confirmed(confirmed, blocklist_path=blocklist, image_dir=images)

    assert read_blocklist(blocklist) == {"old-one", "new-one"}
    assert list(images.iterdir()) == [], "圖檔沒刪掉"


def test_applying_is_a_no_op_on_dry_run(tmp_path):
    """--dry-run 印一樣的統計但一個位元組都不能動——這一步是不可逆的。"""
    blocklist = tmp_path / "blocklist.txt"
    blocklist.write_text("old-one\n", encoding="utf-8")
    images = tmp_path / "img"
    images.mkdir()
    (images / "new-one.webp").write_bytes(b"x")
    confirmed = tmp_path / "confirmed.txt"
    confirmed.write_text("new-one\n", encoding="utf-8")

    apply_confirmed(confirmed, blocklist_path=blocklist, image_dir=images, dry_run=True)

    assert read_blocklist(blocklist) == {"old-one"}
    assert (images / "new-one.webp").exists()


# ---------------------------------------------------------------------------
# 16. 人工答案的分級：哪一格是人真的看過的
# ---------------------------------------------------------------------------
#
# 人工審核表**只填兩格**（整段的最終階段、第幾輪開始索取財物）時，一段對話裡
# 只有「完整長度」那個前綴是人直接標的。中間的前綴是由 extraction_turn 推出來的
# 下限——方向可信，但沒有人逐格確認過。兩者若都掛 gold，--gold-only 量到的
# 就不再是「模型對上人的答案」，而是四分之三在對推論出來的標籤。
# 填了逐輪轉折點（verdict_transitions）時則相反：每一格都是人指定的，整段都算 gold。
#
# 另一條：規則投不出票（stage 是 None）的對話，正是最值得拿去考模型的那一批。
# 實測 50 段人工標註裡有 16 段屬於這種，用弱標籤當門檻會把它們整批擋在測試集外。


def _labelled(id_: str, *, source: str, stage: str | None) -> dict:
    return {"id": id_, "source": source, "stage": stage, "label_tier": "weak"}


def test_a_human_verdict_makes_a_conversation_eligible_even_without_a_weak_stage():
    """規則投不出票，不代表這段對話不能當考題——有人工答案就該收。"""
    labels = [
        _labelled("conv-manual-a", source="cofacts-manual", stage=None),
        _labelled("conv-manual-b", source="cofacts-manual", stage=None),
    ]
    verdicts = {"conv-manual-a": {"stage": "baiting", "extraction_turn": 0}}

    _, test = split_ids(labels, verdicts, test_size=10)

    assert test == {"conv-manual-a"}, "有人工答案的那段被弱標籤的門檻擋掉了"


def test_only_the_full_length_prefix_counts_as_gold():
    """答案卷只有兩格時：一段對話裡只有最長的那個前綴是人直接標的。"""
    label = {"label_tier": "gold"}

    assert prefix_tier(label, 12, 12) == "gold"
    assert prefix_tier(label, 11, 12) == "derived"
    assert prefix_tier({"label_tier": "weak"}, 12, 12) == "weak"


def test_every_prefix_is_gold_when_the_verdict_gave_transitions():
    """答案卷填了逐輪轉折點時，每一格都是人指定的，整段都算 gold。

    2026-09-21 修的就是這裡：原本的條件看的是底層弱標籤的產生者
    （label_source == "claude"），而 2026-08-31 的人工覆核是把轉折點填進
    verdict_transitions，測試集那 50 段的弱標籤仍是 label_source="rule"——
    於是 444 個人工逐格確認過的前綴有 394 個被標成 derived，--gold-only 只剩 50 筆。
    """
    label = {"label_tier": "gold", "label_source": "rule", "verdict_transitions": True}

    assert prefix_tier(label, 12, 12) == "gold"
    assert prefix_tier(label, 4, 12) == "gold", "人填的轉折點決定了每一個前綴的階段"
    # 轉折點是空的（人只填兩格）就不能享有這個待遇
    assert prefix_tier({**label, "verdict_transitions": False}, 4, 12) == "derived"


def test_derived_prefixes_never_leak_into_the_gold_evaluation():
    """一段十輪的對話展開後，只有那一筆完整前綴可以被 --gold-only 收走。"""
    record = {
        "id": "conv-manual-x",
        "source": "cofacts-manual",
        "scam_type": "假買家詐騙",
        "turns": [{"sender": "them", "text": f"第 {i} 則"} for i in range(1, 11)],
    }
    label = {
        "prefix_stages": ["baiting"] * 9 + ["extraction"],
        "turn_stages": [None] * 9 + ["extraction"],
        "label_tier": "gold",
    }

    samples = expand(record, label, as_eval=True)
    gold = [s for s in samples if s["label_tier"] == "gold"]

    assert len(samples) > 1, "這段對話應該展開出多個前綴，測試才有意義"
    assert [s["id"] for s in gold] == ["conv-manual-x#10"]
    assert gold[0]["stage"] == "extraction"
    assert {s["label_tier"] for s in samples} == {"gold", "derived"}

    # 同一段對話，答案卷改成有轉折點：整段的每一個前綴都進得了 --gold-only
    with_transitions = expand(
        record, {**label, "verdict_transitions": True}, as_eval=True
    )
    assert {s["label_tier"] for s in with_transitions} == {"gold"}


# ---------------------------------------------------------------------------
# 17. 微調的兩條靜默約束：遮罩位置與 loss 等價
# ---------------------------------------------------------------------------
#
# scripts/train_stage_lora.py 有兩個「錯了也不會報錯」的地方：
#
# (1) assistant-only 遮罩錯位。system prompt 佔了每筆樣本 1,135 字裡的絕大部分，
#     而且 17,226 筆完全相同。遮多了會把答案的頭幾個 token 也遮掉（模型學不到
#     JSON 的開頭），遮少了會讓模型花力氣去背它推論時本來就會拿到的文字。
#     兩種都只是「loss 曲線長得有點怪」，不會有任何一行報錯。
#
# (2) 為了塞進 6 GiB VRAM，loss 只在有標籤的位置過 lm_head。這是效能改寫，
#     不該改變數值——但它自己動手做了 shift，shift 差一格同樣不會報錯。
#
# 這一節用假的 tokenizer 與 3 個字的詞表把兩件事釘住，不需要 GPU 也不需要
# 下載任何模型。


class _FakeTokenizer:
    """以字元為單位的假 tokenizer，模板與 Qwen 的 <|im_start|> 形狀相同。"""

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=False):
        rendered = "".join(
            f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in messages
        )
        return rendered + ("<|im_start|>assistant\n" if add_generation_prompt else "")

    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": [ord(char) for char in text]}


def _write_finetune_jsonl(path, answer="{\"詐騙階段\": \"索取財物\"}"):
    record = {
        "messages": [
            {"role": "system", "content": "五階段定義……" * 20},
            {"role": "user", "content": "[對方] 請匯款到這個帳號"},
            {"role": "assistant", "content": answer},
        ]
    }
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    return record


def test_only_the_answer_carries_a_label(tmp_path):
    """遮罩的邊界要正好落在 assistant 內容的第一個字，不多不少。"""
    from scripts.train_stage_lora import build_samples

    path = tmp_path / "finetune.jsonl"
    record = _write_finetune_jsonl(path)
    tokenizer = _FakeTokenizer()

    samples, stats = build_samples(path, tokenizer, max_len=10_000)

    assert stats.kept == 1
    sample = samples[0]
    learned = "".join(
        chr(token) for token, label in zip(sample.input_ids, sample.labels) if label != -100
    )
    # 學的是答案本身加上結束符號——結束符號要學，否則模型不知道什麼時候停。
    assert learned == record["messages"][2]["content"] + "<|im_end|>\n"
    # 被遮掉的那段就是推論時模型本來就會拿到的 prompt，一個字都不多。
    masked = "".join(
        chr(token) for token, label in zip(sample.input_ids, sample.labels) if label == -100
    )
    assert masked == tokenizer.apply_chat_template(
        record["messages"][:-1], add_generation_prompt=True
    )


def test_a_template_that_shifts_the_prompt_is_rejected(tmp_path):
    """模板若不是前綴穩定的，遮罩就會整段錯位——寧可當場炸掉。"""
    from scripts.train_stage_lora import build_samples

    class _ShiftingTokenizer(_FakeTokenizer):
        def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=False):
            rendered = super().apply_chat_template(
                messages, tokenize=tokenize, add_generation_prompt=add_generation_prompt
            )
            # 有答案時才補上的前言：真實世界的版本是模板在多輪時才加的東西。
            return ("<|prelude|>" + rendered) if not add_generation_prompt else rendered

    path = tmp_path / "finetune.jsonl"
    _write_finetune_jsonl(path)

    with pytest.raises(RuntimeError, match="前綴"):
        build_samples(path, _ShiftingTokenizer(), max_len=10_000)


def test_over_long_samples_are_dropped_not_truncated(tmp_path):
    """截斷只能從尾巴截，而尾巴就是答案——寧可整筆不要，也不要餵一筆沒有標籤的。"""
    from scripts.train_stage_lora import build_samples

    path = tmp_path / "finetune.jsonl"
    _write_finetune_jsonl(path)

    samples, stats = build_samples(path, _FakeTokenizer(), max_len=16)

    assert (stats.kept, stats.too_long) == (0, 1)
    assert samples == []


def test_sliced_loss_equals_the_plain_full_logits_loss():
    """省記憶體的寫法要與標準寫法逐值相同，否則省下來的是分數不是記憶體。"""
    torch = pytest.importorskip("torch")
    from scripts.train_stage_lora import sliced_cross_entropy

    torch.manual_seed(0)
    batch, seq, hidden_size, vocab = 2, 7, 4, 11
    hidden = torch.randn(batch, seq, hidden_size)
    head = torch.nn.Linear(hidden_size, vocab, bias=False)

    labels = torch.full((batch, seq), -100)
    labels[0, -3:] = torch.tensor([3, 5, 7])   # 只有答案那幾格有標籤
    labels[1, -2:] = torch.tensor([2, 9])

    sliced, _ = sliced_cross_entropy(hidden, labels, head)

    # 標準寫法：整段算 logits，再照 causal LM 的慣例往左移一格。
    full_logits = head(hidden).float()
    reference = torch.nn.functional.cross_entropy(
        full_logits[:, :-1, :].reshape(-1, vocab), labels[:, 1:].reshape(-1), ignore_index=-100
    )

    assert torch.allclose(sliced, reference, atol=1e-6)


# ---------------------------------------------------------------------------
# 18. 合併之後那份 config：Ollama 讀不到 rope_theta 就產出一顆亂碼模型
# ---------------------------------------------------------------------------
#
# 實測踩過：transformers 5.x 把 `rope_theta` 收進 `rope_parameters`、`torch_dtype`
# 改名 `dtype`，而 Ollama 的 GGUF 轉檔器讀的是 4.x 的鍵位。`ollama create` 完全
# 不報錯，產出的 GGUF 裡卻是 `qwen2.rope.freq_base = 0.0`（正確值 1000000.0），
# 模型對任何輸入都回一串「@@@@@@@」。
#
# 從外面看像是微調把模型訓壞了——但權重是好的，壞的是一個沒有人會去看的預設值。
# 所以 merge_stage_lora 把權重以外的檔案一律照抄基底，並在抄完之後檢查 rope_theta。


def _fake_base(tmp_path, **config_overrides):
    base = tmp_path / "base"
    base.mkdir()
    config = {"architectures": ["Qwen2ForCausalLM"], "rope_theta": 1_000_000.0,
              "torch_dtype": "bfloat16", "sliding_window": 32768}
    config.update(config_overrides)
    (base / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (base / "tokenizer_config.json").write_text('{"chat_template": "…"}', encoding="utf-8")
    return base


def test_merged_config_comes_from_the_base_not_from_transformers(tmp_path):
    """save_pretrained 寫的那份是新版鍵位，會被基底的原檔覆蓋掉。"""
    from scripts.merge_stage_lora import copy_base_side_files

    base = _fake_base(tmp_path)
    out = tmp_path / "merged"
    out.mkdir()
    # transformers 5 寫出來的樣子：rope_theta 不見了，搬進 rope_parameters。
    (out / "config.json").write_text(
        json.dumps({"dtype": "bfloat16", "rope_parameters": {"rope_theta": 1_000_000.0}}),
        encoding="utf-8",
    )

    copied = copy_base_side_files(str(base), out)

    config = json.loads((out / "config.json").read_text(encoding="utf-8"))
    assert config["rope_theta"] == 1_000_000.0, "Ollama 會把 rope.freq_base 寫成 0"
    assert config["sliding_window"] == 32768
    assert "config.json" in copied and "tokenizer_config.json" in copied
    # 基底沒有的檔案不該憑空生出來
    assert "special_tokens_map.json" not in copied


def test_a_base_config_without_rope_theta_stops_the_merge(tmp_path):
    """檢查要在合併時就炸掉，而不是等到模型輸出亂碼才有人發現。"""
    from scripts.merge_stage_lora import copy_base_side_files

    base = tmp_path / "base"
    base.mkdir()
    (base / "config.json").write_text(
        json.dumps({"dtype": "bfloat16", "rope_parameters": {"rope_theta": 1_000_000.0}}),
        encoding="utf-8",
    )
    out = tmp_path / "merged"
    out.mkdir()

    with pytest.raises(SystemExit, match="rope_theta"):
        copy_base_side_files(str(base), out)


# ---------------------------------------------------------------------------
# 19. 老師模型標籤：接觸建立的地板、單調性、測試集不得被重標
# ---------------------------------------------------------------------------


def test_contact_floor_only_bites_once_the_counterpart_has_spoken_enough():
    """前一兩則確實可能還在接觸建立；地板要等對話長到不可能還在打招呼才生效。"""
    from scripts.label_stage_teacher import (
        CONTACT_FLOOR_STAGE,
        CONTACT_MAX_THEM_MESSAGES,
        apply_contact_floor,
    )

    turns = [{"sender": "them", "text": ""} for _ in range(5)]
    result = apply_contact_floor(turns, ["contact"] * 5)

    kept = CONTACT_MAX_THEM_MESSAGES - 1
    assert result[:kept] == ["contact"] * kept
    assert set(result[kept:]) == {CONTACT_FLOOR_STAGE}


def test_contact_floor_counts_only_the_counterpart_messages():
    """使用者自己講幾句話不代表對方推進了階段（同 rule_floor 只掃 them 的理由）。"""
    from scripts.label_stage_teacher import apply_contact_floor

    turns = [
        {"sender": "them", "text": ""},
        {"sender": "me", "text": ""},
        {"sender": "me", "text": ""},
        {"sender": "me", "text": ""},
    ]
    assert apply_contact_floor(turns, ["contact"] * 4) == ["contact"] * 4


def test_contact_floor_never_lowers_a_stage_or_breaks_monotonicity():
    """地板只往上頂。頂完仍要是單調的，否則 App 眼中的風險會自己降下來。"""
    from scripts.label_stage_teacher import apply_contact_floor

    turns = [{"sender": "them", "text": ""} for _ in range(4)]
    weak = ["contact", "contact", "extraction", "extraction"]
    result = apply_contact_floor(turns, weak)

    for before, after in zip(weak, result):
        assert STAGE_INDEX[after] >= STAGE_INDEX[before]
    indices = [STAGE_INDEX[s] for s in result]
    assert indices == sorted(indices)


def test_contact_floor_leaves_unlabelled_prefixes_alone():
    """沒有任何一票的前綴要保持 None——猜一個階段比跳過那筆樣本更糟。"""
    from scripts.label_stage_teacher import apply_contact_floor

    turns = [{"sender": "them", "text": ""} for _ in range(4)]
    assert apply_contact_floor(turns, [None] * 4) == [None] * 4


def test_teacher_labels_may_never_reach_the_test_set(tmp_path, monkeypatch):
    """老師標過的對話拿去評測老師或它的學生都不再有意義，出現在測試集要直接炸掉。"""
    import scripts.build_stage_dataset as builder

    labelled = [
        {
            "id": "conv-manual-XYZ",
            "source": "cofacts-manual",
            "scam_type": "",
            "turn_stages": ["baiting"],
            "prefix_stages": ["baiting"],
            "stage": "baiting",
            "label_tier": "teacher",
        }
    ]
    monkeypatch.setattr(builder, "load_jsonl", lambda path: labelled)
    monkeypatch.setattr(builder, "load_verdicts", lambda path: {})
    monkeypatch.setattr(
        builder, "split_ids", lambda *a, **k: (set(), {"conv-manual-XYZ"})
    )
    monkeypatch.setattr(sys, "argv", ["build_stage_dataset", "--dry-run"])

    with pytest.raises(SystemExit, match="帶著老師標籤"):
        builder.main()


def test_merged_labels_keep_every_conversation(tmp_path):
    """成品必須是完整的一份：少掉合成樣本不會報錯，只會讓訓練集無聲縮水。"""
    from scripts.label_stage_teacher import merge_and_write

    labels = tmp_path / "labels.jsonl"
    labels.write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=False)
            for row in (
                {"id": "a", "stage": "contact", "label_tier": "weak"},
                {"id": "b", "stage": None, "label_tier": "weak"},
                {"id": "c", "stage": "baiting", "label_tier": "weak"},
            )
        ),
        encoding="utf-8",
    )
    out = tmp_path / "merged.jsonl"
    stats = merge_and_write(
        {"b": {"id": "b", "stage": "extraction", "label_tier": "teacher"}}, labels, out
    )

    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert stats == {"total": 3, "replaced": 1}
    assert [row["id"] for row in rows] == ["a", "b", "c"]
    assert rows[1]["stage"] == "extraction" and rows[1]["label_tier"] == "teacher"
    # 沒被重標的維持原樣，tier 不得被順手改掉
    assert {rows[0]["label_tier"], rows[2]["label_tier"]} == {"weak"}


# ---------------------------------------------------------------------------
# 20. 答案審核頁：一段對話只能出現一次
# ---------------------------------------------------------------------------


def _stage_row(conversation_id: str, turns: int, stage: str, tier: str = "gold") -> dict:
    return {
        "id": f"{conversation_id}#{turns}",
        "conversation_id": conversation_id,
        "source": "cofacts-manual",
        "scam_type": "未分類",
        "turns": [{"sender": "them", "text": f"第 {i} 則"} for i in range(1, turns + 1)],
        "stage": stage,
        "label_tier": tier,
    }


def test_review_page_shows_each_conversation_once():
    """審核頁一段對話只出一列，而且是**最長**的那個前綴。

    這裡踩過一次：原本是篩 `label_tier == "gold"`，因為當時只有完整長度那一列
    是 gold。2026-08-27 重標之後每一列都是 gold，那個條件一筆都篩不掉，
    250 段的審核頁變成 2,179 列——同一段對話被同一個人審八遍，
    每人工時從 2 小時變成 13 小時，而且八次的答案不會一致。
    這種壞法不會拋例外，只會讓頁面安靜地變成另一件事。
    """
    from scripts.export_answer_review import stage_items

    records = [
        _stage_row("conv-a", 2, "contact"),
        _stage_row("conv-a", 5, "baiting"),
        _stage_row("conv-a", 9, "extraction"),
        _stage_row("conv-b", 3, "grooming"),
        _stage_row("conv-b", 6, "baiting"),
    ]
    items = stage_items(records, {}, blind_pct=0)

    assert [item["id"] for item in items] == ["conv-a", "conv-b"]
    # 取的是最長前綴，所以答案是整段走到的階段，不是中途某一段的
    assert [item["orig"]["stage"] for item in items] == ["索取財物", "鋪陳誘餌"]
    assert [len(item["turns"]) for item in items] == [9, 6]


def test_review_page_drops_notes_that_belong_to_another_answer(tmp_path):
    """理由對不上現在的答案就不給看——那是重標之前那顆模型寫的。

    留著的話，覆核的人會看到「只到登記，未要錢」擺在一個寫著「索取財物」的
    欄位旁邊，然後照那句話把對的答案改回去：一個會反向汙染答案的預填。
    """
    from scripts.export_answer_review import load_verdict_notes

    path = tmp_path / "verdicts.csv"
    path.write_text(
        "id,verdict_stage,note\n"
        "keep,索取財物,已經開口要匯款\n"
        "stale,鋪陳誘餌,只到登記，未要錢\n"
        "blank,索取財物,\n",
        encoding="utf-8",
    )
    notes = load_verdict_notes(
        path, {"keep": "索取財物", "stale": "索取財物", "blank": "索取財物"}
    )

    assert notes == {"keep": "已經開口要匯款"}


# ---------------------------------------------------------------------------
# 21. 階段轉折點：答案檔的解析度與答案檔過期的守門
# ---------------------------------------------------------------------------


def test_transitions_pin_every_prefix_two_fields_cannot():
    """轉折點釘得住每一個前綴；兩格只釘得住索取那條線與最後一列。

    這就是改版的理由：測試集 2,179 列裡有 1,074 列（49.3%）落在索取之前，
    弱標籤在那一段大量留白（76% 的格子是空的），兩格的夾法補不回來，
    expand() 會把那些前綴整批跳過——評測樣本無聲少掉一半。
    """
    from scripts.build_stage_dataset import apply_verdict, parse_transitions

    weak = [None] * 10
    with_transitions = apply_verdict(
        weak,
        {
            "stage": "closing",
            "extraction_turn": 9,
            "transitions": parse_transitions("1:1,4:3,9:4,10:5"),
        },
    )
    two_fields = apply_verdict(
        weak, {"stage": "closing", "extraction_turn": 9, "transitions": []}
    )

    assert with_transitions == [
        "contact", "contact", "contact",
        "baiting", "baiting", "baiting", "baiting", "baiting",
        "extraction", "closing",
    ]
    # 兩格路徑：索取之前那 8 格沒有人給過答案，只能留白
    assert two_fields[:8] == [None] * 8
    assert two_fields[8:] == ["extraction", "closing"]


def test_transitions_reject_the_shapes_that_fail_silently():
    """壞掉的轉折點一律當作沒填，不要半套用。

    半套用比整串丟掉更糟：`9:4,1:1` 若照順序吃，第 1 輪會覆蓋掉第 9 輪的答案，
    產出一個看起來正常、實際上錯得離譜的序列。
    """
    from scripts.build_stage_dataset import parse_transitions

    assert parse_transitions("1:1,4:3,9:4") == [(1, "contact"), (4, "baiting"), (9, "extraction")]
    assert parse_transitions("4:3,9:4") == []      # 第一個轉折不在第 1 輪
    assert parse_transitions("1:1,9:4,4:3") == []  # 輪次沒遞增
    assert parse_transitions("1:3,4:1") == []      # 階段沒遞增（詐騙腳本不會倒退）
    assert parse_transitions("1:9") == []          # 階段編號超出 1-5
    assert parse_transitions("一:1") == []


def test_review_csv_keeps_the_columns_the_pipeline_reads():
    """匯出的欄名是契約：build_stage_dataset 與 eval_stage 都照欄名讀。

    加 verdict_transitions 的同時，verdict_stage／verdict_extraction_turn 必須留著，
    否則舊的讀取端會安靜地讀到空值——而空的 verdict_stage 會被當成「沒審過」跳過。
    """
    from scripts.export_answer_review import STAGE_COLUMNS

    for column in ("id", "狀態", "verdict_stage", "verdict_extraction_turn",
                   "verdict_transitions", "note", "對話"):
        assert column in STAGE_COLUMNS, column


def test_import_and_build_agree_on_which_answer_file():
    """審核結果寫進 A、重建時讀 B 的話，人審完全白做，而且不會有人發現。"""
    from scripts.build_stage_dataset import VERDICTS
    from scripts.import_answer_review import STAGE_VERDICT_PATH

    assert STAGE_VERDICT_PATH == VERDICTS


def test_default_answer_file_is_not_the_pre_relabel_one():
    """預設不得指回重標之前那份。

    實測拿舊檔套在現在的標籤上，251 段重疊的對話裡有 105 段、3,542 個前綴裡
    改掉 636 個（18.0%），其中 557 個是把階段往前推——低估，正好是這條線
    最不該錯的方向，而且是安靜發生的。
    """
    from scripts.build_stage_dataset import VERDICTS, VERDICTS_LEGACY

    assert VERDICTS != VERDICTS_LEGACY
    assert VERDICTS.name == "stage_verdicts_claude.csv"
