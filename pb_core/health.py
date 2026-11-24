"""Health check over all blocks (design notes section 18).

Pure Python, no WebUI / gradio imports. report() is read-only and never raises on JSON-shaped input; it
only reads the blocks dict it is given. thumb_names() is the only function that touches the file system
(it lists storage.THUMB_DIR).

A finding is {"kind": str, "block": str | None, "sub": str | None, "detail": str} (detail is Markdown).
"""

import json
import os
import random

from . import adetailer, bans, lora, parser, storage, subrows, subs, weights

# Kinds in report order, with the human title used by format_report().
KINDS = (
    ("unknown_ref", "Unknown references"),
    ("all_inactive_ref", "References to categories whose blocks are all inactive"),
    ("self_category_ref", "Blocks that call their own category"),
    ("cycle", "Cycles / nesting too deep"),
    # Bans (section 38); unknown ban targets are listed under unknown_ref, broken ban values under ignored_value.
    ("self_ban", "Blocks that ban themselves or their own category"),
    ("mutual_ban", "Mutual bans (the block further left in the prompt wins)"),
    ("ban_empty_pool", "Bans that empty a category pool"),
    ("lora_in_text", "LoRA tags inside Text"),
    ("ignored_value", "Stored values that are ignored"),
    ("orphan_thumb", "Thumbnails without a block"),
    ("bad_block", "Broken blocks"),
)
_KIND_INDEX = {k: i for i, (k, _) in enumerate(KINDS)}

# Seeds of the cycle check: Random(0) as in the save-time check, plus 15 more, so cycles that only happen
# with some random picks are found too. A token whose expansion uses no RNG at all is run once only.
CYCLE_SEEDS = tuple(range(16))

_SHOW_MAX = 40


def _show(value):
    # A stored value as inline Markdown code, JSON-like and shortened. Never raises.
    try:
        s = json.dumps(value, ensure_ascii=False)
    except Exception:
        s = repr(value)
    if len(s) > _SHOW_MAX:
        s = s[:_SHOW_MAX - 1] + "…"
    return "`" + s.replace("`", "'") + "`"


def _code(text):
    return "`" + str(text).replace("`", "'") + "`"


def _finding(kind, block, sub, detail):
    return {"kind": kind, "block": block, "sub": sub, "detail": detail}


def thumb_names(folder=None):
    """Block names that have a thumbnail file (<name>.webp) in `folder` (default storage.THUMB_DIR, read
    at call time), sorted. Missing / unreadable folder -> []."""
    folder = storage.THUMB_DIR if folder is None else folder
    try:
        files = os.listdir(folder)
    except OSError:
        return []
    return sorted(f[:-len(".webp")] for f in files
                  if f.endswith(".webp") and os.path.isfile(os.path.join(folder, f)))


# ---- per-kind checks ----

def _bad_block(name, block):
    # bad_block findings of one block; the block is unusable for every other check if it is not a dict.
    if not isinstance(block, dict):
        return [_finding("bad_block", name, None,
                         f"stored value {_show(block)} is not an object; the block cannot be used")]
    result = []
    if not isinstance(block.get("text"), str):
        what = "missing" if "text" not in block else f"{_show(block.get('text'))} (not text)"
        result.append(_finding("bad_block", name, None, f"`text` is {what}"))
    cat = block.get("category")
    if not (isinstance(cat, str) and parser.is_valid_name(cat)):
        what = "missing" if "category" not in block else f"{_show(cat)}, not a valid name"
        result.append(_finding("bad_block", name, None,
                               f"`category` is {what}; the block is never picked by a valid `%Category`"))
    return result


def _token_text(symbol, name, sub, slot):
    if sub is not None:
        return symbol + name + parser.SUB_SEPARATOR + sub
    if slot is not None:
        return symbol + name + parser.SLOT_DRAW_SEPARATOR + slot
    return symbol + name


def _ref_findings(name, sub_name, text, blocks):
    # unknown_ref / all_inactive_ref findings of one text, scanned statically (no expansion), each
    # distinct token once.
    result, seen = [], set()

    def check(symbol, ref, sub, slot):
        token = _token_text(symbol, ref, sub, slot)
        if token in seen:
            return None
        seen.add(token)
        if symbol == parser.BLOCK_SYMBOL:
            if ref not in blocks:
                result.append(_finding("unknown_ref", name, sub_name,
                                       f"{_code(token)}: no block named {_code(ref)}"))
                return None
            target = blocks[ref]
            if not isinstance(target, dict):
                return None  # reported as bad_block
            if sub is not None and subs.get_sub(target, sub) is None:
                result.append(_finding("unknown_ref", name, sub_name,
                                       f"{_code(token)}: block {_code(ref)} has no sub-block {_code(sub)}"))
            elif slot is not None and not parser.slot_draw_candidates(target, slot):
                result.append(_finding("unknown_ref", name, sub_name,
                                       f"{_code(token)}: block {_code(ref)} has no sub-block in slot "
                                       f"{_code(slot)}"))
            return None
        members = [b for b in blocks.values() if weights.in_category(b, ref)]
        if not members:
            result.append(_finding("unknown_ref", name, sub_name,
                                   f"{_code(token)}: no block has category {_code(ref)}"))
        elif not any(weights.is_active(b) for b in members):
            n = len(members)
            result.append(_finding("all_inactive_ref", name, sub_name,
                                   f"{_code(token)}: {'the' if n == 1 else 'all'} {n} block"
                                   f"{'' if n == 1 else 's'} of category {_code(ref)} "
                                   f"{'is' if n == 1 else 'are'} inactive; the token stays in the prompt"))
        return None

    parser.replace_tokens(text, check)
    return result


def _self_category_findings(name, sub_name, text, block):
    # self_category_ref finding of one text: it contains %C where C is the block's own category, so a
    # %C pick inside the block can choose the block itself (static; the random cycle probe rarely sees
    # it when the category has several blocks). At most one finding per text.
    cat = block.get("category")
    if not (isinstance(cat, str) and parser.is_valid_name(cat)):
        return []
    found = []

    def check(symbol, ref, sub, slot):
        if symbol == parser.CATEGORY_SYMBOL and weights.in_category(block, ref):
            found.append(True)
        return None

    parser.replace_tokens(text, check)
    if not found:
        return []
    token = _code(parser.CATEGORY_SYMBOL + cat)
    detail = (f"{token} is this block's own category: a pick of {token} can choose this block again, "
              f"which calls {token} again, and so on; only the nesting depth limit "
              f"({parser.MAX_DEPTH} levels) stops it (an error instead of a prompt)")
    if not weights.is_active(block):
        detail += "; the block is inactive now, so it cannot pick itself until it is activated"
    return [_finding("self_category_ref", name, sub_name, detail)]


def _adetailer_ref_findings(name, block, blocks):
    # unknown_ref / all_inactive_ref findings of the block's ADetailer texts (section 31a), labelled
    # with the tab. No self-category / cycle check: an ADetailer text is never added recursively, and
    # the blocks it reaches are checked on their own.
    result = []
    for k, text in adetailer.adetailer_texts(block):
        for f in _ref_findings(name, None, text, blocks):
            f["detail"] = f"ADetailer {adetailer.tab_label(k)}: " + f["detail"]
            result.append(f)
    return result


_BAN_KINDS = {"unknown": "unknown_ref", "self": "self_ban", "mutual": "mutual_ban", "empty_pool": "ban_empty_pool"}


def _ban_findings(name, block, blocks):
    # Section 38: static findings of the block's usable bans (bans.problems with its stored category).
    # A mutual ban is listed once per pair, at the block whose name sorts first.
    found = bans.block_bans(block)
    if not found:
        return []
    cat = block.get("category")
    others = {n: b for n, b in blocks.items() if isinstance(n, str)}
    result = []
    for kind, text in bans.problems(others, name, cat if isinstance(cat, str) else "", found):
        if kind == "mutual":
            continue
        result.append(_finding(_BAN_KINDS[kind], name, None, "Bans: " + text))
    for other in bans.mutual(others, name, block, found):
        if str(other) < str(name):
            continue
        result.append(_finding("mutual_ban", name, None,
                               f"{_code(parser.BLOCK_SYMBOL + name)} and {_code(parser.BLOCK_SYMBOL + other)} "
                               f"ban each other; in a prompt with both, the one further left wins"))
    return result


def _cycle_finding(name, block, usable):
    # The first token of ~name / ~name.sub that raises BlockCycleError with any of CYCLE_SEEDS, or None.
    for token in subrows.cycle_tokens(name, block):
        for seed in CYCLE_SEEDS:
            rng = random.Random(seed)
            before = rng.getstate()
            try:
                parser.expand(token, usable, rng, apply_bans=False)
            except parser.BlockCycleError:
                detail = (f"{_code(token)} nests deeper than {parser.MAX_DEPTH} levels "
                          f"(a block that reaches itself?)")
                if seed != 0:
                    detail += f"; only with some random picks (check seed {seed})"
                return _finding("cycle", name, None, detail)
            except Exception:
                break  # broken data somewhere else; reported by the other checks
            if rng.getstate() == before:
                break  # no RNG used: every seed gives the same result
    return None


def _lora_finding(name, block):
    _, tags = lora.split_lora_tags(block.get("text"))
    if not tags:
        return None
    return _finding("lora_in_text", name, None,
                    "Text contains " + ", ".join(_code(t) for t in tags)
                    + "; use *Move LoRA tags* (under *More actions*) to move them to the LoRA box")


def _is_set(block, key):
    # A key that is present with a value other than None / "" (those mean "not set", same as missing).
    return key in block and block[key] is not None and block[key] != ""


def _ignored_findings(name, block):
    result = []

    def add(sub, detail):
        result.append(_finding("ignored_value", name, sub, detail))

    if "weight" in block:
        _, err = weights.validate_weight(block["weight"])
        if err:
            add(None, f"weight {_show(block['weight'])} is ignored: {err} "
                      f"{weights.DEFAULT_WEIGHT} is used instead")
    if "active" in block and not isinstance(block["active"], bool):
        add(None, f"active {_show(block['active'])} is not true / false; the block counts as active")
    if _is_set(block, "slot") and subs.block_slot(block) is None:
        add(None, f"slot {_show(block['slot'])} is not a valid name; no block slot is used")
    if _is_set(block, "lora") and not isinstance(block["lora"], str):
        add(None, f"lora {_show(block['lora'])} is not text; no LoRA is used")
    for detail in adetailer.ignored_details(block, _show):
        add(None, detail)
    for detail in bans.ignored_details(block, _show):
        add(None, detail)

    raw = block.get("subs")
    if raw is None:
        return result
    if not isinstance(raw, list):
        add(None, f"subs {_show(raw)} is not a list; the block has no sub-blocks")
        return result
    # Same rules and order as subs.normalize_subs.
    kept, seen = 0, set()
    for i, entry in enumerate(raw, 1):
        label = f"sub-block entry #{i}"
        ename = entry.get("name") if isinstance(entry, dict) else None
        valid_name = isinstance(ename, str) and parser.is_valid_name(ename)
        sub = ename if valid_name else None
        if kept >= subs.MAX_SUBS:
            add(sub, f"{label} is dropped: only the first {subs.MAX_SUBS} usable sub-blocks are used")
            continue
        if not isinstance(entry, dict):
            add(None, f"{label} {_show(entry)} is not an object; dropped")
            continue
        if not valid_name:
            add(None, f"{label}: name {_show(ename)} is not a valid name; dropped")
            continue
        if ename in seen:
            add(sub, f"{label}: duplicate name {_code(ename)}; dropped (the first one is used)")
            continue
        if not isinstance(entry.get("text"), str):
            what = "missing" if "text" not in entry else f"{_show(entry.get('text'))} (not text)"
            add(sub, f"{label}: text is {what}; dropped")
            continue
        seen.add(ename)
        kept += 1
        mode = entry.get("mode")
        if mode is not None and not (isinstance(mode, str) and mode.strip().lower() in subs.MODES):
            add(sub, f"mode {_show(mode)} is not include / exclude / random; "
                     f"{subs.DEFAULT_MODE} is used")
        if _is_set(entry, "slot") and not (isinstance(entry["slot"], str)
                                           and parser.is_valid_name(entry["slot"])):
            add(sub, f"slot {_show(entry['slot'])} is not a valid name; no slot is used")
        if entry.get("chance") is not None and subs.sub_chance(entry) != entry.get("chance"):
            add(sub, f"chance {_show(entry['chance'])} is not a whole number "
                     f"{subs.MIN_CHANCE}..{subs.MAX_CHANCE}; {subs.DEFAULT_CHANCE} is used")
    return result


def report(blocks, thumb_names=None):
    """All findings for `blocks` (the "blocks" dict of blocks.json) and the given thumbnail names
    (see thumb_names(); None = do not check thumbnails). Sorted by kind (KINDS order), then block name.
    Read-only; never raises on JSON-shaped input."""
    findings = []
    if not isinstance(blocks, dict):
        findings.append(_finding("bad_block", None, None,
                                 f"the blocks data {_show(blocks)} is not an object; nothing can be used"))
        blocks = {}
    names = sorted(blocks, key=str)
    # Blocks that expand() can handle without crashing (dict with a text string).
    usable = {n: b for n, b in blocks.items() if isinstance(b, dict) and isinstance(b.get("text"), str)}

    for name in names:
        block = blocks[name]
        findings.extend(_bad_block(name, block))
        if not isinstance(block, dict):
            continue
        for sub_name, text in subs.block_texts(block):
            findings.extend(_ref_findings(name, sub_name, text, blocks))
            findings.extend(_self_category_findings(name, sub_name, text, block))
        findings.extend(_adetailer_ref_findings(name, block, blocks))
        findings.extend(_ban_findings(name, block, blocks))
        if name in usable:
            f = _cycle_finding(name, block, usable)
            if f:
                findings.append(f)
        f = _lora_finding(name, block)
        if f:
            findings.append(f)
        findings.extend(_ignored_findings(name, block))

    if thumb_names is not None:
        try:
            thumbs = sorted({t for t in thumb_names if isinstance(t, str)})
        except TypeError:
            thumbs = []
        for t in thumbs:
            if t not in blocks:
                findings.append(_finding("orphan_thumb", None, None,
                                         f"{_code(t + '.webp')} has no block named {_code(t)}"))

    findings.sort(key=lambda f: (_KIND_INDEX[f["kind"]], "" if f["block"] is None else str(f["block"])))
    return findings


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def _affected(findings):
    return {f["block"] for f in findings if f["block"] is not None}


def summary_line(findings):
    """One line for the status bar: "Health check: 3 problems in 2 blocks" / "Health check: no problems"."""
    if not findings:
        return "Health check: no problems"
    line = f"Health check: {_plural(len(findings), 'problem')}"
    affected = _affected(findings)
    if affected:
        line += f" in {_plural(len(affected), 'block')}"
    return line


def format_report(findings, block_count):
    """Markdown report: one group per kind (KINDS order, title + count), one list item per finding
    (block name as code, ".sub" when the finding is about a sub-block, then the detail).
    "No problems found in N blocks." when there are no findings."""
    if not findings:
        return f"No problems found in {_plural(block_count, 'block')}."
    lines = [f"**{summary_line(findings)}** (checked {_plural(block_count, 'block')})"]
    for kind, title in KINDS:
        group = [f for f in findings if f["kind"] == kind]
        if not group:
            continue
        lines.append("")
        lines.append(f"**{title}** ({len(group)})")
        for f in group:
            where = ""
            if f["block"] is not None:
                label = str(f["block"])
                if f["sub"] is not None:
                    label += parser.SUB_SEPARATOR + str(f["sub"])
                where = _code(label) + ": "
            lines.append(f"- {where}{f['detail']}")
    return "\n".join(lines)
