"""Sub-blocks (design notes section 3): normalisation, save-time validation and block-level text helpers.
Also the block-level slot helpers (design notes section 4).

Pure Python, no WebUI / gradio imports. Stored shape inside a block:
    "subs": [ {"name": "outfit", "text": "...", "mode": "include", "slot": null}, ... ]
Missing "subs" = [], missing "mode" = "include", missing "slot" = None.
Block-level "slot" is stored only when set (key removed when empty).
Optional sub-block "chance" (design notes section 14): integer percent 1..100 for mode "random", stored
only when it differs from DEFAULT_CHANCE (50). Missing or broken values behave as 50.
"""

import math

MAX_SUBS = 6
MODES = ("include", "exclude", "random")
# Mode of STORED data whose "mode" is missing or broken (older blocks.json files load unchanged).
DEFAULT_MODE = "include"
# Mode of a NEW / blank sub-block row in the management form (design notes sections 36 A, 37 A): the single
# place for the blank-row mode.
NEW_ROW_MODE = "include"
DEFAULT_CHANCE = 50
MIN_CHANCE, MAX_CHANCE = 1, 100


def _is_valid_name(s):
    # Lazy import: parser imports this module, so a top-level import would be circular.
    from .parser import is_valid_name
    return isinstance(s, str) and is_valid_name(s)


def _norm_mode(value):
    # Missing or broken mode behaves as "include" (same rule as broken weights -> 1). Case-insensitive.
    if isinstance(value, str) and value.strip().lower() in MODES:
        return value.strip().lower()
    return DEFAULT_MODE


def _norm_slot(value):
    return value if _is_valid_name(value) else None


def _whole_chance(value):
    # int 1..100 for an int or integral float in range (bool excluded), else None. Never raises.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        value = int(value)
    return value if MIN_CHANCE <= value <= MAX_CHANCE else None


def sub_chance(sub):
    """Chance in percent (int 1..100) of a sub-block dict (stored or normalised), section 14.
    Missing or broken values (non-number, bool, fraction, NaN, < 1, > 100) give DEFAULT_CHANCE.
    Never raises."""
    if not isinstance(sub, dict):
        return DEFAULT_CHANCE
    c = _whole_chance(sub.get("chance"))
    return DEFAULT_CHANCE if c is None else c


def validate_chance(value):
    """Save-time check of a sub-block chance field. None / "" / whitespace = DEFAULT_CHANCE.
    Accepts ints 1..100 and integral floats (Gradio Number gives floats).
    Returns (int, None) or (None, error_message)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return DEFAULT_CHANCE, None
    c = _whole_chance(value)
    if c is None:
        return None, f"invalid chance `{value}` (whole number {MIN_CHANCE}..{MAX_CHANCE})"
    return c, None


def add_chance(entry, chance):
    # Adds "chance" only when it differs from the default (old dict / JSON shape otherwise).
    if chance != DEFAULT_CHANCE:
        entry["chance"] = chance
    return entry


def validate_slot(value):
    """Save-time check of a slot field (block or sub-block). None / "" / whitespace = no slot.
    Returns (slot_or_None, None) or (None, error_message)."""
    if value is None:
        return None, None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None, None
    if not _is_valid_name(value):
        return None, f"invalid slot `{value}` (must start with a letter; letters, digits, _)"
    return value, None


def block_slot(block):
    """Block-level slot (design notes section 4): the stored "slot" if it is a valid name, else None.
    Never raises; missing or broken values mean "no slot"."""
    if not isinstance(block, dict):
        return None
    return _norm_slot(block.get("slot"))


def set_block_slot(block, slot):
    """New block dict with the block-level "slot" set; None / "" removes the key (old JSON shape).
    Raises ValueError for an invalid slot (validate with validate_slot first)."""
    slot, err = validate_slot(slot)
    if err:
        raise ValueError(err)
    block = dict(block)
    if slot is None:
        block.pop("slot", None)
    else:
        block["slot"] = slot
    return block


def normalize_subs(block):
    """Usable sub-blocks of a stored block, as a new list of
    {"name": str, "text": str, "mode": "include"|"exclude"|"random", "slot": str|None}
    plus "chance": int only when the usable chance differs from DEFAULT_CHANCE (read it with sub_chance).

    Never raises. Skipped: non-dict entries, entries whose name is not a valid name, later duplicates
    of a name, entries whose text is not a string; at most MAX_SUBS entries are kept (the first ones).
    """
    raw = block.get("subs") if isinstance(block, dict) else None
    return [add_chance({"name": entry["name"], "text": entry["text"], "mode": _norm_mode(entry.get("mode")),
                        "slot": _norm_slot(entry.get("slot"))}, sub_chance(entry))
            for _, entry in usable_entries(raw)]


def usable_entries(raw):
    """[(index, entry), ...] of the stored sub-block list `raw` that normalize_subs uses, in stored order
    (same skipping rules; at most MAX_SUBS). `entry` is the stored dict itself. Never raises."""
    if not isinstance(raw, list):
        return []
    result, seen = [], set()
    for i, entry in enumerate(raw):
        if len(result) >= MAX_SUBS:
            break
        if not isinstance(entry, dict):
            continue
        name, text = entry.get("name"), entry.get("text")
        if not _is_valid_name(name) or name in seen or not isinstance(text, str):
            continue
        seen.add(name)
        result.append((i, entry))
    return result


def get_sub(block, sub):
    """The normalised sub-block dict named `sub` of `block`, or None."""
    for s in normalize_subs(block):
        if s["name"] == sub:
            return s
    return None


def sub_names(block):
    """Names of the usable sub-blocks of `block`, in stored order."""
    return [s["name"] for s in normalize_subs(block)]


def validate_subs(rows):
    """Save-time check of a sub-block list (e.g. the rows of the management tab).

    `rows`: iterable of dicts with "name", "text", optional "mode" (default "include") and
    optional "slot" (None / "" = no slot) and optional "chance" (None / "" = 50, see validate_chance).
    Name and text are stripped. A row whose name and text are both empty is "no sub-block" and dropped.
    Returns (cleaned_list, None) or (None, error_message). cleaned_list items are
    {"name", "text", "mode", "slot"} with slot None when unset, plus "chance" (int) only when it is not
    DEFAULT_CHANCE (kept for every mode); [] means "no subs" (see set_subs).
    """
    if rows is None:
        return [], None
    cleaned, seen = [], set()
    for i, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            return None, f"Sub-block {i}: invalid data."
        name = row.get("name")
        text = row.get("text")
        name = name.strip() if isinstance(name, str) else ""
        text = text.strip() if isinstance(text, str) else ""
        if not name and not text:
            continue
        if not _is_valid_name(name):
            return None, (f"Sub-block {i}: invalid name `{name}` "
                          "(must start with a letter; letters, digits, _)")
        if name in seen:
            return None, f"Sub-block {i}: duplicate name `{name}`."
        if not text:
            return None, f"Sub-block `{name}`: text cannot be empty."
        mode = row.get("mode", DEFAULT_MODE)
        if mode is None:
            mode = DEFAULT_MODE
        if not isinstance(mode, str) or mode.strip().lower() not in MODES:
            return None, f"Sub-block `{name}`: invalid mode `{mode}` (include / exclude / random)."
        mode = mode.strip().lower()
        slot, serr = validate_slot(row.get("slot"))
        if serr:
            return None, f"Sub-block `{name}`: {serr}."
        chance, cerr = validate_chance(row.get("chance"))
        if cerr:
            return None, f"Sub-block `{name}`: {cerr}."
        seen.add(name)
        cleaned.append(add_chance({"name": name, "text": text, "mode": mode, "slot": slot}, chance))
    if len(cleaned) > MAX_SUBS:
        return None, f"A block can have at most {MAX_SUBS} sub-blocks."
    return cleaned, None


def set_subs(block, subs):
    """New block dict with "subs" set to `subs`; an empty list removes the key (old JSON shape)."""
    block = dict(block)
    if subs:
        block["subs"] = [dict(s) for s in subs]
    else:
        block.pop("subs", None)
    return block


def block_texts(block):
    """All texts of a block that may contain tokens: [(None, text), (sub_name, sub_text), ...].
    The block's own text comes first; sub-blocks are the normalised (usable) ones."""
    if not isinstance(block, dict):
        return []
    result = []
    text = block.get("text", "")
    result.append((None, text if isinstance(text, str) else ""))
    result.extend((s["name"], s["text"]) for s in normalize_subs(block))
    return result


def rewrite_block_texts(block, fn):
    """Apply fn(text) -> text to the block's own text, to the text of every stored sub-block entry
    that has a string text, to every string entry of the stored ADetailer texts (section 31a) and to
    every string entry of the stored bans (section 38; a rewrite that makes two bans equal keeps one).
    Returns (new_block, changed). The input is not modified; stored sub entries are copied as they are
    (no normalisation), so unrelated hand-edited data is kept."""
    new = dict(block)
    changed = False
    text = block.get("text")
    if isinstance(text, str):
        t = fn(text)
        if t != text:
            new["text"] = t
            changed = True
    raw = block.get("subs")
    if isinstance(raw, list):
        new_subs = []
        for entry in raw:
            if isinstance(entry, dict) and isinstance(entry.get("text"), str):
                t = fn(entry["text"])
                if t != entry["text"]:
                    entry = dict(entry, text=t)
                    changed = True
                else:
                    entry = dict(entry)
            new_subs.append(entry)
        new["subs"] = new_subs
    from .adetailer import FIELD, rewrite_texts  # lazy: adetailer imports parser, which imports us
    ad, ad_changed = rewrite_texts(block, fn)
    if ad is not None:
        new[FIELD] = ad
        changed = changed or ad_changed
    from . import bans  # lazy, same reason
    banned, bans_changed = bans.rewrite(block, fn)
    if banned is not None:
        new[bans.FIELD] = banned
        changed = changed or bans_changed
    return new, changed


def _rewrite_all(blocks, fn):
    # (new_blocks, sorted names of blocks whose text, sub texts, ADetailer texts or bans changed). Input is not
    # modified.
    new_blocks, updated = {}, []
    for n, b in blocks.items():
        if isinstance(b, dict):
            b, changed = rewrite_block_texts(b, fn)
            if changed:
                updated.append(n)
        new_blocks[n] = b
    return new_blocks, sorted(updated)


def rename_block_refs(blocks, old, new):
    """Rewrite ~old, ~old.sub and ~old*slot to ~new / ~new.sub / ~new*slot in every block text,
    sub-block text and ADetailer text, and ~old -> ~new in every block's bans (section 38).
    Does not move the block itself. Returns (new_blocks, sorted names of changed blocks)."""
    from .parser import BLOCK_SYMBOL, rename_token
    return _rewrite_all(blocks, lambda t: rename_token(t, BLOCK_SYMBOL, old, new))
