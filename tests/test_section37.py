"""Design notes section 37: new rows start as Include again (A), "All Include | All Exclude | All Random" for
the open form (B). Part C (row classes) is CSS + JS and is checked by devtools/browser/scenario_sub_rows.py."""

import json
import os

import pytest

from pb_core import formsave, guard, storage, subrows, subs

N = subrows.ROW_COUNT
NF = len(subrows.FORM_FIELDS)


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_FILE", str(tmp_path / "blocks.json"))
    monkeypatch.setattr(storage, "THUMB_DIR", str(tmp_path / "thumbs"))


BLOCKS = {
    "saber": {"category": "C", "text": "1girl, saber",
              "subs": [{"name": "armor", "text": "ARMOR", "mode": "include", "slot": "outfit"},
                       {"name": "dress", "text": "DRESS", "mode": "random", "chance": 30},
                       {"name": "hat", "text": "HAT", "mode": "exclude"}]},
}


def group(values, g):
    # Row group g of flat form values: 0 names, 1 texts, 2 modes (with_chance layout).
    return list(values[NF + g * N:NF + (g + 1) * N])


def with_modes(values, modes):
    values = list(values)
    values[NF + 2 * N:NF + 3 * N] = modes
    return values


def loaded(name="saber"):
    return subrows.form_values(subrows.block_form(BLOCKS, name), with_chance=True)


def apply_all(values, mode):
    new, changed, filled = subrows.set_row_modes(group(values, 0), group(values, 1), group(values, 2), mode)
    return with_modes(values, new), changed, filled


# ---------------------------------------------------------------- A. new rows start as Include

def test_new_row_mode_is_include_again():
    assert subs.NEW_ROW_MODE == "include"
    assert subs.DEFAULT_MODE == "include"
    assert subrows.empty_row()["mode"] == "include"


def test_new_form_shows_include_in_all_rows():
    values = subrows.form_values(subrows.blank_form(), with_chance=True)
    assert group(values, 2) == ["include"] * N
    assert [r["mode"] for r in subrows.blank_form()["rows"]] == ["include"] * N


def test_fresh_new_form_is_not_modified():
    values = subrows.form_values(subrows.blank_form(), with_chance=True)
    assert not guard.is_modified({}, None, values)
    assert not guard.is_modified(BLOCKS, None, values)
    assert not guard.is_dirty(guard.blank_snapshot(), values)


def test_filled_new_row_saves_as_include():
    values = subrows.form_values(subrows.blank_form(), with_chance=True)
    values[subrows.FORM_FIELDS.index("name")] = "zz"
    values[subrows.FORM_FIELDS.index("category")] = "C"
    values[subrows.FORM_FIELDS.index("text")] = "t"
    values[NF] = "hat"
    values[NF + N] = "red hat"
    plan = formsave.plan_form_save({}, values, None)
    assert plan["error"] is None
    assert plan["blocks"]["zz"]["subs"] == [{"name": "hat", "text": "red hat", "mode": "include", "slot": None}]


# ---------------------------------------------------------------- B. set_row_modes helper

def test_set_row_modes_changes_only_filled_rows():
    names = ["a", "", "  ", "", "e", ""]
    texts = ["A", "", "", "only text", "", "  "]
    modes = ["include", "random", "random", "include", "random", "exclude"]
    new, changed, filled = subrows.set_row_modes(names, texts, modes, "exclude")
    # Rows 0, 3 (text only) and 4 (name only) are filled; 1, 2 (whitespace name), 5 (whitespace text) blank.
    assert new == ["exclude", "random", "random", "exclude", "exclude", "exclude"]
    assert filled == 3
    assert changed == 3
    # Inputs are not mutated.
    assert modes == ["include", "random", "random", "include", "random", "exclude"]


def test_set_row_modes_counts_only_real_changes():
    names, texts = ["a", "b", "c"], ["A", "B", "C"]
    new, changed, filled = subrows.set_row_modes(names, texts, ["random", "Random", "include"], "random")
    assert new == ["random", "random", "random"]
    assert (changed, filled) == (1, 3)  # "Random" equals random (case-insensitive)
    # An empty / None mode reads as NEW_ROW_MODE (include), as rows_from_values reads it.
    _, changed, _ = subrows.set_row_modes(["a", "b"], ["A", "B"], [None, ""], "include")
    assert changed == 0
    _, changed, _ = subrows.set_row_modes(["a", "b"], ["A", "B"], [None, ""], "exclude")
    assert changed == 2


def test_set_row_modes_no_filled_rows():
    modes = [None, "random", "exclude"]
    new, changed, filled = subrows.set_row_modes(["", " ", None], [None, "", "\n"], modes, "random")
    assert new == modes and (changed, filled) == (0, 0)


def test_set_row_modes_rejects_unknown_mode():
    with pytest.raises(ValueError):
        subrows.set_row_modes(["a"], ["A"], ["include"], "Random")
    with pytest.raises(ValueError):
        subrows.set_row_modes(["a"], ["A"], ["include"], None)


def test_status_texts():
    assert subrows.row_modes_status("exclude", 3, 3) == "Set 3 sub-blocks to Exclude. Press Save to keep it."
    assert subrows.row_modes_status("random", 1, 2) == "Set 1 sub-block to Random. Press Save to keep it."
    assert subrows.row_modes_status("include", 0, 0) == "No filled sub-block rows."
    assert subrows.row_modes_status("include", 0, 3) == (
        "Nothing to change: all 3 filled sub-block rows are already Include.")
    assert subrows.row_modes_status("include", 0, 1) == (
        "Nothing to change: the filled sub-block row is already Include.")


def test_all_exclude_on_loaded_form_is_modified_and_saved_by_switch():
    values, changed, filled = apply_all(loaded(), "exclude")
    assert (changed, filled) == (2, 3)
    assert group(values, 2) == ["exclude"] * 3 + ["include"] * (N - 3)
    # The guard sees a modified form, so a block switch auto-saves it (section 26).
    modified = guard.is_modified(BLOCKS, "saber", values)
    assert modified
    plan = formsave.plan_form_save(BLOCKS, values, "saber")
    assert plan["error"] is None
    assert guard.switch_action(False, modified, plan["error"]) == "save"
    saved = plan["blocks"]["saber"]["subs"]
    assert [s["mode"] for s in saved] == ["exclude"] * 3
    # Only the mode changed: names, texts, slot and the stored chance stay.
    assert [(s["name"], s["text"], s["slot"]) for s in saved] == [
        ("armor", "ARMOR", "outfit"), ("dress", "DRESS", None), ("hat", "HAT", None)]
    assert saved[1].get("chance") == 30


def test_all_random_keeps_chance_and_reload_restores():
    values, changed, _ = apply_all(loaded(), "random")
    assert changed == 2
    plan = formsave.plan_form_save(BLOCKS, values, "saber")
    assert [s["mode"] for s in plan["blocks"]["saber"]["subs"]] == ["random"] * 3
    assert plan["blocks"]["saber"]["subs"][1].get("chance") == 30
    # Reload = the stored block again: original modes, not modified.
    reloaded = subrows.form_values(subrows.block_form(BLOCKS, "saber"), with_chance=True)
    assert group(reloaded, 2)[:3] == ["include", "random", "exclude"]
    assert not guard.is_modified(BLOCKS, "saber", reloaded)


def test_no_change_keeps_form_unmodified():
    blocks = {"p": {"category": "C", "text": "t",
                    "subs": [{"name": "a", "text": "A", "mode": "random"},
                             {"name": "b", "text": "B", "mode": "random"}]}}
    values = subrows.form_values(subrows.block_form(blocks, "p"), with_chance=True)
    new_values, changed, filled = apply_all(values, "random")
    assert (changed, filled) == (0, 2)
    assert not guard.is_modified(blocks, "p", new_values)


def test_helper_writes_nothing_to_disk(tmp_path):
    storage.save_blocks(BLOCKS)
    before = (os.stat(storage.DATA_FILE).st_mtime_ns, open(storage.DATA_FILE, encoding="utf-8").read())
    apply_all(loaded(), "exclude")
    after = (os.stat(storage.DATA_FILE).st_mtime_ns, open(storage.DATA_FILE, encoding="utf-8").read())
    assert before == after
    assert json.loads(after[1])["blocks"]["saber"]["subs"][0]["mode"] == "include"
