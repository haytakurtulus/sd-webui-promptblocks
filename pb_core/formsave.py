"""Saving the management tab's form (design notes sections 11 and 26).

Pure Python, no gradio, no file access. One function, plan_form_save(), holds the whole rule of the Save
button: validation (name, category, block slot, weight, empty text, sub-block rows, chance, cycle check),
the new blocks dict and the status text. The Save button and the auto-save of a block switch (tile,
dropdown, New) both use it, so they can never drift apart. Only one thing differs: removing a sub-block
that other blocks reference asks for a second press on the Save button (confirm=True) and only adds a
warning to the status in an auto-save (confirm=False).

`values` is the flat list in the tab's component order (subrows.form_values(form, with_chance=True)):
FORM_FIELDS (name, category, block_slot, weight, active, chance line, text, lora, the four ADetailer
texts, bans), then the sub-block row
values (names, texts, modes, slots, meta, chances).
"""

import random

from . import adetailer, bans, lora, parser, subrows, subs, suggest, weights


def with_weight(block, w):
    # Weight is stored only when it differs from 1, so untouched blocks keep the old JSON shape.
    block = dict(block)
    if w == 1:
        block.pop("weight", None)
    else:
        block["weight"] = w
    return block


def with_active(block, active):
    # "active": false is stored only for inactive blocks; active blocks drop the key (old JSON shape).
    block = dict(block)
    if active:
        block.pop("active", None)
    else:
        block["active"] = False
    return block


def stored(blocks, n):
    """The stored block dict of `n`, or {} when missing or a broken non-dict entry (hand-edited data)."""
    b = blocks.get(n) if isinstance(blocks, dict) else None
    return b if isinstance(b, dict) else {}


def cycle_error(blocks, name):
    """Save-time cycle check: ~name and every ~name.sub, each with Random(0) (see CLAUDE.md 2b for the
    single-seed limitation), then every ADetailer text of the block (section 31a; as at Generate, without
    LoRA). The error text, or None."""
    try:
        for token in subrows.cycle_tokens(name, blocks[name]):
            parser.expand(token, blocks, random.Random(0), apply_bans=False)
    except parser.BlockCycleError as e:
        return str(e)
    for k, text in adetailer.adetailer_texts(blocks[name]):
        try:
            parser.expand(text, blocks, random.Random(0), lora=False, apply_bans=False)
        except parser.BlockCycleError as e:
            return f"ADetailer {adetailer.tab_label(k)}: {e}"
    return None


def removal_key(name, plan):
    """Key of the Save button's "removes a referenced sub-block" confirmation: the same change again."""
    return repr((name, plan["removals"], sorted(plan["renames"].items())))


def plan_form_save(blocks, values, loaded, pending=None, confirm=True, count=subrows.ROW_COUNT):
    """What saving the form `values` means for the saved data `blocks`.

    `loaded`: the block the form belongs to (None = a new / duplicated form). Only when the Name field
    still holds that name are renamed sub-block rows renames (identity tracking); any other Name saves a
    block under that name with all rows as new, and the loaded block stays as it is.
    `pending` / `confirm`: the Save button's two-step confirm for removing a referenced sub-block
    (confirm=True: the first press returns the warning and the key to remember; the second press with
    the same key saves). confirm=False (auto-save): saves and appends a warning instead; and a Name that
    differs from `loaded` but belongs to an existing block is an error (auto-save never replaces another
    block; the Save button does, and says so).

    Returns {"error": str or None, "pending": key or None, "name": the saved name, "blocks": the new
    blocks dict, "message": status text}. With an error nothing else is meaningful (and nothing may be
    written); "pending" is set only for the confirm warning."""
    values = list(values)
    n_form = len(subrows.FORM_FIELDS)
    form = dict(zip(subrows.FORM_FIELDS, values[:n_form]))
    sub_values = values[n_form:]

    def fail(msg, key=None):
        return {"error": msg, "pending": key, "name": None, "blocks": None, "message": msg}

    def text(v):
        return v.strip() if isinstance(v, str) else ""

    n, c, t = text(form["name"]), text(form["category"]), text(form["text"])
    if not parser.is_valid_name(n):
        return fail(f"Invalid name: `{n}` (must start with a letter; letters, digits, _)")
    cerr = parser.category_error(c)
    if cerr:
        return fail(cerr)
    bs, bserr = subs.validate_slot(form["block_slot"])
    if bserr:
        return fail(f"Not saved: block slot: {bserr}.")
    w, werr = weights.validate_weight(form["weight"])
    if werr:
        return fail(f"Not saved: {werr}")
    if not t:
        return fail("Text cannot be empty.")
    # Section 38 step 1: stored and validated only; expansion does not use bans yet.
    ban_list, berr = bans.parse_text(form["bans"])
    if berr:
        return fail(f"Not saved: {berr}")
    old = stored(blocks, n)
    exists = n in blocks
    # Rows were loaded from `loaded`; only when saving that same block are renamed rows sub-block
    # renames. Saving under another name treats all rows as new.
    plan, serr = subrows.plan_save(subrows.rows_from_values(sub_values, count), blocks.get(n),
                                   track_identity=(loaded == n and exists))
    if serr:
        return fail(f"Not saved: {serr}")
    is_new_category = c not in suggest.category_counts(blocks)
    hint = suggest.category_hint(c, blocks)
    is_new_slot = bs is not None and bs not in suggest.slot_counts(blocks)
    slot_hint = suggest.slot_hint(bs, blocks)
    candidate = dict(blocks)
    candidate[n] = bans.set_block_bans(adetailer.set_block_adetailer(lora.set_block_lora(subs.set_block_slot(
        subs.set_subs(with_active(with_weight({**old, "category": c, "text": t}, w), form["active"]), plan["subs"]),
        bs), form["lora"]), [form[f] for f in subrows.ADETAILER_FIELDS]), ban_list)
    candidate, updated = subrows.rename_sub_refs_many(candidate, n, plan["renames"])
    err = cycle_error(candidate, n)
    if err:
        return fail(f"Not saved: {err}")

    # Auto-save never replaces ANOTHER existing block (a Name typed over the loaded one, or a new form
    # named like an existing block): the switch is refused; only the Save button overwrites.
    if not confirm and exists and n != loaded:
        return fail(f"⚠ A block named `{n}` already exists. Press Save to overwrite it, or Reload to discard.")

    removal_users = {s: suggest.sub_users(candidate, n, s) for s in plan["removals"]}
    removal_users = {s: u for s, u in removal_users.items() if u}
    sep = parser.SUB_SEPARATOR
    used = "; ".join(f"`{parser.BLOCK_SYMBOL}{n}{sep}{s}` is used by: {', '.join(u)}"
                     for s, u in removal_users.items())
    if removal_users and confirm:
        key = removal_key(n, plan)
        if pending != key:
            return fail("⚠ This save removes a referenced sub-block: " + used
                        + ". **Press Save again to confirm.**", key)

    if isinstance(loaded, str) and loaded and n != loaded:
        if exists:
            msg = f"Saved `{n}` (replaced the existing block `{n}`; `{loaded}` is unchanged)."
        else:
            msg = f"Saved as new block `{n}` (`{loaded}` is unchanged)."
    else:
        msg = f"Saved `{n}`."
    if is_new_category:
        msg += " " + hint
    if is_new_slot:
        msg += " " + slot_hint
    if plan["renames"]:
        msg += " Renamed sub-blocks: " + ", ".join(
            f"`{o}` → `{nw}`" for o, nw in plan["renames"].items()) + "."
        if updated:
            msg += f" Updated references in: {', '.join(updated)}."
    if plan["removals"]:
        msg += " Removed sub-blocks: " + ", ".join(f"`{s}`" for s in plan["removals"]) + "."
    if removal_users and not confirm:
        msg += " ⚠ A removed sub-block is still referenced: " + used + "."
    return {"error": None, "pending": None, "name": n, "blocks": candidate, "message": msg}
