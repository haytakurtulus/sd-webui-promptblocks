import json
import random

import pytest

from pb_core import parser, storage, subrows, subs, suggest


def row(name="", text="", mode="include", slot=None, orig=None):
    return {"name": name, "text": text, "mode": mode, "slot": slot, "orig": orig}


def saber():
    return {"category": "PCharacter", "text": "1girl, saber", "subs": [
        {"name": "outfit", "text": "armor", "mode": "include", "slot": "clothes"},
        {"name": "sword", "text": "excalibur", "mode": "random"},
        {"name": "hat", "text": "crown", "mode": "exclude"},
    ]}


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    # These helpers do not touch storage, but make sure nothing can reach the real data/ folder.
    monkeypatch.setattr(storage, "DATA_FILE", str(tmp_path / "blocks.json"))
    monkeypatch.setattr(storage, "THUMB_DIR", str(tmp_path / "thumbs"))


# --- rows_from_block ------------------------------------------------------------------------------

def test_rows_from_block_pads_and_keeps_identity_and_slot():
    rows = subrows.rows_from_block(saber())
    assert len(rows) == subrows.ROW_COUNT == subs.MAX_SUBS == 6
    pad = subrows.ROW_COUNT - 3
    assert [r["name"] for r in rows] == ["outfit", "sword", "hat"] + [""] * pad
    assert [r["orig"] for r in rows] == ["outfit", "sword", "hat"] + [None] * pad
    # Padding rows are blank rows: they start as subs.NEW_ROW_MODE (sections 36 A, 37 A).
    assert [r["mode"] for r in rows] == ["include", "random", "exclude"] + [subs.NEW_ROW_MODE] * pad
    assert rows[0]["slot"] == "clothes"
    assert rows[1]["slot"] is None
    assert rows[3:] == [subrows.empty_row()] * pad


def test_rows_from_old_block_without_subs():
    rows = subrows.rows_from_block({"category": "C", "text": "x"})
    assert rows == [subrows.empty_row() for _ in range(subrows.ROW_COUNT)]
    assert subrows.rows_from_block({}) == rows


def test_rows_from_block_skips_broken_entries():
    b = {"text": "x", "subs": [{"name": "1bad", "text": "t"}, {"name": "ok", "text": "t", "mode": "RANDOM"}]}
    rows = subrows.rows_from_block(b)
    assert [r["name"] for r in rows] == ["ok"] + [""] * (subrows.ROW_COUNT - 1)
    assert rows[0]["mode"] == "random"


# --- move_row -------------------------------------------------------------------------------------

def test_move_up_and_down():
    rows = subrows.rows_from_block(saber())
    up = subrows.move_row(rows, 1, -1)
    pad = [""] * (subrows.ROW_COUNT - 3)
    assert [r["name"] for r in up] == ["sword", "outfit", "hat"] + pad
    down = subrows.move_row(rows, 1, 1)
    assert [r["name"] for r in down] == ["outfit", "hat", "sword"] + pad
    # identity and slot travel with the row
    assert up[1]["orig"] == "outfit" and up[1]["slot"] == "clothes"


def test_move_edges_are_no_ops():
    rows = subrows.rows_from_block(saber())
    assert subrows.move_row(rows, 0, -1) == rows
    assert subrows.move_row(rows, subrows.ROW_COUNT - 1, 1) == rows
    assert subrows.move_row(rows, 7, -1) == rows


def test_move_does_not_modify_input():
    rows = subrows.rows_from_block(saber())
    before = [dict(r) for r in rows]
    moved = subrows.move_row(rows, 0, 1)
    assert rows == before
    moved[0]["name"] = "changed"
    assert rows[1]["name"] == "sword"


def test_move_empty_row_over_filled_row():
    rows = subrows.rows_from_block(saber())
    moved = subrows.move_row(rows, 3, -1)
    assert [r["name"] for r in moved] == ["outfit", "sword", "", "hat"] + [""] * (subrows.ROW_COUNT - 4)


# --- plan_save ------------------------------------------------------------------------------------

def test_plan_unchanged_rows():
    plan, err = subrows.plan_save(subrows.rows_from_block(saber()), saber(), True)
    assert err is None
    assert plan["renames"] == {} and plan["removals"] == []
    assert [s["name"] for s in plan["subs"]] == ["outfit", "sword", "hat"]


def test_plan_compacts_empty_rows_and_keeps_order():
    rows = [row(), row("a", "x", orig=None), row(), row("b", "y", "random")]
    plan, err = subrows.plan_save(rows, None, False)
    assert err is None
    assert plan["subs"] == [{"name": "a", "text": "x", "mode": "include", "slot": None},
                            {"name": "b", "text": "y", "mode": "random", "slot": None}]


def test_plan_rename_detected():
    rows = subrows.rows_from_block(saber())
    rows[0]["name"] = "armor"
    plan, err = subrows.plan_save(rows, saber(), True)
    assert err is None
    assert plan["renames"] == {"outfit": "armor"}
    assert plan["removals"] == []


def test_plan_rename_detection_survives_reordering():
    rows = subrows.rows_from_block(saber())
    rows = subrows.move_row(rows, 0, 1)   # outfit -> row 2
    rows = subrows.move_row(rows, 1, 1)   # outfit -> row 3
    rows = subrows.move_row(rows, 2, -1)  # back to row 2
    assert rows[1]["orig"] == "outfit"
    rows[1]["name"] = "armor"
    plan, err = subrows.plan_save(rows, saber(), True)
    assert err is None
    assert plan["renames"] == {"outfit": "armor"}
    assert plan["removals"] == []
    assert [s["name"] for s in plan["subs"]] == ["sword", "armor", "hat"]


def test_plan_reorder_only_is_not_a_rename():
    rows = subrows.move_row(subrows.rows_from_block(saber()), 0, 1)
    plan, _ = subrows.plan_save(rows, saber(), True)
    assert plan["renames"] == {} and plan["removals"] == []
    assert [s["name"] for s in plan["subs"]] == ["sword", "outfit", "hat"]


def test_plan_swapped_names_are_two_renames():
    rows = subrows.rows_from_block(saber())
    rows[0]["name"], rows[1]["name"] = "sword", "outfit"
    plan, err = subrows.plan_save(rows, saber(), True)
    assert err is None
    assert plan["renames"] == {"outfit": "sword", "sword": "outfit"}
    assert plan["removals"] == []


def test_plan_removal_detected():
    rows = subrows.rows_from_block(saber())
    rows[1] = row(orig="sword")  # cleared row keeps its identity
    plan, err = subrows.plan_save(rows, saber(), True)
    assert err is None
    assert plan["removals"] == ["sword"]
    assert plan["renames"] == {}
    assert [s["name"] for s in plan["subs"]] == ["outfit", "hat"]


def test_plan_removal_after_reorder():
    rows = subrows.move_row(subrows.rows_from_block(saber()), 2, -1)  # hat to row 2
    rows[1] = dict(rows[1], name="", text="")
    plan, _ = subrows.plan_save(rows, saber(), True)
    assert plan["removals"] == ["hat"]


def test_plan_removed_name_reused_by_new_row_is_not_a_removal():
    rows = subrows.rows_from_block(saber())
    rows[1] = row(orig="sword")
    rows[3] = row("sword", "new sword text")
    plan, _ = subrows.plan_save(rows, saber(), True)
    assert plan["removals"] == []
    assert plan["renames"] == {}


def test_plan_without_identity_treats_rows_as_new():
    # Saving under another existing name: no renames; that block's missing subs are removals.
    target = {"category": "C", "text": "t", "subs": [{"name": "outfit", "text": "a"},
                                                    {"name": "cape", "text": "b"}]}
    rows = subrows.rows_from_block(saber())
    rows[0]["name"] = "armor"
    plan, _ = subrows.plan_save(rows, target, False)
    assert plan["renames"] == {}
    assert plan["removals"] == ["cape", "outfit"]


def test_plan_orig_not_in_stored_block_is_new():
    rows = [row("x", "t", orig="gone")] + [row() for _ in range(3)]
    plan, err = subrows.plan_save(rows, {"text": "t"}, True)
    assert err is None
    assert plan["renames"] == {} and plan["removals"] == []


def test_plan_new_block_without_stored():
    plan, err = subrows.plan_save(subrows.rows_from_block(saber()), None, True)
    assert err is None
    assert plan["renames"] == {} and plan["removals"] == []


def test_plan_slot_preserved_through_reorder_and_rename():
    rows = subrows.move_row(subrows.rows_from_block(saber()), 0, 1)
    rows[1]["name"] = "armor"
    rows[1]["mode"] = "random"
    plan, _ = subrows.plan_save(rows, saber(), True)
    armor = [s for s in plan["subs"] if s["name"] == "armor"][0]
    assert armor["slot"] == "clothes"
    assert armor["mode"] == "random"
    block = subs.set_subs(saber(), plan["subs"])
    assert subs.get_sub(block, "armor")["slot"] == "clothes"
    # reload -> slot still in the row
    assert subrows.rows_from_block(block)[1]["slot"] == "clothes"


def test_plan_validation_errors_passed_through():
    rows = [row("outfit", ""), row(), row(), row()]
    plan, err = subrows.plan_save(rows, None, False)
    assert plan is None and "text cannot be empty" in err
    rows = [row("a", "x"), row("a", "y"), row(), row()]
    plan, err = subrows.plan_save(rows, None, False)
    assert plan is None and "duplicate" in err
    rows = [row("", "text only"), row(), row(), row()]
    plan, err = subrows.plan_save(rows, None, False)
    assert plan is None and "invalid name" in err


def test_plan_whitespace_only_row_is_empty():
    rows = [row("  ", "  ", orig="outfit"), row(), row(), row()]
    plan, err = subrows.plan_save(rows, saber(), True)
    assert err is None
    assert plan["subs"] == []
    assert plan["removals"] == ["hat", "outfit", "sword"]
    # empty list -> key removed on save (old JSON shape)
    assert "subs" not in subs.set_subs(saber(), plan["subs"])


# --- rename_sub_refs_many -------------------------------------------------------------------------

def test_rename_many_rewrites_everywhere():
    blocks = {
        "saber": saber(),
        "scene": {"category": "S", "text": "~saber.outfit, ~saber, ~rin.outfit",
                  "subs": [{"name": "x", "text": "~saber.outfit"}]},
        "other": {"category": "S", "text": "nothing"},
    }
    new, updated = subrows.rename_sub_refs_many(blocks, "saber", {"outfit": "armor"})
    assert updated == ["scene"]
    assert new["scene"]["text"] == "~saber.armor, ~saber, ~rin.outfit"
    assert new["scene"]["subs"][0]["text"] == "~saber.armor"
    assert blocks["scene"]["text"] == "~saber.outfit, ~saber, ~rin.outfit"  # input untouched


def test_rename_many_swap_is_simultaneous():
    blocks = {"scene": {"text": "~saber.outfit ~saber.sword"}}
    new, updated = subrows.rename_sub_refs_many(blocks, "saber", {"outfit": "sword", "sword": "outfit"})
    assert new["scene"]["text"] == "~saber.sword ~saber.outfit"
    assert updated == ["scene"]


def test_rename_many_empty_mapping():
    blocks = {"scene": {"text": "~saber.outfit"}}
    new, updated = subrows.rename_sub_refs_many(blocks, "saber", {})
    assert new == blocks and updated == []


def test_rename_sub_tokens_only_exact_parent_and_sub():
    text = "~saber.outfit, ~saber.outfits, ~saber.outfit., ~saberx.outfit, %saber.outfit"
    assert (parser.rename_sub_tokens(text, "saber", {"outfit": "armor"})
            == "~saber.armor, ~saber.outfits, ~saber.armor., ~saberx.outfit, %saber.outfit")


# --- full save flow (pure parts, as ui.on_save wires them) -----------------------------------------

def test_save_flow_rename_and_removal_warning():
    blocks = {
        "saber": saber(),
        "scene": {"category": "S", "text": "~saber.outfit, ~saber.hat"},
    }
    rows = subrows.rows_from_block(blocks["saber"])
    rows[0]["name"] = "armor"
    rows[2] = row(orig="hat")
    plan, err = subrows.plan_save(rows, blocks["saber"], True)
    assert err is None
    candidate = dict(blocks)
    candidate["saber"] = subs.set_subs(blocks["saber"], plan["subs"])
    candidate, updated = subrows.rename_sub_refs_many(candidate, "saber", plan["renames"])
    assert candidate["scene"]["text"] == "~saber.armor, ~saber.hat"
    assert updated == ["scene"]
    assert plan["removals"] == ["hat"]
    assert suggest.sub_users(candidate, "saber", "hat") == ["scene"]
    # stored JSON stays loadable with slot kept
    json.dumps(candidate)
    assert subs.get_sub(candidate["saber"], "armor")["slot"] == "clothes"


# --- cycle tokens -----------------------------------------------------------------------------------

def test_cycle_tokens_include_every_sub():
    assert subrows.cycle_tokens("saber", saber()) == ["~saber", "~saber.outfit", "~saber.sword", "~saber.hat"]
    assert subrows.cycle_tokens("x", {"text": "t"}) == ["~x"]


def test_cycle_through_excluded_sub_is_caught_by_direct_token():
    blocks = {"loop": {"category": "C", "text": "a",
                       "subs": [{"name": "s", "text": "~loop.s", "mode": "exclude"}]}}
    # ~loop alone does not reach the excluded sub ...
    parser.expand("~loop", blocks, random.Random(0))
    # ... but expanding ~loop.s directly does.
    with pytest.raises(parser.BlockCycleError):
        for token in subrows.cycle_tokens("loop", blocks["loop"]):
            parser.expand(token, blocks, random.Random(0))


# --- API shapes -------------------------------------------------------------------------------------

def test_api_trace():
    assert subrows.api_trace([("saber", "outfit")]) == [{"parent": "saber", "sub": "outfit"}]
    assert subrows.api_trace(None) == []
    trace = []
    parser.expand("~saber", {"saber": saber()}, random.Random(0), trace=trace)
    assert subrows.api_trace(trace)[0] == {"parent": "saber", "sub": "outfit"}


# --- Duplicate name -----------------------------------------------------------------------------------

def test_duplicate_name_unique():
    assert subrows.duplicate_name("saber", {"saber": {}}) == "saber_copy"
    assert subrows.duplicate_name("saber", {"saber": {}, "saber_copy": {}}) == "saber_copy2"
    assert subrows.duplicate_name("saber", {"saber_copy": {}, "saber_copy2": {}, "saber_copy3": {}}) \
        == "saber_copy4"
    assert subrows.duplicate_name("  saber ", {}) == "saber_copy"


def test_duplicate_name_empty_or_none():
    assert subrows.duplicate_name("", {}) == "block_copy"
    assert subrows.duplicate_name(None, {"block_copy": {}}) == "block_copy2"


def test_duplicate_name_is_valid_for_valid_names():
    assert parser.is_valid_name(subrows.duplicate_name("a", {}))
