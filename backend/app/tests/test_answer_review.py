"""測試集答案人工審核這條線的靜默失效。

這裡釘的都是「跑起來不會報錯，但人工的幾十小時會白做」的那種問題：
分份分歪了四個人的成績就不能比、階段名稱用錯語言按鈕永遠不會亮、
狀態欄的四個值任何一個對不上匯入端就整批靜靜地不套用。
"""

import csv
import json

from app.services.stage_service import STAGE_LABELS
from scripts import export_answer_review as export
from scripts import import_answer_review as importer


# ---------------------------------------------------------------------------
# 19. 分份：四個人拿到的必須是同一種東西
# ---------------------------------------------------------------------------


def _items(spec: dict[str, int]) -> list[dict]:
    """spec 是「層別 → 幾筆」。"""
    items = []
    for name, count in spec.items():
        for index in range(count):
            items.append({"id": f"{name}-{index}", "src": name, "blind": False})
    return items


def test_every_shard_gets_the_same_mix():
    items = _items({"a": 1000, "b": 400, "c": 4})
    buckets = export.split_shards(items, lambda item: item["src"], 4)

    assert [len(bucket) for bucket in buckets] == [351, 351, 351, 351]
    for bucket in buckets:
        counts = {name: sum(1 for item in bucket if item["src"] == name) for name in "abc"}
        assert counts == {"a": 250, "b": 100, "c": 1}


def test_a_rare_stratum_is_not_swallowed_by_the_limit():
    """--limit 是在每一層依比例砍，不是砍整列——否則只有 4 筆的稀有類會整個消失。"""
    items = _items({"a": 1000, "b": 400, "c": 4})
    buckets = export.split_shards(items, lambda item: item["src"], 4, limit=200)

    kept = [item for bucket in buckets for item in bucket]
    assert 190 <= len(kept) <= 210
    assert sum(1 for item in kept if item["src"] == "c") >= 1


def test_dealing_after_interleaving_would_have_skewed_the_shards():
    """這是真的發生過的錯：交錯成一列再每 4 個發一張，等於在取樣同一個相位。

    留著這個測試是為了記住為什麼 split_shards() 要在層內發牌，
    而不是圖方便寫成 deal(interleave(...))。
    """
    # 用 data/test.jsonl 真正的層別大小。隨便編的數字重現不出來——
    # 交錯序列的週期剛好與份數互質時就沒事，是這五個大小的組合才踩得到。
    real = {"0|community+rule": 1000, "1|knn": 431, "1|manual": 221,
            "1|rule": 60, "1|rule+knn": 288}
    items = _items(real)
    naive = export.interleave(
        [[item for item in items if item["src"] == name] for name in sorted(real)]
    )
    skewed = [naive[index::4] for index in range(4)]
    spread = [sum(1 for item in bucket if item["src"] == "0|community+rule") for bucket in skewed]
    assert spread == [319, 177, 336, 168]  # 一份 319 筆、另一份 177 筆

    fair = export.split_shards(items, lambda item: item["src"], 4)
    even = [sum(1 for item in bucket if item["src"] == "0|community+rule") for bucket in fair]
    assert even == [250, 250, 250, 250]


def test_the_same_item_never_lands_in_two_shards():
    items = _items({"a": 97, "b": 31})
    buckets = export.split_shards(items, lambda item: item["src"], 4)
    ids = [item["id"] for bucket in buckets for item in bucket]
    assert len(ids) == len(set(ids)) == 128


def test_blind_picks_do_not_move_when_the_test_set_changes():
    """盲審用雜湊挑，加減幾筆不會讓已經審過的那些突然變成盲審。"""
    before = {item_id for item_id in "abcdefghij" if export.is_blind(item_id, 30)}
    after = {item_id for item_id in "abcdefghijklmno" if export.is_blind(item_id, 30)}
    assert before == {item_id for item_id in after if item_id in "abcdefghij"}
    assert export.is_blind("anything", 0) is False


# ---------------------------------------------------------------------------
# 20. 頁面：階段名稱與答案欄位的語言必須對得上
# ---------------------------------------------------------------------------


def _stage_record(conversation_id: str, stage: str, turns: int) -> dict:
    return {
        "id": f"{conversation_id}#{turns}",
        "conversation_id": conversation_id,
        "source": "cofacts-manual",
        "scam_type": "未分類",
        "turns": [{"sender": "them", "text": f"第 {i} 句"} for i in range(1, turns + 1)],
        "stage": stage,
        "label_tier": "gold" if turns == 9 else "derived",
    }


def test_the_page_speaks_chinese_stage_names_not_slugs():
    """stage_test.jsonl 存 slug，但按鈕、verdict_stage、build_stage_dataset 都吃中文名。

    漏掉這一步不會報錯：頁面照樣打得開，只是五個按鈕永遠不會亮，
    而且每一段都會被算成「已改判」——匯入時看到的統計會是「250 段全部改過」。
    """
    records = [_stage_record("c1", "baiting", 9)]
    items = export.stage_items(records, {}, blind_pct=0)

    assert items[0]["orig"]["stage"] == "鋪陳誘餌"
    assert items[0]["orig"]["stage"] in export.STAGE_LABEL_LIST
    assert set(export.STAGE_LABEL_LIST) == set(STAGE_LABELS.values())


def test_only_the_full_length_prefix_is_handed_to_a_human():
    """一段對話只審一次。同一段的八個前綴各審一次，只會得到八個不一致的答案。"""
    records = [
        _stage_record("c1", "contact", 3),
        _stage_record("c1", "baiting", 6),
        _stage_record("c1", "extraction", 9),
    ]
    items = export.stage_items(records, {}, blind_pct=0)
    assert [item["id"] for item in items] == ["c1"]
    assert len(items[0]["turns"]) == 9


def test_the_transitions_are_recovered_from_the_prefixes():
    """階段轉折點＝前綴的階段換掉的那個長度；第一個轉折一律掛在第 1 輪。

    兩格（最終階段、索取起始輪）仍然一起推出來給既有的讀取端用，但它們是
    轉折點的投影，不是另一份答案——對不上就代表這裡推錯了。
    """
    records = [
        _stage_record("c1", "contact", 3),
        _stage_record("c1", "baiting", 5),
        _stage_record("c1", "extraction", 6),
        _stage_record("c1", "closing", 9),
    ]
    items = export.stage_items(records, {}, blind_pct=0)
    export.stage_transitions(records, items)
    # 最短那個前綴的階段掛在第 1 輪，不是掛在它自己的長度 3
    assert items[0]["orig"]["tr"] == [[1, 1], [5, 3], [6, 4], [9, 5]]
    assert items[0]["orig"]["turn"] == 6
    assert items[0]["orig"]["stage"] == "收尾拖延"

    never = [_stage_record("c2", "grooming", 9)]
    items = export.stage_items(never, {}, blind_pct=0)
    export.stage_transitions(never, items)
    assert items[0]["orig"]["tr"] == [[1, 2]]
    assert items[0]["orig"]["turn"] == 0
    assert items[0]["orig"]["stage"] == "培養信任"


def test_the_page_ships_no_machine_answer_outside_orig():
    """盲審靠 JS 不畫 orig 來遮。至少要確定答案沒有第二個出口（例如 meta 欄）。"""
    records = [_stage_record("c1", "extraction", 9)]
    items = export.stage_items(records, {}, blind_pct=100)
    assert items[0]["blind"] is True
    assert "索取財物" not in items[0]["meta"]

    page = export.render(items, kind="stage", title="t", key="k")
    assert page.count("<title>") == 1
    assert "__DATA__" not in page and "__KIND__" not in page  # 佔位符全部換掉了


def test_the_scam_page_offers_exactly_the_textbook_types():
    page = export.render(
        export.scam_items([{"id": "x", "text": "嗨", "is_scam": 0, "scam_type": "非詐騙"}], 0),
        kind="scam",
        title="t",
        key="k",
    )
    types = json.loads(page.split("const TYPES = ")[1].split(";\n")[0])
    assert len(types) == 23  # 22 類教科書 + 非詐騙
    assert types[-1] == export.NOT_SCAM_TYPE == "非詐騙"


# ---------------------------------------------------------------------------
# 21. 匯入：狀態欄的四個值，兩邊必須是同一組字
# ---------------------------------------------------------------------------


def test_the_two_scripts_agree_on_the_four_status_words():
    """頁面寫進 CSV 的狀態字串，匯入端得認得。

    這兩個字串各自寫在兩個檔案裡，對不上的話匯入會**安靜地**把每一列都當成
    未審——不報錯、不套用，人白做一整天。
    """
    page = export.PAGE
    for word in (importer.REVIEWED, importer.DROPPED, importer.HELD, importer.TODO):
        assert f'"{word}"' in page, f"頁面裡沒有「{word}」這個狀態"


def _sheet(columns: list[str], rows: list[dict], tmp_path, name: str):
    path = tmp_path / name
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_a_shard_csv_is_readable_by_build_stage_dataset(tmp_path):
    """階段那份的三個關鍵欄名與 data/stage_verdicts.csv 逐字相同，所以連匯入都不必經過。

    真的餵給 load_verdicts() 來確認，而不是比對欄名字串——欄名對了但值的語言
    不對（英文 slug）一樣讀不出東西，那才是實際發生過的失敗。
    """
    from scripts.build_stage_dataset import load_verdicts

    path = _sheet(
        export.STAGE_COLUMNS,
        [
            {"id": "c1", "狀態": "審過", "verdict_stage": "索取財物",
             "verdict_extraction_turn": "4", "verdict_transitions": "1:1,4:4"},
            {"id": "c2", "狀態": "未審", "verdict_stage": "", "verdict_extraction_turn": ""},
        ],
        tmp_path,
        "stage_review_1of4.csv",
    )
    verdicts = load_verdicts(path)
    assert verdicts == {
        "c1": {
            "stage": "extraction",
            "extraction_turn": 4,
            "transitions": [(1, "contact"), (4, "extraction")],
        }
    }


def test_sheets_are_recognised_by_their_header_not_their_filename(tmp_path):
    """組員會把檔案改成自己的名字，所以不能靠檔名分辨是哪一份。"""
    _sheet(
        export.SCAM_COLUMNS,
        [{"編號": "a1", "狀態": "審過", "是否詐騙": "1", "詐騙類型": "假投資詐騙"}],
        tmp_path,
        "隨便取的名字.csv",
    )
    _sheet(
        export.STAGE_COLUMNS,
        [{"id": "c1", "狀態": "審過", "verdict_stage": "索取財物"}],
        tmp_path,
        "另一個名字.csv",
    )
    scam, stage, summary = importer.read_sheets(tmp_path)
    assert set(scam) == {"a1"} and set(stage) == {"c1"}
    assert len(summary) == 2


def test_a_broken_row_does_not_take_the_other_three_shards_down(tmp_path):
    rows = [
        {"編號": "ok", "狀態": "審過", "是否詐騙": "1", "詐騙類型": "假投資詐騙"},
        {"編號": "bad-type", "狀態": "審過", "是否詐騙": "1", "詐騙類型": "冒充客服"},
        {"編號": "bad-pair", "狀態": "審過", "是否詐騙": "1", "詐騙類型": "非詐騙"},
        {"編號": "untouched", "狀態": "未審", "是否詐騙": "", "詐騙類型": ""},
    ]
    _sheet(export.SCAM_COLUMNS, rows, tmp_path, "s.csv")
    scam, _, _ = importer.read_sheets(tmp_path)
    good, problems = importer.check_scam(scam)
    assert set(good) == {"ok", "untouched"}
    assert len(problems) == 2


def test_held_rows_stay_in_the_set_but_stop_counting(tmp_path):
    """存疑不是刪除：留著才知道測試集裡有多少是連人都判不出來的。"""
    path = tmp_path / "test.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(record, ensure_ascii=False)
            for record in (
                {"id": "keep", "text": "a", "is_scam": 0, "scam_type": "非詐騙", "label_tier": "clean"},
                {"id": "hold", "text": "b", "is_scam": 1, "scam_type": "假投資詐騙", "label_tier": "tier1"},
                {"id": "drop", "text": "c", "is_scam": 1, "scam_type": "假求職詐騙", "label_tier": "tier1"},
            )
        )
        + "\n",
        encoding="utf-8",
    )
    rows = {
        "hold": {"編號": "hold", "狀態": "存疑"},
        "drop": {"編號": "drop", "狀態": "剔除"},
    }
    stats = importer.apply_scam(rows, path, tmp_path / "excluded.jsonl", write=True)

    kept = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [record["id"] for record in kept] == ["keep", "hold"]
    assert kept[1]["label_tier"] == "unverified"  # eval 的 --exclude-unverified 認這個
    assert stats == {**stats, "剔除": 1, "存疑": 1, "留下": 2}
    assert json.loads((tmp_path / "excluded.jsonl").read_text(encoding="utf-8"))["id"] == "drop"


def test_a_reviewed_row_stops_claiming_to_be_machine_labelled(tmp_path):
    path = tmp_path / "test.jsonl"
    path.write_text(
        json.dumps(
            {"id": "a1", "text": "x", "is_scam": 0, "scam_type": "非詐騙",
             "label_source": "community+rule", "scam_type_confidence": "medium"},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    rows = {"a1": {"編號": "a1", "狀態": "審過", "是否詐騙": "1", "詐騙類型": "假投資詐騙"}}
    stats = importer.apply_scam(rows, path, tmp_path / "ex.jsonl", write=True)

    record = json.loads(path.read_text(encoding="utf-8").strip())
    assert record["is_scam"] == 1 and record["scam_type"] == "假投資詐騙"
    assert record["label_source"] == "human"
    assert stats["改判"] == 1 and stats["翻是否"] == 1
    assert (path.with_name("test.jsonl.review.bak")).exists()


def test_unreviewed_rows_change_nothing(tmp_path):
    """未審是絕大多數（沒人一次做得完 500 筆），它必須是完全的 no-op。"""
    original = {"id": "a1", "text": "x", "is_scam": 0, "scam_type": "非詐騙",
                "label_source": "knn", "label_tier": "clean"}
    path = tmp_path / "test.jsonl"
    path.write_text(json.dumps(original, ensure_ascii=False) + "\n", encoding="utf-8")

    rows = {"a1": {"編號": "a1", "狀態": "未審", "是否詐騙": "1", "詐騙類型": "假投資詐騙"}}
    importer.apply_scam(rows, path, tmp_path / "ex.jsonl", write=True)
    assert json.loads(path.read_text(encoding="utf-8").strip()) == original


def test_the_stage_import_keeps_every_column_it_did_not_touch(tmp_path):
    columns = ["priority", "id", "source", "turns", "conversation",
               "verdict_stage", "verdict_extraction_turn", "note"]
    path = _sheet(
        columns,
        [
            {"priority": "P3", "id": "c1", "source": "cofacts-manual", "turns": "9",
             "conversation": "1.[對方]嗨", "verdict_stage": "培養信任",
             "verdict_extraction_turn": "", "note": "模型寫的理由"},
            {"priority": "P1", "id": "c2", "source": "cofacts-manual", "turns": "4",
             "conversation": "1.[我]嗨", "verdict_stage": "接觸建立",
             "verdict_extraction_turn": "", "note": ""},
        ],
        tmp_path,
        "stage_verdicts.csv",
    )
    rows = {
        "c1": {"id": "c1", "狀態": "審過", "verdict_stage": "索取財物",
               "verdict_extraction_turn": "4", "note": "第 4 輪要銀行帳號"},
        "c2": {"id": "c2", "狀態": "剔除"},
    }
    stats = importer.apply_stage(rows, path, tmp_path / "excluded.csv", write=True)

    with path.open(encoding="utf-8-sig", newline="") as handle:
        kept = list(csv.DictReader(handle))
    assert len(kept) == 1
    assert kept[0]["priority"] == "P3" and kept[0]["conversation"] == "1.[對方]嗨"
    assert kept[0]["verdict_stage"] == "索取財物"
    assert kept[0]["verdict_extraction_turn"] == "4"
    assert kept[0]["note"] == "第 4 輪要銀行帳號"
    assert stats["改判"] == 1 and stats["剔除"] == 1

    with (tmp_path / "excluded.csv").open(encoding="utf-8-sig", newline="") as handle:
        assert [row["id"] for row in csv.DictReader(handle)] == ["c2"]


def test_the_blind_agreement_rate_only_counts_blind_and_reviewed_rows():
    rows = {
        "a": {"盲審": "1", "狀態": "審過", "verdict_stage": "索取財物", "機器原判": "索取財物"},
        "b": {"盲審": "1", "狀態": "審過", "verdict_stage": "鋪陳誘餌", "機器原判": "索取財物"},
        "c": {"盲審": "1", "狀態": "未審", "verdict_stage": "", "機器原判": "索取財物"},
        "d": {"盲審": "", "狀態": "審過", "verdict_stage": "索取財物", "機器原判": "索取財物"},
    }
    assert importer.blind_agreement(rows, answer="verdict_stage", machine="機器原判") == (1, 2)
