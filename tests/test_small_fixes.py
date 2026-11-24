"""Design notes section 21 (small fixes) + robustness against broken hand-edited blocks.json entries."""
import json
import random

import pytest

from pb_core import browser, bulk, parser, storage, suggest, weights


# ---- 1. "1 block" / "N blocks" wording ----

def test_category_hint_singular():
    blocks = {"saber": {"category": "PCharacter", "text": "x"}}
    assert suggest.category_hint("PCharacter", blocks) == "Existing category (1 block)."


def test_category_hint_plural():
    blocks = {"a": {"category": "C", "text": "x"}, "b": {"category": "C", "text": "y"}}
    assert suggest.category_hint("C", blocks) == "Existing category (2 blocks)."


def test_slot_hint_singular_and_plural():
    one = {"a": {"category": "C", "text": "x", "slot": "outfit"}}
    two = {**one, "b": {"category": "C", "text": "y", "slot": "outfit"}}
    assert suggest.slot_hint("outfit", one) == "Existing slot (1 use)."
    assert suggest.slot_hint("outfit", two) == "Existing slot (2 uses)."


# ---- 2. Placeholder tiles removed on Delete / Rename ----

def _touch(folder, *names):
    for n in names:
        (folder / n).write_bytes(b"x")


def test_remove_placeholders_exact_names_only(tmp_path):
    cache = tmp_path / "tile_cache"
    cache.mkdir()
    _touch(cache, "sa_128.png", "sa_64.png", "saber_128.png", "sa_1_128.png", "xsa_128.png",
           "sa_128.png.tmp", "sa_big.png", "sa_128.webp", "sa.png")
    removed = browser.remove_placeholders("sa", str(cache))
    assert removed == ["sa_128.png", "sa_64.png"]
    left = sorted(p.name for p in cache.iterdir())
    assert left == ["sa.png", "sa_128.png.tmp", "sa_128.webp", "sa_1_128.png", "sa_big.png",
                    "saber_128.png", "xsa_128.png"]


def test_remove_placeholders_never_outside_folder(tmp_path):
    cache = tmp_path / "tile_cache"
    cache.mkdir()
    outside = tmp_path / "saber_128.png"
    outside.write_bytes(b"x")
    sub = cache / "nested"
    sub.mkdir()
    _touch(sub, "saber_128.png")
    assert browser.remove_placeholders("saber", str(cache)) == []
    assert outside.exists() and (sub / "saber_128.png").exists()
    # A name that tries to reach outside is only ever compared to file names inside the folder.
    assert browser.remove_placeholders("../saber", str(cache)) == []
    assert outside.exists()


def test_remove_placeholders_missing_folder(tmp_path):
    assert browser.remove_placeholders("saber", str(tmp_path / "nope")) == []


def test_remove_placeholders_drops_memory_cache(tmp_path):
    pytest.importorskip("PIL.Image")
    cache = tmp_path / "tile_cache"
    path = browser.placeholder_file("saber", str(cache))
    browser.placeholder_file("sa", str(cache))
    assert ("saber", browser.TILE_SIZE) in browser._placeholders
    assert browser.remove_placeholders("saber", str(cache)) == [f"saber_{browser.TILE_SIZE}.png"]
    assert ("saber", browser.TILE_SIZE) not in browser._placeholders
    assert ("sa", browser.TILE_SIZE) in browser._placeholders
    assert not (cache / f"saber_{browser.TILE_SIZE}.png").exists()
    assert (cache / f"sa_{browser.TILE_SIZE}.png").exists()
    # Regenerated on demand afterwards.
    assert browser.placeholder_file("saber", str(cache)) == path
    browser.remove_placeholders("sa", str(cache))
    browser.remove_placeholders("saber", str(cache))


def test_tile_cache_dir_follows_thumb_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "THUMB_DIR", str(tmp_path / "data" / "thumbs"))
    assert storage.tile_cache_dir() == str(tmp_path / "data" / "tile_cache")


# ---- 4. Non-dict block entries ----

BROKEN = {
    "saber": {"category": "PCharacter", "text": "1girl, saber"},
    "rin": {"category": "PCharacter", "text": "1girl, rin", "active": False},
    "junk": "not a block",
    "nums": [1, 2, 3],
    "nothing": None,
    "scene": {"category": "PPose", "text": "running, %PCharacter, ~junk"},
}


def test_category_pool_skips_non_dict():
    assert weights.category_pool(BROKEN, "PCharacter") == ["saber"]
    assert weights.chances(BROKEN, "PCharacter") == {"saber": 1.0}


def test_expand_category_with_broken_entries():
    for seed in range(5):
        out = parser.expand("%PCharacter", BROKEN, random.Random(seed))
        assert out == "1girl, saber"


def test_expand_non_dict_block_left_untouched():
    out = parser.expand("~scene, ~junk.x, ~nums*s", BROKEN, random.Random(0))
    assert out == "running, 1girl, saber, ~junk, ~junk.x, ~nums*s"


def test_expand_dict_block_without_text():
    blocks = {"a": {"category": "C"}, "b": {"category": "C", "text": 5}}
    assert parser.expand("x ~a y", blocks, random.Random(0)) == "x  y"
    assert parser.expand("~b", blocks, random.Random(0)) == ""


def test_find_all_inactive_skips_non_dict():
    blocks = {"rin": {"category": "C", "text": "r", "active": False}, "junk": "C"}
    assert parser.find_all_inactive("%C %Other", blocks) == ["C"]
    unknown, inactive = parser.preview_warnings("%C ~junk", blocks)
    assert inactive == ["C"]
    assert unknown == ["~junk"]


def test_suggest_counts_skip_non_dict():
    assert suggest.category_counts(BROKEN) == {"PCharacter": 2, "PPose": 1}
    assert suggest.category_hint("PCharacter", BROKEN) == "Existing category (2 blocks)."
    assert suggest.slot_counts(BROKEN) == {}
    assert suggest.users_of(BROKEN, parser.BLOCK_SYMBOL, "junk") == ["scene"]
    assert suggest.delete_warnings(BROKEN, "junk") == ["`~junk` is used by: scene"]


def test_browser_with_broken_entries(tmp_path):
    assert browser.filter_names(BROKEN, "", "PCharacter") == ["rin", "saber"]
    assert browser.filter_names(BROKEN, "n", None) == ["nothing", "nums", "junk", "rin", "scene"]
    assert browser.category_filter_choices(BROKEN) == [
        ("(all categories) (2/3 active)", browser.ALL_CATEGORIES), ("PCharacter (1/2 active)", "PCharacter"),
        ("PPose (1)", "PPose")]
    assert browser.caption("junk", BROKEN["junk"]) == "junk"


def test_build_gallery_with_broken_entries(tmp_path):
    pytest.importorskip("PIL.Image")
    result = browser.build_gallery(BROKEN, "", None, lambda n: str(tmp_path / "none.webp"),
                                   str(tmp_path / "tiles"))
    assert result["names"] == sorted(BROKEN)
    for n in BROKEN:
        browser.remove_placeholders(n, str(tmp_path / "tiles"))


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.parametrize("payload", [[1, 2], "text", 5, None, {"version": 1, "blocks": [1]},
                                     {"version": 1, "blocks": "x"}, {"version": 1, "blocks": None}])
def test_load_blocks_non_object_gives_empty(tmp_path, monkeypatch, capsys, payload):
    data = tmp_path / "data" / "blocks.json"
    monkeypatch.setattr(storage, "DATA_FILE", str(data))
    _write(data, payload)
    assert storage.load_blocks() == {}
    out = capsys.readouterr().out
    assert out.count("\n") == 1 and out.startswith("[PromptBlocks]")
    assert out.isascii()


def test_load_blocks_missing_blocks_key_is_silent(tmp_path, monkeypatch, capsys):
    data = tmp_path / "data" / "blocks.json"
    monkeypatch.setattr(storage, "DATA_FILE", str(data))
    _write(data, {"version": 1})
    assert storage.load_blocks() == {}
    assert capsys.readouterr().out == ""


def test_load_blocks_keeps_broken_entries(tmp_path, monkeypatch):
    # Single broken entries are kept (callers skip them), so a save does not silently drop them.
    data = tmp_path / "data" / "blocks.json"
    monkeypatch.setattr(storage, "DATA_FILE", str(data))
    _write(data, {"version": 1, "blocks": BROKEN})
    assert storage.load_blocks() == BROKEN


# ---- 5. Bulk status when the gallery list is capped ----

def test_capped_more():
    assert bulk.capped_more(60, 75, 60) == 15
    assert bulk.capped_more(60, 60, 60) == 0
    assert bulk.capped_more(10, 75, 60) == 0  # not capped: list shows every match
    assert bulk.capped_more(60, 40, 60) == 0


def test_active_status_capped():
    assert bulk.active_status(False, 58, 2, 60, 15) == (
        "Disabled 58 blocks (2 were already inactive). "
        "Only the 60 blocks shown were changed; 15 more match the filter.")
    assert bulk.active_status(True, 60, 0, 60, 1) == (
        "Enabled 60 blocks. Only the 60 blocks shown were changed; 1 more matches the filter.")
    assert bulk.active_status(True, 0, 0, 60, 3) == (
        "Nothing to change. Only the 60 blocks shown were checked; 3 more match the filter.")


def test_active_status_uncapped_unchanged():
    assert bulk.active_status(True, 3, 0) == "Enabled 3 blocks."
    assert bulk.active_status(True, 3, 0, 3, 0) == "Enabled 3 blocks."
    assert bulk.active_status(False, 0, 0, 5, 0) == "Nothing to change."


def test_broken_blocks_file_is_kept_aside_before_it_is_replaced(tmp_path, monkeypatch):
    from pb_core import storage
    data_file = tmp_path / "data" / "blocks.json"
    data_file.parent.mkdir()
    data_file.write_text('["not", "an", "object"]', encoding="utf-8")
    monkeypatch.setattr(storage, "DATA_FILE", str(data_file))
    monkeypatch.setattr(storage, "THUMB_DIR", str(tmp_path / "data" / "thumbs"))
    assert storage.load_blocks() == {}
    storage.save_blocks({"a": {"category": "C", "text": "t"}})
    kept = [p for p in data_file.parent.iterdir() if p.name.startswith("blocks.broken-")]
    assert len(kept) == 1
    assert kept[0].read_text(encoding="utf-8") == '["not", "an", "object"]'
    assert storage.load_blocks() == {"a": {"category": "C", "text": "t"}}


def test_valid_blocks_file_makes_no_broken_copy(tmp_path, monkeypatch):
    from pb_core import storage
    data_file = tmp_path / "data" / "blocks.json"
    monkeypatch.setattr(storage, "DATA_FILE", str(data_file))
    monkeypatch.setattr(storage, "THUMB_DIR", str(tmp_path / "data" / "thumbs"))
    storage.save_blocks({"a": {"category": "C", "text": "t"}})
    storage.save_blocks({"a": {"category": "C", "text": "t2"}})
    assert not [p for p in data_file.parent.iterdir() if p.name.startswith("blocks.broken-")]
