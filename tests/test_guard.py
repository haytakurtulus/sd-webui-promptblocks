"""Form state helpers (design notes sections 20 and 26): form_snapshot / is_dirty / is_modified,
switch_action and the refusal text."""

from pb_core import guard, subrows, subs

N = subrows.ROW_COUNT
NF = len(subrows.FORM_FIELDS)

BLOCKS = {
    "saber": {"category": "PChar", "text": "1girl, saber", "lora": "<lora:saber:0.8>", "weight": 2.5,
              "slot": "hero",
              "subs": [{"name": "armor", "text": "ARMOR", "mode": "include", "slot": "outfit"},
                       {"name": "dress", "text": "DRESS", "mode": "random", "chance": 30},
                       {"name": "hat", "text": "HAT", "mode": "exclude"}]},
    "rin": {"category": "PChar", "text": "rin", "active": False},
}


def loaded(name="saber"):
    return subrows.form_values(subrows.block_form(BLOCKS, name), with_chance=True)


def blank():
    return subrows.form_values(subrows.blank_form(), with_chance=True)


def idx(field):
    return subrows.FORM_FIELDS.index(field)


def row_idx(group, row):
    # Index in the flat values of row `row` of group 0 names, 1 texts, 2 modes, 3 slots, 5 chances
    # (4 is the meta value, a single entry).
    if group < 4:
        return NF + group * N + row
    return NF + 4 * N + 1 + row


def changed(values, index, value):
    values = list(values)
    values[index] = value
    return values


def test_equal_form_is_clean():
    snap = guard.form_snapshot(loaded())
    assert not guard.is_dirty(snap, loaded())


def test_round_trip_snapshot_of_loaded_block():
    # Snapshot of the stored block == snapshot of the values on_pick returns for it.
    assert guard.block_snapshot(BLOCKS, "saber") == guard.form_snapshot(loaded())
    snap = guard.block_snapshot(BLOCKS, "saber")
    assert snap["weight"] == 2.5 and snap["block_slot"] == "hero" and snap["lora"] == "<lora:saber:0.8>"
    assert snap["rows"] == [["armor", "ARMOR", "include", "outfit", 50],
                            ["dress", "DRESS", "random", None, 30],
                            ["hat", "HAT", "exclude", None, 50]]
    assert guard.block_snapshot(BLOCKS, "rin")["active"] is False


def test_missing_block_snapshot_is_blank():
    assert guard.block_snapshot(BLOCKS, "nope") == guard.blank_snapshot()
    assert guard.block_snapshot(BLOCKS, None) == guard.form_snapshot(blank())


def test_text_changed_is_dirty():
    snap = guard.form_snapshot(loaded())
    assert guard.is_dirty(snap, changed(loaded(), idx("text"), "1girl, saber, smile"))


def test_each_block_field_counts():
    snap = guard.form_snapshot(loaded())
    for field, value in (("name", "saber2"), ("category", "Other"), ("block_slot", "villain"),
                         ("weight", 3), ("active", False), ("lora", "")):
        assert guard.is_dirty(snap, changed(loaded(), idx(field), value)), field


def test_sub_row_changed_is_dirty():
    snap = guard.form_snapshot(loaded())
    for group, value in ((0, "armour"), (1, "ARMOR2"), (2, "random"), (3, "top"), (5, 40)):
        assert guard.is_dirty(snap, changed(loaded(), row_idx(group, 0), value)), group
    # Filling an empty row is a change too.
    v = changed(loaded(), row_idx(0, 3), "cape")
    assert guard.is_dirty(snap, changed(v, row_idx(1, 3), "CAPE"))


def test_whitespace_only_differences_do_not_count():
    snap = guard.form_snapshot(loaded())
    v = loaded()
    for field in ("name", "category", "text", "lora", "block_slot"):
        v = changed(v, idx(field), f"  {v[idx(field)]}\n")
    v = changed(v, row_idx(0, 0), " armor ")
    v = changed(v, row_idx(1, 1), "DRESS  ")
    v = changed(v, row_idx(3, 0), " outfit")
    assert not guard.is_dirty(snap, v)


def test_none_and_empty_string_are_equal():
    snap = guard.form_snapshot(blank())
    v = blank()
    v = changed(v, idx("name"), None)
    v = changed(v, idx("category"), "")
    v = changed(v, idx("text"), None)
    v = changed(v, idx("lora"), None)
    v = changed(v, idx("block_slot"), "  ")
    assert not guard.is_dirty(snap, v)


def test_weight_numeric_forms():
    snap = guard.form_snapshot(blank())  # weight 1
    assert not guard.is_dirty(snap, changed(blank(), idx("weight"), 1.0))
    assert guard.is_dirty(snap, changed(blank(), idx("weight"), 1.5))
    assert guard.is_dirty(snap, changed(blank(), idx("weight"), None))  # field emptied
    snap = guard.form_snapshot(loaded())  # weight 2.5
    assert not guard.is_dirty(snap, changed(loaded(), idx("weight"), 2.50))


def test_chance_numeric_forms_and_default():
    snap = guard.form_snapshot(loaded())
    for value in (None, "", " ", 50, 50.0):
        assert not guard.is_dirty(snap, changed(loaded(), row_idx(5, 0), value)), value
    assert not guard.is_dirty(snap, changed(loaded(), row_idx(5, 1), 30.0))
    assert guard.is_dirty(snap, changed(loaded(), row_idx(5, 1), 50))


def test_mode_default_and_case():
    snap = guard.form_snapshot(loaded())
    # A filled row whose mode is None reads as a blank row's mode (subs.NEW_ROW_MODE, sections 36 A, 37 A),
    # the same way subrows.rows_from_values reads it for Save; row 0 of saber is stored as include, row 1
    # as random.
    assert guard.is_dirty(snap, changed(loaded(), row_idx(2, 0), None)) == (subs.NEW_ROW_MODE != "include")
    assert guard.is_dirty(snap, changed(loaded(), row_idx(2, 1), None)) == (subs.NEW_ROW_MODE != "random")
    assert not guard.is_dirty(snap, changed(loaded(), row_idx(2, 1), "Random"))
    assert guard.is_dirty(snap, changed(loaded(), row_idx(2, 0), "exclude"))


def test_row_order_change_is_dirty():
    snap = guard.form_snapshot(loaded())
    rows = subrows.move_row(subrows.block_form(BLOCKS, "saber")["rows"], 0, 1)
    v = loaded()[:NF] + subrows.rows_to_values(rows, with_chance=True)
    assert guard.is_dirty(snap, v)


def test_empty_rows_ignored_and_their_position_does_not_matter():
    snap = guard.form_snapshot(loaded())
    # Move the last filled row (hat, row 2) down into the empty row 3: same filled order.
    rows = subrows.move_row(subrows.block_form(BLOCKS, "saber")["rows"], 2, 1)
    v = loaded()[:NF] + subrows.rows_to_values(rows, with_chance=True)
    assert not guard.is_dirty(snap, v)
    # An empty row with a non-default mode / slot / chance is still empty (Save drops it).
    v = changed(loaded(), row_idx(2, 3), "random")
    v = changed(v, row_idx(3, 3), "outfit")
    v = changed(v, row_idx(5, 3), 10)
    v = changed(v, row_idx(0, 3), "  ")
    assert not guard.is_dirty(snap, v)


def test_meta_and_chance_line_are_ignored():
    snap = guard.form_snapshot(loaded())
    v = changed(loaded(), idx("chance"), "something else")
    v = changed(v, NF + 4 * N, [{"orig": None} for _ in range(N)])
    assert not guard.is_dirty(snap, v)


def test_thumb_touched_makes_dirty():
    snap = guard.form_snapshot(loaded())
    assert guard.is_dirty(snap, loaded(), thumb_touched=True)


def test_missing_snapshot_means_blank_form():
    assert not guard.is_dirty(None, blank())
    assert guard.is_dirty(None, changed(blank(), idx("name"), "x"))


# ---- section 26: "modified" against the saved block, switch decision, refusal text ----

def test_is_modified_compares_with_the_saved_block():
    assert not guard.is_modified(BLOCKS, "saber", loaded())
    assert guard.is_modified(BLOCKS, "saber", changed(loaded(), idx("text"), "1girl, saber, smile"))
    # Same form, but the block on disk changed since (e.g. another action saved it): modified.
    other = dict(BLOCKS, saber=dict(BLOCKS["saber"], text="new text on disk"))
    assert guard.is_modified(other, "saber", loaded())
    # The form of rin compared with saber: modified.
    assert guard.is_modified(BLOCKS, "saber", loaded("rin"))


def test_is_modified_new_form_compares_with_blank():
    assert not guard.is_modified(BLOCKS, None, blank())
    assert guard.is_modified(BLOCKS, None, changed(blank(), idx("name"), "newblock"))
    # A loaded block that no longer exists counts as the blank form.
    assert not guard.is_modified(BLOCKS, "gone", blank())
    assert guard.is_modified(BLOCKS, "gone", loaded())


def test_is_modified_thumbnail_touched():
    assert guard.is_modified(BLOCKS, "saber", loaded(), thumb_touched=True)
    assert guard.is_modified(BLOCKS, None, blank(), thumb_touched=True)


def test_is_modified_after_a_save_of_the_same_values():
    # The values that were just saved (formsave) compare equal to the block on disk.
    from pb_core import formsave
    v = changed(loaded(), idx("text"), "  1girl, saber, edited  ")
    v = changed(v, row_idx(0, 0), " armor2 ")  # a sub-block rename
    plan = formsave.plan_form_save(BLOCKS, v, "saber")
    assert plan["error"] is None
    assert not guard.is_modified(plan["blocks"], "saber", v)


def test_switch_action():
    assert guard.switch_action(stale=False, modified=False, save_error=None) == "load"
    assert guard.switch_action(stale=False, modified=True, save_error=None) == "save"
    assert guard.switch_action(stale=False, modified=True, save_error="Text cannot be empty.") == "refuse"
    # A stale event (the form was replaced after it was triggered) never saves or refuses.
    assert guard.switch_action(stale=True, modified=True, save_error=None) == "load"
    assert guard.switch_action(stale=True, modified=True, save_error="x") == "load"


def test_refusal_message():
    msg = guard.refusal_message("Text cannot be empty.")
    assert msg == "⚠ Text cannot be empty. Fix it or press Reload to discard."
    assert guard.refusal_message("⚠ already warned.").startswith("⚠ already warned.")
    assert not guard.refusal_message("⚠ already warned.").startswith("⚠ ⚠")
    assert "again" not in msg.lower()
