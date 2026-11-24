"""Form state helpers of the management tab (design notes sections 20, 23a and 26).

Pure Python, no gradio. "Modified" is decided without a stored snapshot: the current form values are
compared with the block the form belongs to, as it is saved on disk now (or with the blank form for a
new block). A switch to another block (tile, dropdown) or New first auto-saves a modified form
(switch_action); see ui.py.

`values` everywhere is the flat list in the management tab's component order, i.e. the layout of
subrows.form_values(form, with_chance=True): FORM_FIELDS (name, category, block_slot, weight, active,
chance line, text, lora, the four ADetailer texts, bans), then the sub-block row values (names, texts, modes, slots, meta, chances).
The chance LINE (a computed hint), the row meta (identity) and the thumbnail are not compared;
thumbnail changes are passed separately as a "touched" flag.
"""

import hashlib
import json
import math

from . import adetailer, bans, subrows, subs


def data_key(blocks):
    """Short fingerprint of the saved data `blocks` (any JSON-shaped value), for the keys of two-step
    confirms (Delete, Restore backup, Move LoRA tags in ALL blocks, section 23a): a confirmation is valid
    only while the data it warned about is unchanged, so no event has to reset it. Key order does not
    matter; never raises."""
    try:
        s = json.dumps(blocks, sort_keys=True, ensure_ascii=False, default=repr)
    except (TypeError, ValueError):
        s = repr(blocks)
    return hashlib.sha1(s.encode("utf-8", "replace")).hexdigest()[:16]


def is_stale(seen, current):
    """True when a handler's view of the form is out of date (section 23a fix 6): `seen` is the form
    generation the browser had when the event was triggered, `current` the server's generation when the
    handler runs (a handler that reloaded / blanked the form in between changed it). Values are compared
    as text (a hidden Textbox sends strings); None counts as "0", the initial generation."""
    def norm(v):
        return "0" if v is None else str(v).strip()
    return norm(seen) != norm(current)


def _text(value):
    # Stripped string; None / non-strings count as "".
    return value.strip() if isinstance(value, str) else ""


def _number(value, default=None):
    # Numbers compare by value (1 == 1.0, 50 == 50.0); None / "" / whitespace give `default`.
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        value = float(value)
        if math.isfinite(value) and value.is_integer():
            return int(value)
        return value
    return value


def _mode(value):
    # None / "" = the mode of a blank form row (subs.NEW_ROW_MODE, as subrows.rows_from_values reads it);
    # strings compare case-insensitively (validate_subs lowers them).
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    if value is None or isinstance(value, str):
        return subs.NEW_ROW_MODE
    return value


def _slot(value):
    # None / "" / whitespace = no slot; strings are stripped (same rule as subs.validate_slot).
    if isinstance(value, str):
        return value.strip() or None
    return value


def form_snapshot(values, count=subrows.ROW_COUNT):
    """Normalised, comparable snapshot of the form values (layout: see the module docstring).

    Normalised the way Save normalises: strings stripped, None == "", weight 1 == 1.0, chance
    None / "" / 50 / 50.0 equal, mode None = random (a blank row's mode), slot "" = None. Completely empty
    sub-block rows are dropped (Save ignores them), the order of the remaining rows is kept (it is saved)."""
    values = list(values)
    n_form = len(subrows.FORM_FIELDS)
    form = dict(zip(subrows.FORM_FIELDS, values[:n_form]))
    rows = subrows.rows_from_values(values[n_form:], count)
    kept = [[_text(r["name"]), _text(r["text"]), _mode(r["mode"]), _slot(r["slot"]),
             _number(r["chance"], subs.DEFAULT_CHANCE)]
            for r in rows if not subrows.is_empty_row(r)]
    return {
        "name": _text(form["name"]),
        "category": _text(form["category"]),
        "block_slot": _slot(form["block_slot"]),
        "weight": _number(form["weight"]),
        "active": bool(form["active"]),
        "text": _text(form["text"]),
        "lora": _text(form["lora"]),
        "adetailer": adetailer.clean_texts([form[f] for f in subrows.ADETAILER_FIELDS]),
        "bans": bans.snapshot_value(form["bans"]),
        "rows": kept,
    }


def blank_snapshot(count=subrows.ROW_COUNT):
    """Snapshot of the blank form ("New")."""
    return form_snapshot(subrows.form_values(subrows.blank_form(count), with_chance=True), count)


def block_snapshot(blocks, name, count=subrows.ROW_COUNT):
    """Snapshot of block `name` as stored in `blocks` (the form after picking it); blank if missing."""
    return form_snapshot(subrows.form_values(subrows.block_form(blocks, name, count), with_chance=True),
                         count)


def is_dirty(snapshot, values, thumb_touched=False, count=subrows.ROW_COUNT):
    """True when the form `values` differ from `snapshot` (None = the blank form) or the thumbnail was
    touched."""
    if thumb_touched:
        return True
    if not isinstance(snapshot, dict):
        snapshot = blank_snapshot(count)
    return form_snapshot(values, count) != snapshot


def is_modified(blocks, loaded, values, thumb_touched=False, count=subrows.ROW_COUNT):
    """Section 26: True when the form `values` differ from their source, i.e. block `loaded` as saved in
    `blocks` now (None, or a block that no longer exists = the blank form), or the thumbnail was
    touched since the form was loaded / saved / blanked."""
    return is_dirty(block_snapshot(blocks, loaded, count), values, thumb_touched, count)


def switch_action(stale, modified, save_error):
    """What a block switch (tile, dropdown pick, New) does (section 26):
    "load" (the form is not modified, or it is stale: it was replaced after the event was triggered, so
    the values sent with the event are not the form on screen and must not be saved), "save" (modified
    and valid: save it, then load / blank) or "refuse" (modified and invalid: keep the form)."""
    if stale or not modified:
        return "load"
    return "refuse" if save_error else "save"


def refusal_message(error):
    """Status text of a refused switch: the validation error and what to do (unless the error already
    says it, e.g. "... Press Save to overwrite it, or Reload to discard.")."""
    error = (error or "").strip()
    if not error.startswith("⚠"):
        error = "⚠ " + error
    if "Reload" in error:
        return error
    return f"{error} Fix it or press Reload to discard."
