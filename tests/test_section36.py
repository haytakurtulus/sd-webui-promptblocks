"""Design notes section 36: new rows start as subs.NEW_ROW_MODE (A; Random in 36, Include again since 37 A), "Set sub-blocks of shown blocks" (B),
up to 6 sub-blocks per block (C)."""

import json
import random

import pytest

from pb_core import browser, bulk, formsave, guard, health, parser, storage, subrows, subs

N = subrows.ROW_COUNT
NF = len(subrows.FORM_FIELDS)


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_FILE", str(tmp_path / "blocks.json"))
    monkeypatch.setattr(storage, "THUMB_DIR", str(tmp_path / "thumbs"))


def idx(field):
    return subrows.FORM_FIELDS.index(field)


def row(group, i):
    # Flat index of row i in group 0 names, 1 texts, 2 modes, 3 slots, 5 chances (4 = the meta value).
    return NF + group * N + i if group < 4 else NF + 4 * N + 1 + i


def blank():
    return subrows.form_values(subrows.blank_form(), with_chance=True)


def put(values, pairs):
    values = list(values)
    for i, v in pairs:
        values[i] = v
    return values


# ---------------------------------------------------------------- A. new rows start as NEW_ROW_MODE

NEW = subs.NEW_ROW_MODE
# A stored mode that differs from the blank-row mode.
OTHER = "exclude" if NEW != "exclude" else "random"


def test_constants_split():
    assert subs.DEFAULT_MODE == "include"
    assert subs.NEW_ROW_MODE in subs.MODES


def test_blank_rows_and_new_form_show_new_row_mode():
    assert subrows.empty_row()["mode"] == NEW
    assert subrows.empty_row()["chance"] == subs.DEFAULT_CHANCE
    assert [r["mode"] for r in subrows.blank_form()["rows"]] == [NEW] * N
    values = blank()
    assert values[row(2, 0):row(2, 0) + N] == [NEW] * N
    # Padding rows of a loaded block are blank rows too.
    rows = subrows.rows_from_block({"text": "x", "subs": [{"name": "a", "text": "A", "mode": OTHER}]})
    assert [r["mode"] for r in rows] == [OTHER] + [NEW] * (N - 1)


def test_fresh_new_form_is_not_modified():
    assert not guard.is_modified({}, None, blank())
    assert not guard.is_modified({"x": {"category": "C", "text": "x"}}, None, blank())
    assert not guard.is_dirty(None, blank())
    # A blank row whose mode dropdown was changed is still an empty row: not modified.
    assert not guard.is_modified({}, None, put(blank(), [(row(2, 0), OTHER)]))


def test_loaded_block_with_blank_rows_is_not_modified():
    blocks = {"saber": {"category": "C", "text": "t",
                        "subs": [{"name": "armor", "text": "A", "mode": "include"}]}}
    values = subrows.form_values(subrows.block_form(blocks, "saber"), with_chance=True)
    assert not guard.is_modified(blocks, "saber", values)


def test_filled_blank_row_saves_as_new_row_mode():
    values = put(blank(), [(idx("name"), "zz"), (idx("category"), "C"), (idx("text"), "t"),
                           (row(0, 0), "hat"), (row(1, 0), "red hat")])
    plan = formsave.plan_form_save({}, values, None)
    assert plan["error"] is None
    assert plan["blocks"]["zz"]["subs"] == [{"name": "hat", "text": "red hat", "mode": NEW, "slot": None}]
    # Reloading the saved block gives an unmodified form.
    reloaded = subrows.form_values(subrows.block_form(plan["blocks"], "zz"), with_chance=True)
    assert not guard.is_modified(plan["blocks"], "zz", reloaded)


def test_stored_sub_without_mode_still_include():
    block = {"text": "t", "subs": [{"name": "a", "text": "A"}, {"name": "b", "text": "B", "mode": "bogus"}]}
    assert [s["mode"] for s in subs.normalize_subs(block)] == ["include", "include"]
    assert [r["mode"] for r in subrows.rows_from_block(block)][:2] == ["include", "include"]
    # Expansion: both are always added.
    assert parser.expand("~p", {"p": dict(block, category="C")}, random.Random(0)) == "t, A, B"


def test_stored_sub_without_mode_loaded_form_not_modified():
    blocks = {"p": {"category": "C", "text": "t", "subs": [{"name": "a", "text": "A"}]}}
    values = subrows.form_values(subrows.block_form(blocks, "p"), with_chance=True)
    assert values[row(2, 0)] == "include"
    assert not guard.is_modified(blocks, "p", values)


# ---------------------------------------------------------------- B. bulk.set_sub_modes

def data():
    return {
        "saber": {"category": "PChar", "text": "saber",
                  "subs": [{"name": "armor", "text": "ARMOR", "mode": "include", "slot": "outfit"},
                           {"name": "dress", "text": "DRESS", "mode": "random", "chance": 30},
                           {"name": "hat", "text": "HAT", "mode": "exclude", "extra": "kept"}]},
        "rin": {"category": "PChar", "text": "rin",
                "subs": [{"name": "bow", "text": "BOW"},                          # no mode = include
                         {"name": "cape", "text": "CAPE", "mode": "Random"}]},   # stored capitalised
        "beach": {"category": "PScene", "text": "beach",
                  "subs": [{"name": "sun", "text": "SUN", "mode": "include"}]},
        "plain": {"category": "PScene", "text": "plain"},
    }


def test_set_sub_modes_counts_and_only_mode_changes():
    blocks = data()
    before = json.loads(json.dumps(blocks))
    new, changed, count = bulk.set_sub_modes(blocks, ["saber", "rin", "plain"], "random")
    assert changed == ["saber", "rin"]
    assert count == 3  # armor, hat, bow (dress and the stored "Random" cape already are Random)
    assert blocks == before  # input not mutated
    assert new["saber"]["subs"] == [
        {"name": "armor", "text": "ARMOR", "mode": "random", "slot": "outfit"},
        {"name": "dress", "text": "DRESS", "mode": "random", "chance": 30},
        {"name": "hat", "text": "HAT", "mode": "random", "extra": "kept"}]
    assert new["rin"]["subs"] == [{"name": "bow", "text": "BOW", "mode": "random"},
                                  {"name": "cape", "text": "CAPE", "mode": "Random"}]
    assert new["beach"] is blocks["beach"] and new["plain"] is blocks["plain"]
    # Every other block field unchanged.
    for n in ("saber", "rin"):
        assert {k: v for k, v in new[n].items() if k != "subs"} == {k: v for k, v in blocks[n].items()
                                                                     if k != "subs"}


def test_set_sub_modes_random_keeps_stored_chance():
    new, _, _ = bulk.set_sub_modes(data(), ["saber"], "random")
    assert subs.sub_chance(new["saber"]["subs"][1]) == 30
    assert subs.sub_chance(new["saber"]["subs"][0]) == 50


def test_set_sub_modes_include_missing_mode_is_no_change():
    new, changed, count = bulk.set_sub_modes(data(), ["rin"], "include")
    assert changed == ["rin"] and count == 1  # only cape; bow (no mode) already behaves as include
    assert "mode" not in new["rin"]["subs"][0]
    assert new["rin"]["subs"][1]["mode"] == "include"


def test_set_sub_modes_nothing_to_change():
    blocks = data()
    new, changed, count = bulk.set_sub_modes(blocks, ["beach", "plain", "missing"], "include")
    assert (changed, count) == ([], 0)
    assert new == blocks


def test_set_sub_modes_skips_missing_duplicate_and_non_dict():
    blocks = dict(data(), broken="junk")
    _, changed, count = bulk.set_sub_modes(blocks, ["missing", "broken", "beach", "beach"], "exclude")
    assert changed == ["beach"] and count == 1


def test_set_sub_modes_leaves_unusable_entries_untouched():
    raw = ["junk", {"name": "1bad", "text": "x", "mode": "include"}, {"name": "ok", "text": "OK"},
           {"name": "ok", "text": "dup", "mode": "include"}, {"name": "notext", "mode": "include"}]
    raw += [{"name": f"s{i}", "text": "t", "mode": "include"} for i in range(subs.MAX_SUBS)]  # last is beyond
    blocks = {"b": {"category": "C", "text": "b", "subs": raw}}
    new, changed, count = bulk.set_sub_modes(blocks, ["b"], "exclude")
    got = new["b"]["subs"]
    assert count == subs.MAX_SUBS  # ok + s0..s4
    assert got[0] == "junk" and got[1]["mode"] == "include" and got[3]["mode"] == "include"
    assert got[4] == {"name": "notext", "mode": "include"}
    assert got[2]["mode"] == "exclude"
    assert [e["mode"] for e in got[5:]] == ["exclude"] * (subs.MAX_SUBS - 1) + ["include"]


def test_set_sub_modes_case_insensitive_mode_and_invalid():
    _, _, count = bulk.set_sub_modes(data(), ["beach"], " Exclude ")
    assert count == 1
    with pytest.raises(ValueError):
        bulk.set_sub_modes(data(), ["beach"], "sometimes")
    with pytest.raises(ValueError):
        bulk.set_sub_modes(data(), ["beach"], None)


def test_scope_respects_filter():
    # The handler acts on the browser's listed names (the same list as Enable shown): a category filter
    # or a search keeps the other blocks untouched.
    blocks = data()
    shown = browser.filter_names(blocks, "", "PScene")
    assert shown == ["beach", "plain"]
    new, changed, count = bulk.set_sub_modes(blocks, shown, "random")
    assert changed == ["beach"] and count == 1
    assert new["saber"] == blocks["saber"] and new["rin"] == blocks["rin"]
    shown = browser.filter_names(blocks, "sab", browser.ALL_CATEGORIES)
    _, changed, _ = bulk.set_sub_modes(blocks, shown, "random")
    assert changed == ["saber"]
    # No filter = all blocks.
    _, changed, count = bulk.set_sub_modes(blocks, browser.filter_names(blocks), "random")
    assert changed == ["beach", "rin", "saber"] and count == 1 + 1 + 2


def test_confirm_message_and_status():
    assert bulk.sub_modes_confirm("random", 5, 2) == (
        "⚠ Set 5 sub-blocks in 2 blocks to Random? **Press Set sub-blocks of shown blocks again to confirm.**")
    assert bulk.sub_modes_confirm("include", 1, 1).startswith("⚠ Set 1 sub-block in 1 block to Include?")
    assert bulk.sub_modes_status("exclude", 3, 2) == "Set 3 sub-blocks in 2 blocks to Exclude."
    assert bulk.sub_modes_status("random", 0, 0, 4).startswith("Nothing to change")
    assert "No blocks are shown" in bulk.sub_modes_status("random", 0, 0, 0)
    capped = bulk.sub_modes_confirm("random", 5, 2, shown=200, more=3)
    assert "Only the 200 blocks shown would be changed; 3 more match the filter." in capped


def test_confirm_key_same_plan_same_data_equal():
    blocks = data()
    _, changed, _ = bulk.set_sub_modes(blocks, ["saber", "rin"], "random")
    k1 = bulk.sub_modes_key(blocks, changed, "random")
    assert k1 == bulk.sub_modes_key(data(), list(changed), "random")


def test_confirm_key_changes_with_data_mode_or_scope():
    blocks = data()
    _, changed, _ = bulk.set_sub_modes(blocks, ["saber", "rin"], "random")
    k1 = bulk.sub_modes_key(blocks, changed, "random")
    # A data change between the presses (even in a block outside the scope) asks again.
    edited = dict(blocks, plain=dict(blocks["plain"], text="plain, edited"))
    assert bulk.sub_modes_key(edited, changed, "random") != k1
    # Another mode or another set of changed blocks asks again.
    assert bulk.sub_modes_key(blocks, changed, "exclude") != k1
    assert bulk.sub_modes_key(blocks, ["saber"], "random") != k1


def test_two_press_flow_saves_once(tmp_path):
    # The handler's flow on the pure parts: press 1 -> key, press 2 with the same key -> save.
    storage.save_blocks(data())
    blocks = storage.load_blocks()
    new, changed, count = bulk.set_sub_modes(blocks, ["saber", "rin", "beach"], "random")
    key = bulk.sub_modes_key(blocks, changed, "random")
    # Second press on unchanged data: same key -> save.
    again = storage.load_blocks()
    new2, changed2, _ = bulk.set_sub_modes(again, ["saber", "rin", "beach"], "random")
    assert bulk.sub_modes_key(again, changed2, "random") == key
    storage.save_blocks(new2)
    stored = json.loads((tmp_path / "blocks.json").read_text(encoding="utf-8"))["blocks"]
    assert [s["mode"] for s in stored["saber"]["subs"]] == ["random", "random", "random"]
    assert stored["saber"]["subs"][1]["chance"] == 30
    # A third press: nothing left to change.
    _, changed3, count3 = bulk.set_sub_modes(storage.load_blocks(), ["saber", "rin", "beach"], "random")
    assert (changed3, count3) == ([], 0)


def test_loaded_form_modified_detection_for_reload_rule():
    # The handler reloads an unmodified form of a changed block and keeps a modified one: is_modified
    # is evaluated against the data BEFORE the change.
    blocks = data()
    values = subrows.form_values(subrows.block_form(blocks, "saber"), with_chance=True)
    assert not guard.is_modified(blocks, "saber", values)
    edited = put(values, [(idx("text"), "saber, smile")])
    assert guard.is_modified(blocks, "saber", edited)
    new, changed, _ = bulk.set_sub_modes(blocks, ["saber"], "random")
    reloaded = subrows.form_values(subrows.block_form(new, "saber"), with_chance=True)
    assert reloaded[row(2, 0):row(2, 0) + 3] == ["random", "random", "random"]
    assert not guard.is_modified(new, "saber", reloaded)


# ---------------------------------------------------------------- C. up to 6 sub-blocks

def six_values(name="six", n=6):
    pairs = [(idx("name"), name), (idx("category"), "C"), (idx("text"), "base")]
    for i in range(n):
        pairs += [(row(0, i), f"s{i}"), (row(1, i), f"T{i}"), (row(2, i), "include")]
    return put(blank(), pairs)


def test_row_count_follows_max_subs():
    assert subs.MAX_SUBS == 6 and subrows.ROW_COUNT == 6
    assert len(subrows.blank_form()["rows"]) == 6


def test_block_with_six_subs_saves_and_expands(tmp_path):
    plan = formsave.plan_form_save({}, six_values(), None)
    assert plan["error"] is None
    storage.save_blocks(plan["blocks"])
    blocks = storage.load_blocks()
    assert subs.sub_names(blocks["six"]) == [f"s{i}" for i in range(6)]
    # expand: all six Include sub-blocks after the text; each one callable directly.
    trace = []
    assert parser.expand("~six", blocks, random.Random(0), trace=trace) == "base, " + ", ".join(
        f"T{i}" for i in range(6))
    assert trace == [("six", f"s{i}") for i in range(6)]  # preview's "subs_picked"
    for i in range(6):
        assert parser.expand(f"~six.s{i}", blocks, random.Random(0)) == f"T{i}"
    assert parser.find_unknown(parser.expand("~six.s5", blocks, random.Random(0))) == []
    # popup data (GET /promptblocks/blocks): all six sub-blocks.
    assert [s["name"] for s in subrows.api_block_slots(blocks["six"])["subs"]] == [f"s{i}" for i in range(6)]
    # The loaded form shows all six rows and is not modified.
    values = subrows.form_values(subrows.block_form(blocks, "six"), with_chance=True)
    assert values[row(0, 0):row(0, 0) + 6] == [f"s{i}" for i in range(6)]
    assert not guard.is_modified(blocks, "six", values)
    # Health: no "dropped" finding for six sub-blocks.
    assert not [f for f in health.report(blocks) if "dropped" in (f.get("detail") or "")]


def test_seventh_sub_block_rejected():
    rows = [{"name": f"s{i}", "text": "t", "mode": "random"} for i in range(7)]
    cleaned, err = subs.validate_subs(rows)
    assert cleaned is None and err == "A block can have at most 6 sub-blocks."


def test_old_data_with_four_subs_unchanged():
    block = {"category": "C", "text": "t", "subs": [{"name": f"s{i}", "text": f"T{i}", "mode": "include"}
                                                    for i in range(4)]}
    assert subs.sub_names(block) == ["s0", "s1", "s2", "s3"]
    values = subrows.form_values(subrows.block_form({"b": block}, "b"), with_chance=True)
    assert not guard.is_modified({"b": block}, "b", values)
    plan = formsave.plan_form_save({"b": block}, values, "b")
    assert plan["error"] is None
    assert subs.normalize_subs(plan["blocks"]["b"]) == subs.normalize_subs(block)
