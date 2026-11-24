"""Row logic of the management tab's sub-block panel (design notes section 3, step 3b).

Pure Python, no gradio. ui.py only packs / unpacks component values into the row dicts used here.

A row is {"name": str, "text": str, "mode": str, "slot": str|None, "chance": int, "orig": str|None}.
"orig" is the name the row's sub-block had when it was loaded (None for a row that was empty at load
time). "orig" is the row's identity: it moves with the row on up/down, so a renamed row is recognised
wherever it ends up. "slot" (section 4) and "chance" (section 14, percent for Random, default 50) are
editable fields of the row; they move with the row too.

Component values (see rows_to_values): names..., texts..., modes..., slots..., meta[, chances...], where
meta is a hidden list [{"orig": ...}, ...]. The chance group is only present with with_chance=True (the
management tab always uses it; the 4-group layout is kept as the default for older callers). The slot and
the chance come only from the visible fields, never from meta.
"""

from . import adetailer, bans, lora, parser, subs, suggest, weights

ROW_COUNT = subs.MAX_SUBS

# ADetailer texts of the form, tab 1st..4th (section 31a).
ADETAILER_FIELDS = tuple(f"adetailer_{k + 1}" for k in range(adetailer.TABS))
# Block-level form fields of the management tab, in the order form_values() returns them
# (design notes section 11). The sub-block row values follow them. "bans" (section 38) is the Bans box text.
FORM_FIELDS = (("name", "category", "block_slot", "weight", "active", "chance", "text", "lora") + ADETAILER_FIELDS
               + ("bans",))


def empty_row():
    # A new / blank row starts as subs.NEW_ROW_MODE (sections 36 A, 37 A); stored data without "mode" stays "include".
    return {"name": "", "text": "", "mode": subs.NEW_ROW_MODE, "slot": None, "chance": subs.DEFAULT_CHANCE,
            "orig": None}


def is_empty_row(row):
    # Same rule as subs.validate_subs (non-strings count as empty), so filled rows line up with its output.
    name, text = row.get("name"), row.get("text")
    name = name.strip() if isinstance(name, str) else ""
    text = text.strip() if isinstance(text, str) else ""
    return not name and not text


def rows_from_block(block, count=ROW_COUNT):
    """`count` rows for the panel: the block's normalised sub-blocks in stored order, then empty rows."""
    rows = [{"name": s["name"], "text": s["text"], "mode": s["mode"], "slot": s["slot"],
             "chance": subs.sub_chance(s), "orig": s["name"]}
            for s in subs.normalize_subs(block)][:count]
    while len(rows) < count:
        rows.append(empty_row())
    return rows


def rows_to_values(rows, with_chance=False):
    """Row dicts -> flat component values [names..., texts..., modes..., slots..., meta], followed by
    [chances...] when with_chance is True. Slot None is sent as None (empty dropdown).
    meta = [{"orig": ...}, ...] (row identity only). A row without "chance" sends DEFAULT_CHANCE."""
    values = ([r["name"] for r in rows] + [r["text"] for r in rows] + [r["mode"] for r in rows]
              + [r["slot"] for r in rows] + [[{"orig": r["orig"]} for r in rows]])
    if with_chance:
        values += [r.get("chance", subs.DEFAULT_CHANCE) for r in rows]
    return values


def _slot_value(value):
    # Slot dropdown value -> row slot. None / "" / whitespace -> None; a string is stripped; anything
    # else is kept as it is so that validate_subs reports it.
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    return value


def _chance_value(value):
    # Chance number field value -> row chance. None / "" / whitespace -> DEFAULT_CHANCE; anything else is
    # kept as it is (e.g. 30.0 from Gradio) so that validate_subs accepts or reports it.
    if value is None or (isinstance(value, str) and not value.strip()):
        return subs.DEFAULT_CHANCE
    return value


def rows_from_values(values, count=ROW_COUNT):
    """Inverse of rows_to_values (with or without the chance group). The slot and the chance are read
    from the visible values; meta only gives "orig". Missing / broken meta entries give orig None;
    a missing chance group gives DEFAULT_CHANCE; an empty mode gives NEW_ROW_MODE (the mode of a blank row,
    sections 36 A, 37 A)."""
    values = list(values)
    names, texts = values[:count], values[count:2 * count]
    modes, slots = values[2 * count:3 * count], values[3 * count:4 * count]
    meta = values[4 * count] if len(values) > 4 * count else None
    chances = values[4 * count + 1:5 * count + 1]
    rows = []
    for i in range(count):
        m = meta[i] if isinstance(meta, list) and i < len(meta) and isinstance(meta[i], dict) else {}
        rows.append({"name": names[i] or "", "text": texts[i] or "", "mode": modes[i] or subs.NEW_ROW_MODE,
                     "slot": _slot_value(slots[i]),
                     "chance": _chance_value(chances[i] if i < len(chances) else None),
                     "orig": m.get("orig")})
    return rows


def _row_mode(value):
    # A row's mode dropdown value for comparison (same rule as guard._mode): strings case-insensitive,
    # None / "" = the mode of a blank row (NEW_ROW_MODE, as rows_from_values reads it).
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    if value is None or isinstance(value, str):
        return subs.NEW_ROW_MODE
    return value


def set_row_modes(names, texts, modes, mode):
    """"All Include | All Exclude | All Random" of the open form (section 37 B): `mode` for every FILLED
    row (name or text non-blank after strip, the is_empty_row rule); blank rows keep their value.
    Returns (new modes list, changed count, filled count). changed = filled rows whose mode really
    differs (case-insensitive; an empty mode reads as NEW_ROW_MODE). An unknown `mode` raises ValueError."""
    if mode not in subs.MODES:
        raise ValueError(f"unknown sub-block mode: {mode!r}")
    new, changed, filled = [], 0, 0
    for name, text, old in zip(names, texts, modes):
        if is_empty_row({"name": name, "text": text}):
            new.append(old)
            continue
        filled += 1
        if _row_mode(old) != mode:
            changed += 1
        new.append(mode)
    return new, changed, filled


def row_modes_status(mode, changed, filled):
    """Status line of the section 37 B buttons (`changed` / `filled` as set_row_modes returns them)."""
    label = mode.capitalize()
    if not filled:
        return "No filled sub-block rows."
    if not changed:
        return (f"Nothing to change: the filled sub-block row is already {label}." if filled == 1
                else f"Nothing to change: all {filled} filled sub-block rows are already {label}.")
    return f"Set {changed} sub-block{'' if changed == 1 else 's'} to {label}. Press Save to keep it."


def blank_form(count=ROW_COUNT):
    """Form state of the "New" button (section 11): empty name / category / text / LoRA / ADetailer
    texts / bans, weight 1, active, no block slot, no chance line, `count` empty sub-block rows."""
    return {"name": "", "category": None, "block_slot": None, "weight": weights.DEFAULT_WEIGHT,
            "active": True, "chance": "", "text": "", "lora": "",
            **{f: "" for f in ADETAILER_FIELDS}, "bans": "",
            "rows": [empty_row() for _ in range(count)]}


def block_form(blocks, name, count=ROW_COUNT):
    """Form state for block `name` as stored in `blocks` (picking it in the dropdown).
    A missing name / non-dict block gives blank_form(). LoRA is the normalised text ("" for none), the
    ADetailer texts the normalised four texts (section 31a), bans the normalised list as box text (section 38)."""
    block = blocks.get(name) if isinstance(blocks, dict) and isinstance(name, str) else None
    if not isinstance(block, dict) or not block:
        return blank_form(count)
    c = block.get("category", "")
    return {"name": name, "category": c, "block_slot": subs.block_slot(block),
            "weight": weights.block_weight(block), "active": weights.is_active(block),
            "chance": weights.chance_line(blocks, name, c), "text": block.get("text", ""),
            "lora": lora.block_lora(block) or "",
            **dict(zip(ADETAILER_FIELDS, adetailer.block_adetailer(block))),
            "bans": bans.to_text(bans.block_bans(block)),
            "rows": rows_from_block(block, count)}


COPY_SUFFIX = "_copy"


def duplicate_name(name, existing):
    """Name for "Duplicate" (section 11, round 2): `<name>_copy`, or `<name>_copy2`, `_copy3`, ...
    when taken (by a key of `existing`). An empty / non-string name uses the base "block"."""
    base = name.strip() if isinstance(name, str) else ""
    base = (base or "block") + COPY_SUFFIX
    if base not in existing:
        return base
    i = 2
    while f"{base}{i}" in existing:
        i += 1
    return f"{base}{i}"


def form_values(form, with_chance=False):
    """Form dict -> flat values: FORM_FIELDS in order, then rows_to_values(form["rows"], with_chance)."""
    return [form[k] for k in FORM_FIELDS] + rows_to_values(form["rows"], with_chance)


def move_row(rows, index, delta):
    """New list with row `index` swapped with row `index + delta` (delta -1 = up, +1 = down).
    Out-of-range moves (first row up, last row down) return an unchanged copy. Rows are copied."""
    rows = [dict(r) for r in rows]
    target = index + delta
    if 0 <= index < len(rows) and 0 <= target < len(rows):
        rows[index], rows[target] = rows[target], rows[index]
    return rows


def plan_save(rows, stored_block, track_identity):
    """Work out what saving the panel rows means for a block.

    `stored_block`: the block as currently stored under the name being saved (None for a new block).
    `track_identity`: True when the rows were loaded from that same block (Name field == dropdown
    selection); then a row whose name differs from its "orig" is a rename. Otherwise rows are all new.

    Returns (plan, None) or (None, error). plan = {
        "subs": cleaned sub list for subs.set_subs (compacted, slot and chance kept per row),
        "renames": {old: new} (stored names only, applied with rename_sub_refs_many),
        "removals": stored sub names that no longer exist after the save (sorted)}.
    A stored name that is renamed away is not a removal; a stored name that is still present after
    the save (kept, or reused by another row) is not a removal either, since ~parent.name still resolves.
    """
    cleaned, err = subs.validate_subs(rows)
    if err:
        return None, err
    stored = subs.sub_names(stored_block) if isinstance(stored_block, dict) else []
    filled = [r for r in rows if not is_empty_row(r)]  # same order and length as `cleaned`
    renames, survivors = {}, set()
    if track_identity:
        for row, s in zip(filled, cleaned):
            orig = row.get("orig")
            if orig in stored:
                survivors.add(orig)
                if s["name"] != orig:
                    renames[orig] = s["name"]
    final = {s["name"] for s in cleaned}
    removals = sorted(n for n in stored if n not in survivors and n not in final)
    return {"subs": cleaned, "renames": renames, "removals": removals}, None


def rename_sub_refs_many(blocks, parent, mapping):
    """Rewrite ~parent.old -> ~parent.mapping[old] for all keys at once in every block text,
    sub-block text and ADetailer text. Returns (new_blocks, sorted names of changed blocks). Empty mapping = no change."""
    if not mapping:
        return dict(blocks), []
    return subs._rewrite_all(blocks, lambda t: parser.rename_sub_tokens(t, parent, mapping))


def cycle_tokens(name, block):
    """Tokens the save-time cycle check expands: ~name, then ~name.sub for every sub-block, so cycles
    through an Exclude sub or a Random sub that loses its draw are caught too."""
    sep = parser.SUB_SEPARATOR
    return [parser.BLOCK_SYMBOL + name] + [parser.BLOCK_SYMBOL + name + sep + s
                                           for s in subs.sub_names(block)]


def api_block_slots(block):
    """Slot fields for GET /promptblocks/blocks (section 4): {"slot": block slot or None,
    "subs": [{"name", "mode", "text", "slot"[, "chance"]}]} (normalised, stored order); "chance" (int,
    section 14) is present only when it differs from 50. Merged over the raw block."""
    return {"slot": subs.block_slot(block),
            "subs": [subs.add_chance({"name": s["name"], "mode": s["mode"], "text": s["text"],
                                        "slot": s["slot"]}, subs.sub_chance(s))
                     for s in subs.normalize_subs(block)]}


def api_block_lora(block):
    """LoRA field for GET /promptblocks/blocks (section 9): {"lora": normalised string or None}.
    Merged over the raw block, so a broken stored value (e.g. a number) is replaced by None."""
    return {"lora": lora.block_lora(block)}


def slot_choices(blocks):
    """Sorted slot names used by any block or sub-block (choices of the management tab's slot fields)."""
    return sorted(suggest.slot_counts(blocks))


def api_trace(trace):
    """expand() trace [(parent, sub), ...] -> [{"parent", "sub"}, ...] for POST /promptblocks/preview."""
    return [{"parent": p, "sub": s} for p, s in (trace or [])]
