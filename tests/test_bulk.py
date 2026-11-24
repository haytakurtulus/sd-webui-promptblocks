import copy
import random

from pb_core import bulk, parser, storage


def _blocks():
    return {
        "saber": {"category": "PChar", "text": "1girl, saber, %PPose",
                  "subs": [{"name": "outfit", "text": "armor, %PChar, %PCharLonger", "mode": "random"}],
                  "lora": "<lora:%PChar:1>"},
        "rin": {"category": "PChar", "text": "rin", "active": False, "weight": 2},
        "run": {"category": "PPose", "text": "running, %PChar"},
        "sit": {"category": "PPose", "text": "sitting, ~saber"},
        "long": {"category": "PCharLonger", "text": "x, %PCharLonger, %PChar_x"},
    }


# --- rename_category ---

def test_rename_moves_blocks_and_rewrites_refs_incl_sub_texts():
    blocks = _blocks()
    new, moved, rewritten = bulk.rename_category(blocks, "PChar", "Hero")
    assert moved == ["rin", "saber"]
    assert new["saber"]["category"] == "Hero" and new["rin"]["category"] == "Hero"
    assert new["run"]["text"] == "running, %Hero"
    assert new["saber"]["subs"][0]["text"] == "armor, %Hero, %PCharLonger"
    assert rewritten == ["run", "saber"]
    # Other fields kept.
    assert new["rin"]["active"] is False and new["rin"]["weight"] == 2
    assert new["saber"]["subs"][0]["mode"] == "random"


def test_rename_leaves_other_categories_and_longer_names():
    new, _, _ = bulk.rename_category(_blocks(), "PChar", "Hero")
    assert new["run"]["category"] == "PPose" and new["sit"]["category"] == "PPose"
    assert new["long"] == _blocks()["long"]  # %PCharLonger / %PChar_x are other categories
    assert new["sit"]["text"] == "sitting, ~saber"


def test_rename_leaves_lora_field_literal():
    new, _, _ = bulk.rename_category(_blocks(), "PChar", "Hero")
    assert new["saber"]["lora"] == "<lora:%PChar:1>"


def test_rename_does_not_mutate_input():
    blocks = _blocks()
    before = copy.deepcopy(blocks)
    bulk.rename_category(blocks, "PChar", "Hero")
    assert blocks == before


def test_rename_expands_like_before():
    blocks = {
        "saber": {"category": "PChar", "text": "saber",
                  "subs": [{"name": "o", "text": "%PPose", "mode": "random"}]},
        "rin": {"category": "PChar", "text": "rin", "weight": 3},
        "run": {"category": "PPose", "text": "running"},
        "sit": {"category": "PPose", "text": "sitting"},
        "scene": {"category": "Scene", "text": "%PChar, %PPose"},
    }
    new, _, _ = bulk.rename_category(blocks, "PChar", "Hero")
    for seed in range(50):
        assert (parser.expand("%PChar, ~scene", blocks, random.Random(seed))
                == parser.expand("%Hero, ~scene", new, random.Random(seed)))


def test_rename_merge_case():
    blocks = _blocks()
    new, moved, rewritten = bulk.rename_category(blocks, "PChar", "PPose")
    assert moved == ["rin", "saber"]
    assert sorted(n for n, b in new.items() if b["category"] == "PPose") == ["rin", "run", "saber", "sit"]
    assert new["run"]["text"] == "running, %PPose"
    assert new["saber"]["subs"][0]["text"] == "armor, %PPose, %PCharLonger"
    assert "run" in rewritten and "saber" in rewritten


def test_rename_same_or_missing_old_is_no_change():
    blocks = _blocks()
    for old, new_name in (("PChar", "PChar"), ("Nope", "Hero")):
        new, moved, rewritten = bulk.rename_category(blocks, old, new_name)
        assert new == blocks and moved == [] and rewritten == []
        assert new is not blocks


def test_rename_old_json_shape_is_kept():
    blocks = {"a": {"category": "C", "text": "x"}, "b": {"category": "D", "text": "%C"}}
    new, _, _ = bulk.rename_category(blocks, "C", "E")
    assert new == {"a": {"category": "E", "text": "x"}, "b": {"category": "D", "text": "%E"}}


def test_rename_roundtrip_through_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_FILE", str(tmp_path / "blocks.json"))
    monkeypatch.setattr(storage, "THUMB_DIR", str(tmp_path / "thumbs"))
    new, _, _ = bulk.rename_category(_blocks(), "PChar", "Hero")
    storage.save_blocks(new)
    assert storage.load_blocks() == new


# --- check_category_rename ---

def test_check_new_name():
    r = bulk.check_category_rename(_blocks(), " PChar ", " Hero ")
    assert r["error"] is None and r["merge"] is False and r["warning"] is None
    assert (r["old"], r["new"], r["moved"], r["existing"]) == ("PChar", "Hero", 2, 0)


def test_check_merge_counts_and_warning():
    blocks = _blocks()
    blocks["walk"] = {"category": "PPose", "text": "walking"}
    r = bulk.check_category_rename(blocks, "PChar", "PPose")
    assert r["error"] is None and r["merge"] is True
    assert (r["moved"], r["existing"]) == (2, 3)
    assert "`PChar` (2 blocks) will be merged into `PPose` (3 blocks)" in r["warning"]
    assert "again to confirm" in r["warning"]


def test_check_singular_wording():
    blocks = {"a": {"category": "A", "text": "x"}, "b": {"category": "B", "text": "y"}}
    r = bulk.check_category_rename(blocks, "A", "B")
    assert "`A` (1 block) will be merged into `B` (1 block)" in r["warning"]


def test_check_errors():
    blocks = _blocks()
    assert bulk.check_category_rename(blocks, None, "X")["error"]
    assert bulk.check_category_rename(blocks, "", "X")["error"]
    assert "No blocks" in bulk.check_category_rename(blocks, "Nope", "X")["error"]
    for bad in ("", "1abc", "a b", "a.b", "%X", None):
        r = bulk.check_category_rename(blocks, "PChar", bad)
        assert r["error"] and "Invalid" in r["error"], bad
    assert bulk.check_category_rename(blocks, "PChar", "PChar")["error"]


# --- set_active ---

def test_set_active_disable_only_given_names():
    blocks = _blocks()
    new, changed = bulk.set_active(blocks, ["saber", "run"], False)
    assert changed == ["saber", "run"]
    assert new["saber"]["active"] is False and new["run"]["active"] is False
    for n in ("rin", "sit", "long"):
        assert new[n] == blocks[n]
    assert "active" not in new["sit"]


def test_set_active_enable_removes_key():
    blocks = _blocks()
    new, changed = bulk.set_active(blocks, ["rin", "saber"], True)
    assert changed == ["rin"]
    assert "active" not in new["rin"] and new["rin"]["weight"] == 2
    assert new["saber"] == blocks["saber"]


def test_set_active_skips_missing_and_already_in_state():
    blocks = _blocks()
    new, changed = bulk.set_active(blocks, ["rin", "ghost", "rin"], False)
    assert changed == [] and new == blocks
    new, changed = bulk.set_active(blocks, ["saber", "saber"], False)
    assert changed == ["saber"]


def test_set_active_broken_value_counts_as_active():
    blocks = {"a": {"category": "C", "text": "x", "active": "no"}}
    new, changed = bulk.set_active(blocks, ["a"], True)
    assert changed == []
    new, changed = bulk.set_active(blocks, ["a"], False)
    assert changed == ["a"] and new["a"]["active"] is False


def test_set_active_does_not_mutate_input():
    blocks = _blocks()
    before = copy.deepcopy(blocks)
    bulk.set_active(blocks, list(blocks), False)
    bulk.set_active(blocks, list(blocks), True)
    assert blocks == before


def test_set_active_empty_or_none_names():
    blocks = _blocks()
    assert bulk.set_active(blocks, [], False) == (blocks, [])
    assert bulk.set_active(blocks, None, True) == (blocks, [])


# --- active_status ---

def test_active_status_messages():
    assert bulk.active_status(False, 4, 2) == "Disabled 4 blocks (2 were already inactive)."
    assert bulk.active_status(True, 1, 1) == "Enabled 1 block (1 was already active)."
    assert bulk.active_status(True, 3, 0) == "Enabled 3 blocks."
    assert bulk.active_status(False, 0, 5) == "Nothing to change."
