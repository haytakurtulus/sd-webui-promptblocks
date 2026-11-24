"""Bulk edits across many blocks (design notes section 19): category rename / merge, the
"Enable shown" / "Disable shown" active toggle of the block browser and "Set sub-blocks of shown blocks"
(section 36 B).

Pure Python, no WebUI / gradio imports. Every function is non-mutating: the input dict and its block
dicts are never changed; changed blocks are new dicts.
"""

from . import guard, parser, subs, weights

# Initial choice (and fallback) of the "Set sub-blocks of shown blocks" mode dropdown (section 36 B). It stays
# Random although new form rows start as Include again (section 37 A).
BULK_INITIAL_MODE = "random"


def _plural(n, word="block"):
    return f"{n} {word}{'' if n == 1 else 's'}"


def category_size(blocks, category):
    """Number of blocks (active or not) whose category is `category`."""
    return sum(1 for b in blocks.values() if weights.in_category(b, category))


def rename_category(blocks, old, new):
    """Move every block of category `old` to `new` and rewrite `%old` -> `%new` in every block text,
    sub-block text, ADetailer text and ban list (section 38) (LoRA fields are literal and stay untouched; `%oldLonger` is another category and
    stays untouched). If `new` already has blocks, the two categories are merged.

    Returns (new_blocks, moved_names, rewritten_names), both name lists sorted.
    `old == new`, or `old` without blocks -> (unchanged copy, [], []).
    """
    if old == new or not category_size(blocks, old):
        return dict(blocks), [], []
    new_blocks, rewritten = subs._rewrite_all(
        blocks, lambda t: parser.rename_token(t, parser.CATEGORY_SYMBOL, old, new))
    moved = []
    for n, b in new_blocks.items():
        if weights.in_category(b, old):
            new_blocks[n] = dict(b, category=new)
            moved.append(n)
    return new_blocks, sorted(moved), rewritten


def check_category_rename(blocks, old, new):
    """Check a category rename before doing it. `old` / `new` are stripped.

    Returns {"old", "new", "error": message or None, "moved": blocks in old,
             "existing": blocks already in new, "merge": True if new already has blocks,
             "warning": confirm text for a merge or None}.
    """
    old = old.strip() if isinstance(old, str) else ""
    new = new.strip() if isinstance(new, str) else ""
    result = {"old": old, "new": new, "error": None, "moved": 0, "existing": 0, "merge": False,
              "warning": None}
    if not old:
        result["error"] = "Select a category in *From* first."
        return result
    moved = category_size(blocks, old)
    if not moved:
        result["error"] = f"No blocks in category `{old}`."
        return result
    result["moved"] = moved
    if not parser.is_valid_name(new):
        result["error"] = f"Invalid new category: `{new}` (must start with a letter; letters, digits, _)"
        return result
    if new == old:
        result["error"] = f"`{old}` already has that name."
        return result
    existing = category_size(blocks, new)
    result["existing"] = existing
    if existing:
        result["merge"] = True
        result["warning"] = (f"⚠ `{old}` ({_plural(moved)}) will be merged into `{new}` "
                             f"({_plural(existing)}). **Press Rename category again to confirm.**")
    return result


def set_active(blocks, names, active):
    """Set the active state of the blocks in `names` (only those).

    Activating removes the "active" key (old JSON shape), deactivating stores "active": False.
    Names that do not exist (or are not dict blocks) and blocks that already have that state
    (weights.is_active) are skipped. Duplicate names count once.
    Returns (new_blocks, changed_names) with changed_names in the order of `names`.
    """
    active = bool(active)
    new_blocks = dict(blocks)
    changed, seen = [], set()
    for n in names or []:
        if n in seen:
            continue
        seen.add(n)
        b = blocks.get(n)
        if not isinstance(b, dict) or weights.is_active(b) == active:
            continue
        b = dict(b)
        if active:
            b.pop("active", None)
        else:
            b["active"] = False
        new_blocks[n] = b
        changed.append(n)
    return new_blocks, changed


def capped_more(shown, total, limit):
    """Number of matching blocks that the capped gallery did not list: total - shown when the list
    hit `limit` (the tile cap), else 0 (an uncapped list shows every match)."""
    if shown < limit or total <= shown:
        return 0
    return total - shown


def active_status(active, changed, already, shown=0, more=0):
    """Status line of "Enable shown" / "Disable shown": `changed` blocks changed, `already` blocks
    already had that state. "Nothing to change." when changed is 0. `more` > 0 (matching blocks the
    capped gallery did not list; `shown` = number listed) adds a sentence saying only those were
    changed / checked."""
    if not changed:
        msg = "Nothing to change."
    else:
        msg = f"{'Enabled' if active else 'Disabled'} {_plural(changed)}"
        if already:
            state = "active" if active else "inactive"
            msg += f" ({already} {'was' if already == 1 else 'were'} already {state})"
        msg += "."
    if more > 0:
        verb = "were changed" if changed else "were checked"
        msg += (f" Only the {_plural(shown)} shown {verb}; {more} more "
                f"match{'es' if more == 1 else ''} the filter.")
    return msg


def set_sub_modes(blocks, names, mode):
    """Section 36 B: set the mode of every usable sub-block (subs.usable_entries, i.e. the ones
    normalize_subs uses) of the blocks in `names` to `mode` ("include" / "exclude" / "random",
    case-insensitive; anything else raises ValueError).

    Only "mode" changes: name, text, slot and chance stay; stored entries are copied as they are (no
    normalisation), entries that are not usable are left untouched. A sub-block whose usable mode
    already is `mode` (also a stored "Random", or a missing mode for "include") is not changed.
    Names that do not exist (or are not dict blocks) are skipped; duplicate names count once.
    Returns (new_blocks, changed_blocks, changed_sub_count), changed_blocks in the order of `names`.
    """
    target = mode.strip().lower() if isinstance(mode, str) else None
    if target not in subs.MODES:
        raise ValueError(f"invalid mode {mode!r}")
    new_blocks = dict(blocks)
    changed, count, seen = [], 0, set()
    for n in names or []:
        if n in seen:
            continue
        seen.add(n)
        b = blocks.get(n)
        if not isinstance(b, dict):
            continue
        raw = b.get("subs")
        todo = [i for i, entry in subs.usable_entries(raw) if subs._norm_mode(entry.get("mode")) != target]
        if not todo:
            continue
        new_raw = [dict(e) if isinstance(e, dict) else e for e in raw]
        for i in todo:
            new_raw[i]["mode"] = target
        new_blocks[n] = dict(b, subs=new_raw)
        changed.append(n)
        count += len(todo)
    return new_blocks, changed, count


def sub_modes_key(blocks, changed, mode):
    """Confirm key of "Set sub-blocks of shown blocks" (section 23a pattern): the blocks that would
    change, the mode and guard.data_key of the saved data the warning was about. A second press is a
    confirmation only while all three are unchanged, so no event has to reset it."""
    return repr((list(changed), mode, guard.data_key(blocks)))


def mode_label(mode):
    """"Include" / "Exclude" / "Random" for a mode value (other values as given)."""
    return mode.strip().capitalize() if isinstance(mode, str) else str(mode)


def _capped_note(shown, more, verb):
    if more <= 0:
        return ""
    return (f" Only the {_plural(shown)} shown {verb}; {more} more "
            f"match{'es' if more == 1 else ''} the filter.")


def sub_modes_confirm(mode, sub_count, block_count, shown=0, more=0):
    """First-press warning of "Set sub-blocks of shown blocks" (section 36 B)."""
    return (f"⚠ Set {_plural(sub_count, 'sub-block')} in {_plural(block_count)} to {mode_label(mode)}? "
            f"**Press Set sub-blocks of shown blocks again to confirm.**"
            + _capped_note(shown, more, "would be changed"))


def sub_modes_status(mode, sub_count, block_count, shown=0, more=0):
    """Status line after the second press (sub_count > 0) or when nothing has to change (sub_count 0).
    `shown` = number of blocks listed in the browser, `more` = matching blocks the capped gallery did not
    list (see capped_more)."""
    if not sub_count:
        if not shown:
            return "No blocks are shown in the browser; nothing to change."
        return (f"Nothing to change: no sub-block of the {_plural(shown)} shown needs to become "
                f"{mode_label(mode)}." + _capped_note(shown, more, "were checked"))
    return (f"Set {_plural(sub_count, 'sub-block')} in {_plural(block_count)} to {mode_label(mode)}."
            + _capped_note(shown, more, "were changed"))
