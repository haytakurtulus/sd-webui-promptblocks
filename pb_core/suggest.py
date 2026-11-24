import difflib

from . import adetailer, bans, parser, subs, weights


def category_counts(blocks):
    # Non-dict entries (hand-edited blocks.json) are skipped.
    counts = {}
    for b in blocks.values():
        if not isinstance(b, dict):
            continue
        c = b.get("category")
        if c:
            counts[c] = counts.get(c, 0) + 1
    return counts


def category_hint(typed, blocks):
    typed = (typed or "").strip()
    if not typed:
        return ""
    counts = category_counts(blocks)
    if typed in counts:
        n = counts[typed]
        return f"Existing category ({n} block{'' if n == 1 else 's'})."

    # Compare lowercased, so "pcharacter" is suggested as "PCharacter":
    # the parser is case-sensitive, so they would be two different categories.
    by_lower = {c.lower(): c for c in counts}
    close = difflib.get_close_matches(typed.lower(), list(by_lower), n=3, cutoff=0.75)
    msg = f"New category `{typed}`."
    if close:
        msg += " Did you mean: " + ", ".join(f"`{by_lower[c]}`" for c in close) + "?"
    return msg


def slot_counts(blocks):
    # {slot: number of blocks + sub-blocks using it}. Broken slot values are ignored (normalised).
    counts = {}
    for b in blocks.values():
        found = [subs.block_slot(b)] + [s["slot"] for s in subs.normalize_subs(b)]
        for slot in found:
            if slot:
                counts[slot] = counts.get(slot, 0) + 1
    return counts


def slot_hint(typed, blocks):
    # "Did you mean" hint for a slot field, like category_hint. "" for an empty field.
    typed = typed.strip() if isinstance(typed, str) else ""
    if not typed:
        return ""
    counts = slot_counts(blocks)
    if typed in counts:
        n = counts[typed]
        return f"Existing slot ({n} use{'' if n == 1 else 's'})."
    by_lower = {s.lower(): s for s in counts}
    close = difflib.get_close_matches(typed.lower(), list(by_lower), n=3, cutoff=0.75)
    msg = f"New slot `{typed}`."
    if close:
        msg += " Did you mean: " + ", ".join(f"`{by_lower[s]}`" for s in close) + "?"
    return msg


def row_slots_hint(slots, blocks):
    # One shared hint line for the sub-block rows' slot fields: only rows with a slot that is not
    # used anywhere yet are listed (existing slots need no hint). "" if nothing to say.
    counts = slot_counts(blocks)
    parts = []
    for i, typed in enumerate(slots, 1):
        typed = typed.strip() if isinstance(typed, str) else ""
        if typed and typed not in counts:
            parts.append(f"Sub-block {i}: " + slot_hint(typed, blocks))
    return " ".join(parts)


def form_hints(category, block_slot, row_slots, blocks):
    # The three hint lines of the management form from its current values (section 23a fix 2):
    # (category hint, block slot hint, shared sub-block rows slot hint).
    return (category_hint(category if isinstance(category, str) else "", blocks),
            slot_hint(block_slot, blocks),
            row_slots_hint(list(row_slots or []), blocks))


def reference_texts(block):
    # Every text of a block that may hold a reference (design notes 33 C): subs.block_texts() (own text,
    # sub-block texts) plus the non-empty ADetailer texts, keyed ("adetailer", tab index) so the key can
    # never equal a sub-block name.
    return subs.block_texts(block) + [((adetailer.FIELD, k), t) for k, t in adetailer.adetailer_texts(block)]


def users_of(blocks, symbol, name, exclude=None):
    # Sorted names of blocks whose text, sub-block texts or ADetailer texts contain the exact token
    # symbol+name (for blocks, ~name.sub and ~name*slot count as a use of name).
    return sorted(
        n for n, b in blocks.items()
        if n != exclude and any(parser.references(t, symbol, name) for _, t in reference_texts(b))
    )


def sub_users(blocks, parent, sub):
    # Sorted names of blocks whose text, sub-block texts or ADetailer texts contain the exact token
    # ~parent.sub. The sub-block's own text is ignored (removing it removes that reference too); other
    # texts of the parent count (also its ADetailer texts), so the parent itself can be listed.
    result = []
    for n, b in blocks.items():
        for sub_name, t in reference_texts(b):
            if n == parent and sub_name == sub:
                continue
            if parser.sub_references(t, parent, sub):
                result.append(n)
                break
    return sorted(result)


def last_active_category_users(blocks, name):
    # Deleting `name` empties the %Category pick pool of its category when it is the last ACTIVE
    # block there (inactive blocks may remain; %Cat stops expanding either way).
    # Returns the blocks (other than `name`) that reference that %Category; [] = no warning.
    # Deleting an inactive block never changes the pool, so it never warns.
    block = blocks.get(name)
    if not isinstance(block, dict) or not weights.is_active(block):
        return []
    cat = block.get("category")
    if not cat:
        return []
    if any(k != name for k in weights.category_pool(blocks, cat)):
        return []
    return users_of(blocks, parser.CATEGORY_SYMBOL, cat, exclude=name)


def delete_warnings(blocks, name):
    # Warning texts shown before deleting `name` (empty list = the block is used nowhere; Delete still asks
    # once, see delete_confirm_message).
    warnings = []
    block_users = users_of(blocks, parser.BLOCK_SYMBOL, name, exclude=name)
    if block_users:
        warnings.append(f"`{parser.BLOCK_SYMBOL}{name}` is used by: {', '.join(block_users)}")

    cat_users = last_active_category_users(blocks, name)
    if cat_users:
        cat = blocks[name].get("category")
        warnings.append(
            f"this is the last active block in `{parser.CATEGORY_SYMBOL}{cat}` "
            f"(it stops expanding), which is used by: {', '.join(cat_users)}"
        )

    # Bans (section 38): a separate line, so a ban is never mistaken for a use in a prompt text.
    ban_users = bans.ban_users(blocks, parser.BLOCK_SYMBOL + name, exclude=name)
    if ban_users:
        warnings.append(f"`{parser.BLOCK_SYMBOL}{name}` is listed in the bans of: {', '.join(ban_users)} "
                        f"(the ban stays and then names no block)")
    cat = blocks[name].get("category") if isinstance(blocks.get(name), dict) else None
    if isinstance(cat, str) and cat and not any(
            k != name and weights.in_category(b, cat) for k, b in blocks.items()):
        cat_ban_users = bans.ban_users(blocks, parser.CATEGORY_SYMBOL + cat, exclude=name)
        if cat_ban_users:
            warnings.append(f"this is the last block in `{parser.CATEGORY_SYMBOL}{cat}`, which is listed in the "
                            f"bans of: {', '.join(cat_ban_users)} (the ban stays and then names no category)")
    return warnings


def delete_confirm_message(blocks, name):
    # First press of Delete (design notes 33 B): every delete asks twice. A used block shows its
    # delete_warnings(), a block used nowhere a plain question.
    warnings = delete_warnings(blocks, name)
    if warnings:
        return "⚠ " + "; ".join(warnings) + ". **Press Delete again to confirm.**"
    return f"⚠ Delete block `{name}`? **Press Delete again to confirm.**"
