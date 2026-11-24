"""Saving the management tab's form (design notes section 26): formsave.plan_form_save, the one rule
shared by the Save button and the auto-save of a block switch."""

import pytest

from pb_core import formsave, guard, subrows

N = subrows.ROW_COUNT
NF = len(subrows.FORM_FIELDS)

BLOCKS = {
    "saber": {"category": "PChar", "text": "1girl, saber", "lora": "<lora:saber:0.8>",
              "subs": [{"name": "armor", "text": "ARMOR", "mode": "include", "slot": "outfit"},
                       {"name": "hat", "text": "HAT", "mode": "exclude", "slot": None}]},
    "rin": {"category": "PChar", "text": "rin, ~saber.hat", "weight": 3},
}


def form(name="saber", blocks=BLOCKS):
    return subrows.form_values(subrows.block_form(blocks, name), with_chance=True)


def blank():
    return subrows.form_values(subrows.blank_form(), with_chance=True)


def idx(field):
    return subrows.FORM_FIELDS.index(field)


def row(group, i):
    # Flat index of row i in group 0 names, 1 texts, 2 modes, 3 slots, 5 chances (4 = the meta value).
    return NF + group * N + i if group < 4 else NF + 4 * N + 1 + i


def put(values, **fields):
    values = list(values)
    for k, v in fields.items():
        values[idx(k)] = v
    return values


def test_unchanged_form_saves_same_data():
    plan = formsave.plan_form_save(BLOCKS, form(), "saber")
    assert plan["error"] is None and plan["name"] == "saber"
    assert plan["blocks"]["saber"] == BLOCKS["saber"]
    assert plan["message"] == "Saved `saber`."


def test_edit_is_saved_and_other_blocks_kept():
    plan = formsave.plan_form_save(BLOCKS, put(form(), text=" 1girl, saber, smile "), "saber")
    assert plan["blocks"]["saber"]["text"] == "1girl, saber, smile"
    assert plan["blocks"]["rin"] == BLOCKS["rin"]
    assert BLOCKS["saber"]["text"] == "1girl, saber"  # input not mutated


@pytest.mark.parametrize("fields, error", [
    ({"name": ""}, "Invalid name"),
    ({"name": "1abc"}, "Invalid name"),
    ({"category": ""}, "Category is empty."),
    ({"category": "9Cat"}, "Invalid category: `9Cat` (must start with a letter; letters, digits, _)"),
    ({"text": "   "}, "Text cannot be empty."),
    ({"weight": 0}, "Not saved:"),
    ({"block_slot": "bad slot!"}, "Not saved: block slot"),
])
def test_validation_errors(fields, error):
    plan = formsave.plan_form_save(BLOCKS, put(form(), **fields), "saber")
    assert plan["error"] and plan["error"].startswith(error), plan["error"]
    assert plan["blocks"] is None and plan["pending"] is None


def test_blank_form_with_only_a_name_is_invalid():
    plan = formsave.plan_form_save(BLOCKS, put(blank(), name="newblock"), None)
    assert plan["error"] == "Category is empty."


def test_sub_row_and_chance_errors():
    v = form()
    v[row(0, 1)] = "armor"  # duplicate sub-block name
    assert formsave.plan_form_save(BLOCKS, v, "saber")["error"].startswith("Not saved:")
    v = form()
    v[row(2, 0)] = "random"
    v[row(5, 0)] = 0  # chance out of range
    assert formsave.plan_form_save(BLOCKS, v, "saber")["error"].startswith("Not saved:")


def test_cycle_is_an_error():
    plan = formsave.plan_form_save(BLOCKS, put(form(), text="1girl, ~saber"), "saber")
    assert plan["error"].startswith("Not saved:")


def test_changed_name_creates_a_new_block():
    plan = formsave.plan_form_save(BLOCKS, put(form(), name="saber2"), "saber")
    assert plan["error"] is None and plan["name"] == "saber2"
    assert plan["blocks"]["saber"] == BLOCKS["saber"]
    assert plan["blocks"]["saber2"]["text"] == "1girl, saber"
    assert plan["message"].startswith("Saved as new block `saber2` (`saber` is unchanged).")


def test_changed_name_to_an_existing_block_says_so():
    plan = formsave.plan_form_save(BLOCKS, put(form(), name="rin"), "saber")
    assert plan["error"] is None
    assert plan["message"].startswith("Saved `rin` (replaced the existing block `rin`; `saber` is unchanged).")


def test_new_form_message():
    v = put(blank(), name="zz", category="PChar", text="zz text")
    plan = formsave.plan_form_save(BLOCKS, v, None)
    assert plan["error"] is None and plan["message"].startswith("Saved `zz`.")
    assert plan["blocks"]["zz"] == {"category": "PChar", "text": "zz text"}


def test_sub_rename_tracked_only_for_the_loaded_block():
    v = form()
    v[row(0, 1)] = "cap"  # rename hat -> cap
    plan = formsave.plan_form_save(BLOCKS, v, "saber")
    assert plan["error"] is None
    assert plan["blocks"]["rin"]["text"] == "rin, ~saber.cap"
    assert "Renamed sub-blocks" in plan["message"]
    # The same rows on a form that does not belong to saber (e.g. a duplicate) are all new: hat is
    # removed, and it is referenced, so the Save button asks first.
    plan = formsave.plan_form_save(BLOCKS, v, None)
    assert plan["pending"] is not None and "Press Save again" in plan["error"]


def test_removing_a_referenced_sub_block_save_button_asks_twice():
    v = form()
    v[row(0, 1)] = ""
    v[row(1, 1)] = ""  # remove hat (used by rin)
    first = formsave.plan_form_save(BLOCKS, v, "saber", pending=None, confirm=True)
    assert first["blocks"] is None and first["pending"]
    assert "~saber.hat` is used by: rin" in first["error"] and "Press Save again" in first["error"]
    second = formsave.plan_form_save(BLOCKS, v, "saber", pending=first["pending"], confirm=True)
    assert second["error"] is None and [s["name"] for s in second["blocks"]["saber"]["subs"]] == ["armor"]
    assert "still referenced" not in second["message"]
    # Another pending key (a different change) asks again.
    again = formsave.plan_form_save(BLOCKS, v, "saber", pending="other", confirm=True)
    assert again["error"] and again["pending"] == first["pending"]


def test_removing_a_referenced_sub_block_auto_save_saves_and_warns():
    v = form()
    v[row(0, 1)] = ""
    v[row(1, 1)] = ""
    plan = formsave.plan_form_save(BLOCKS, v, "saber", confirm=False)
    assert plan["error"] is None and plan["pending"] is None
    assert [s["name"] for s in plan["blocks"]["saber"]["subs"]] == ["armor"]
    assert "Removed sub-blocks: `hat`." in plan["message"]
    assert "⚠ A removed sub-block is still referenced: `~saber.hat` is used by: rin." in plan["message"]
    assert "again" not in plan["message"].lower()


def test_new_category_and_slot_hints_in_message():
    plan = formsave.plan_form_save(BLOCKS, put(form(), category="Heroes", block_slot="lead"), "saber")
    assert plan["error"] is None
    assert "New category" in plan["message"] and "slot" in plan["message"].lower()


def test_saved_values_are_not_modified_afterwards():
    v = put(form(), weight=2.0, active=False, lora="  <lora:x:1>  ")
    plan = formsave.plan_form_save(BLOCKS, v, "saber")
    assert plan["error"] is None
    assert plan["blocks"]["saber"]["weight"] == 2 and plan["blocks"]["saber"]["active"] is False
    assert not guard.is_modified(plan["blocks"], "saber", v)


def test_weight_and_active_defaults_omitted():
    plan = formsave.plan_form_save(BLOCKS, put(form("rin"), weight=1, active=True), "rin")
    assert "weight" not in plan["blocks"]["rin"] and "active" not in plan["blocks"]["rin"]


def test_with_helpers_and_stored():
    assert formsave.with_weight({"weight": 3}, 1) == {}
    assert formsave.with_weight({}, 2.5) == {"weight": 2.5}
    assert formsave.with_active({"active": False}, True) == {}
    assert formsave.with_active({}, False) == {"active": False}
    assert formsave.stored({"a": "broken"}, "a") == {} and formsave.stored({}, "x") == {}
    assert formsave.stored(BLOCKS, "rin") is BLOCKS["rin"]


# ---- auto-save never replaces another existing block (orchestrator decision on section 26) ----

OVERWRITE = "⚠ A block named `rin` already exists. Press Save to overwrite it, or Reload to discard."


def test_auto_save_refuses_name_of_another_existing_block():
    plan = formsave.plan_form_save(BLOCKS, put(form(), name=" rin "), "saber", confirm=False)
    assert plan["error"] == OVERWRITE and plan["blocks"] is None and plan["pending"] is None
    assert guard.refusal_message(plan["error"]) == OVERWRITE


def test_auto_save_refuses_new_form_named_like_existing_block():
    v = put(blank(), name="rin", category="PChar", text="other text")
    plan = formsave.plan_form_save(BLOCKS, v, None, confirm=False)
    assert plan["error"] == OVERWRITE and plan["blocks"] is None


def test_auto_save_new_unused_name_saves_as_new_block():
    plan = formsave.plan_form_save(BLOCKS, put(form(), name="saber3"), "saber", confirm=False)
    assert plan["error"] is None and "saber3" in plan["blocks"]
    assert plan["blocks"]["saber"] == BLOCKS["saber"]
    assert plan["message"].startswith("Saved as new block `saber3` (`saber` is unchanged).")


def test_auto_save_unchanged_name_saves():
    plan = formsave.plan_form_save(BLOCKS, put(form(), text="1girl, saber, edited"), "saber", confirm=False)
    assert plan["error"] is None and plan["blocks"]["saber"]["text"] == "1girl, saber, edited"
    assert plan["message"].startswith("Saved `saber`.")


def test_save_button_still_overwrites_existing_block():
    plan = formsave.plan_form_save(BLOCKS, put(form(), name="rin"), "saber", confirm=True)
    assert plan["error"] is None and plan["blocks"]["rin"]["text"] == "1girl, saber"
