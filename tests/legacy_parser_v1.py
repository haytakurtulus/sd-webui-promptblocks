# Verbatim copy of pb_core/parser.py as of commit 79e3a58 (before design notes 38 step 2), only the
# relative imports made absolute. Test support for the bans fast-path proof (tests/test_bans_expand.py):
# without reachable bans, the new expand() must give the same output and RNG use as this one. Never edit.
import re

from pb_core.lora import block_lora
from pb_core.subs import DEFAULT_CHANCE, block_slot, get_sub, normalize_subs, sub_chance
from pb_core.weights import block_weight, category_pool, in_category, is_active

BLOCK_SYMBOL = "~"
CATEGORY_SYMBOL = "%"
SUB_SEPARATOR = "."
SLOT_DRAW_SEPARATOR = "*"
MAX_DEPTH = 5
NAME_PATTERN = r"[A-Za-z][A-Za-z0-9_]*"
SUB_JOINER = ", "

# ~name, ~name.sub, ~name*slot or %Category. The ".sub" / "*slot" part only belongs to the token when a
# valid name follows the separator (so "~saber." / "~saber*" is block saber + a literal "." / "*").
# A token has at most one of the two parts: "~a.b*c" is ~a.b + literal "*c", "~a*b.c" is ~a*b + ".c".
# %Category never takes a ".sub" or "*slot" part.
# Groups: 1 = "~", 2 = block name, 3 = sub name (or None), 4 = slot name (or None),
#         5 = "%", 6 = category name.
_TOKEN = re.compile(
    "(" + re.escape(BLOCK_SYMBOL) + ")(" + NAME_PATTERN + ")"
    "(?:" + re.escape(SUB_SEPARATOR) + "(" + NAME_PATTERN + ")"
    "|" + re.escape(SLOT_DRAW_SEPARATOR) + "(" + NAME_PATTERN + "))?"
    "|(" + re.escape(CATEGORY_SYMBOL) + ")(" + NAME_PATTERN + ")"
)


def _parts(m):
    # (symbol, name, sub) of a _TOKEN match; sub is None for ~name, ~name*slot and %Category.
    # The slot part of ~name*slot is read with _slot_part().
    if m.group(1):
        return m.group(1), m.group(2), m.group(3)
    return m.group(5), m.group(6), None


def _slot_part(m):
    # Slot name of a ~name*slot match (section 10), else None.
    return m.group(4) if m.group(1) else None


def slot_draw_candidates(block, slot):
    """Names of the usable sub-blocks of `block` whose slot is `slot`, in stored order, regardless of
    their mode (section 10). [] if none."""
    return [s["name"] for s in normalize_subs(block) if s["slot"] == slot]


def is_valid_name(s):
    return re.fullmatch(NAME_PATTERN, s) is not None


def category_error(c):
    """Save / create message for a stripped Category value, or None when it is valid (design notes 33 D)."""
    if not c:
        return "Category is empty."
    if not is_valid_name(c):
        return f"Invalid category: `{c}` (must start with a letter; letters, digits, _)"
    return None


class BlockCycleError(Exception):
    pass


def _pick(pool, blocks, rng):
    # Equal weights -> rng.choice exactly as before weights existed, so old seeds keep their picks.
    weights = [block_weight(blocks[k]) for k in pool]
    if all(w == weights[0] for w in weights):
        return rng.choice(pool)
    return rng.choices(pool, weights=weights, k=1)[0]


def slot_occupiers(prompt, blocks):
    """Who occupies each slot in `prompt` (design notes section 4, Rule 1 + own-slot exception).
    Returns {slot: set of occupiers}; an occupier is the tuple (name, None) for an explicit ~name call
    whose block has a slot, (parent, sub) for an explicit ~parent.sub call whose sub-block has one, or
    (parent, "*slot") for a ~parent*slot slot draw (section 10) that has at least one candidate (sub
    names cannot contain "*", so this occupier never equals a (parent, sub) or (parent, None) one).
    %Category tokens and unknown tokens never occupy a slot. Only the given string is scanned (no
    nested block texts)."""
    result = {}
    for m in _TOKEN.finditer(prompt):
        symbol, name, sub = _parts(m)
        if symbol != BLOCK_SYMBOL:
            continue
        block = blocks.get(name)
        if not isinstance(block, dict):
            continue
        draw = _slot_part(m)
        if draw is not None:
            if slot_draw_candidates(block, draw):
                result.setdefault(draw, set()).add((name, SLOT_DRAW_SEPARATOR + draw))
            continue
        if sub is None:
            slot = block_slot(block)
        else:
            s = get_sub(block, sub)
            slot = s["slot"] if s is not None else None
        if slot is not None:
            result.setdefault(slot, set()).add((name, sub))
    return result


def occupied_slots(prompt, blocks):
    """Slots occupied by explicit calls in `prompt` (design notes section 4, Rule 1): the slot of every
    ~block whose block has one, of every ~parent.sub whose sub-block has one, and the slot of every
    resolvable ~parent*slot slot draw (section 10). %Category tokens and
    unknown tokens never occupy a slot. Only the given string is scanned (no nested block texts).
    Returns a set of slot names (the own-slot exception is not applied here)."""
    return set(slot_occupiers(prompt, blocks))


def _occupied_for(name, occupied):
    # Slots occupied for block `name`. A plain set (explicit `occupied` argument) applies to every block.
    # A dict from slot_occupiers(): a slot counts only if some occupier is not the block-level ~name
    # call itself (own-slot exception).
    if not isinstance(occupied, dict):
        return occupied
    own = (name, None)
    return {slot for slot, who in occupied.items() if any(o != own for o in who)}


def _random_wins(sub, rng):
    # The one draw of a Random sub-block (section 3 / 4 Phase A): rng.random() < chance / 100
    # (section 14). Chance 50 gives exactly rng.random() < 0.5, so default subs keep every old result.
    return rng.random() < sub_chance(sub) / 100


def _choose_slotted(sub_list, occupied, rng):
    # Phase A + slot choice (Rule 2). Returns the names of the slotted sub-blocks to add.
    # List order: occupied slot -> skipped, no draw; include -> candidate; exclude -> never;
    # random -> one draw, candidate if it wins. Then per slot (order of first appearance):
    # 1 candidate -> it, no RNG; 2+ -> rng.choice. No slotted subs -> no RNG at all.
    pools = {}
    for s in sub_list:
        slot = s["slot"]
        if slot is None:
            continue
        pool = pools.setdefault(slot, [])
        if slot in occupied or s["mode"] == "exclude":
            continue
        if s["mode"] == "random" and not _random_wins(s, rng):
            continue
        pool.append(s["name"])
    chosen = set()
    for pool in pools.values():
        if len(pool) == 1:
            chosen.add(pool[0])
        elif len(pool) > 1:
            chosen.add(rng.choice(pool))
    return chosen


def _claim_lora(name, block, added):
    # Section 9: the block's LoRA text if it has one and it was not added yet in this top-level expand()
    # call (then it is marked as added), else None. Claimed when an insertion of the block STARTS, so for
    # nested insertions of the same block the outermost one carries it. No RNG.
    # `added` is None when LoRA insertion is off for this call (section 13, negative prompts).
    if added is None:
        return None
    lora = block_lora(block)
    if lora is None or name in added:
        return None
    added.add(name)
    return lora


def _append_lora(text, lora):
    # Literal append with the joiner; an empty insertion gives just the LoRA (no leading ", ").
    if lora is None:
        return text
    return text + SUB_JOINER + lora if text.strip() else lora


def _record_use(uses, name, via, depth, **extra):
    # Section 31a rule 1: one entry per block use, in the order the insertions START (outer before
    # inner). "Used" is the LoRA rule: any part of the block is inserted. Never touches the RNG.
    if uses is not None:
        uses.append({"block": name, "via": via, "depth": depth, **extra})


def _expand_block(name, block, blocks, rng, depth, trace, occupied, added, uses=None, forced=None):
    # Parent text first (all its RNG use), then slotted sub-blocks are chosen (Phase A, see
    # _choose_slotted), then all sub-blocks in stored order (Phase B): a slot-less sub behaves as in
    # section 3 (Include/Exclude use no RNG; Random draws rng.random() < chance / 100, section 14); a
    # chosen slotted sub is expanded at its position. A block without slotted subs consumes exactly the RNG it did before
    # slots existed; a block without sub-blocks returns exactly its expanded text.
    # The block's LoRA (section 9) is appended last, after the text and the automatic sub-blocks.
    lora = _claim_lora(name, block, added)
    own = block.get("text")  # a missing / non-string text (hand-edited data) counts as ""
    text = _expand(own if isinstance(own, str) else "", blocks, rng, depth + 1, trace, occupied, added,
                   uses=uses, forced=forced)
    sub_list = normalize_subs(block)
    chosen = _choose_slotted(sub_list, _occupied_for(name, occupied), rng)
    parts = [text]
    for s in sub_list:
        if s["slot"] is not None:
            if s["name"] not in chosen:
                continue
        elif s["mode"] == "exclude":
            continue
        elif s["mode"] == "random" and not _random_wins(s, rng):
            continue
        if trace is not None:
            trace.append((name, s["name"]))
        parts.append(_expand(s["text"], blocks, rng, depth + 1, trace, occupied, added, uses=uses,
                             forced=forced))
    if len(parts) == 1:
        return _append_lora(text, lora)
    return _append_lora(SUB_JOINER.join(p for p in parts if p.strip()), lora)


def expand(prompt, blocks, rng, depth=0, trace=None, occupied=None, *, lora=True, picks=None, uses=None,
           forced=None):
    """Expand ~name, ~name.sub, ~name*slot and %Category tokens. Unknown tokens are left untouched (as
    a whole, including a ".sub" / "*slot" part). If `trace` is a list, (parent, sub) is appended for
    every sub-block that was added automatically or drawn by ~parent*slot (not for direct ~parent.sub
    calls).

    `occupied` (section 4): when None it is computed once from `prompt` at depth 0 (the top-level
    prompt) as slot_occupiers() and empty at deeper levels; recursion passes it down unchanged, so
    slots named only inside block texts never occupy anything. With the computed per-occupier dict, a
    block's own ~X call does not occupy X's slot for X itself (own-slot exception). A plain set of slot
    names passed by the caller is occupied unconditionally for every block (no exception).

    Block LoRA (section 9): whenever any part of block X is inserted (~X, a %Category pick of X,
    ~X.sub, ~X*slot, or X reached through another block's text), X's "lora" text is appended literally with
    ", " at the end of that insertion, at most once per block per call of this function.

    `lora=False` (keyword only, section 13; used for negative prompts) inserts no block LoRA at all. The
    output and the RNG consumption are then identical to the same blocks without any "lora" field.

    `picks` (keyword only, section 15): if a list, one dict is appended, in text order, for every random
    token of the given `prompt` string itself (depth 0) that resolved:
    %Category -> {"kind": "category", "category": C, "block": B} and
    ~name*slot -> {"kind": "slot", "name": N, "slot": S, "sub": X}. Tokens inside block / sub-block
    texts, plain ~name, ~name.sub and tokens left untouched record nothing. A pool / slot with only one
    candidate is recorded too. Recording never changes the output or the RNG consumption.

    `uses` (keyword only, section 31a rule 1): if a list, one dict is appended for every block use at ANY
    depth, in the order the insertions start (a block before the blocks its text reaches): {"block": B,
    "via": "block" | "category" | "sub" | "slot", "depth": d} plus "category": C for a %C pick, "sub": S
    for ~B.S, "slot": S and "sub": X for a ~B*S draw. "Used" follows the LoRA rule above (any part of
    the block is inserted), whether or not LoRA insertion is on. Recording never changes the output or
    the RNG consumption.

    `forced` (keyword only, section 31a, ADetailer texts): a dict {category: block name}; a %category
    token whose category is a key and whose block exists resolves to that block without any RNG, at
    every depth. Other categories pick as usual. None (the default) changes nothing."""
    return _expand(prompt, blocks, rng, depth, trace, occupied, set() if lora else None, picks, uses=uses,
                   forced=forced)


def _expand(prompt, blocks, rng, depth, trace, occupied, added, picks=None, uses=None, forced=None):
    # `added`: names of blocks whose LoRA was already inserted in this top-level expand() call, or None
    # when LoRA insertion is off for the whole call.
    # `picks`: only the outermost call gets it (section 15); nested calls never pass it on.
    if depth > MAX_DEPTH:
        raise BlockCycleError("Block nesting too deep (possible cycle)")
    if occupied is None:
        occupied = slot_occupiers(prompt, blocks) if depth == 0 else set()

    def repl(match):
        symbol, name, sub = _parts(match)
        if symbol == BLOCK_SYMBOL:
            block = blocks.get(name)
            if not isinstance(block, dict):
                # Unknown name, or a broken non-dict entry in blocks.json: left untouched.
                return match.group(0)
            draw = _slot_part(match)
            if draw is not None:
                # Slot draw (section 10): one of the block's sub-blocks in that slot, whatever its
                # mode and the parent's active flag; 1 candidate -> no RNG. Only the drawn sub text
                # (+ the parent's LoRA) is inserted, and the drawn sub goes into the trace.
                candidates = slot_draw_candidates(block, draw)
                if not candidates:
                    return match.group(0)
                lora = _claim_lora(name, block, added)
                picked = candidates[0] if len(candidates) == 1 else rng.choice(candidates)
                if picks is not None:
                    picks.append({"kind": "slot", "name": name, "slot": draw, "sub": picked})
                if trace is not None:
                    trace.append((name, picked))
                _record_use(uses, name, "slot", depth, slot=draw, sub=picked)
                s = get_sub(block, picked)
                return _append_lora(_expand(s["text"], blocks, rng, depth + 1, trace, occupied, added,
                                            uses=uses, forced=forced), lora)
            if sub is not None:
                # Direct call: only the sub text (+ the parent's LoRA), whatever its mode and the
                # parent's active flag.
                s = get_sub(block, sub)
                if s is None:
                    return match.group(0)
                lora = _claim_lora(name, block, added)
                _record_use(uses, name, "sub", depth, sub=sub)
                return _append_lora(_expand(s["text"], blocks, rng, depth + 1, trace, occupied, added,
                                            uses=uses, forced=forced), lora)
            _record_use(uses, name, "block", depth)
        else:
            pool = category_pool(blocks, name)  # active blocks only, sorted by name
            if not pool:
                return match.group(0)
            category = name
            fixed = forced.get(category) if isinstance(forced, dict) else None
            if isinstance(fixed, str) and isinstance(blocks.get(fixed), dict):
                name = fixed  # section 31a: the pick this image's prompt already made, no RNG
            else:
                name = _pick(pool, blocks, rng)
            block = blocks[name]
            if picks is not None:
                picks.append({"kind": "category", "category": category, "block": name})
            _record_use(uses, name, "category", depth, category=category)
        return _expand_block(name, block, blocks, rng, depth, trace, occupied, added, uses=uses,
                             forced=forced)

    return _TOKEN.sub(repl, prompt)


def replace_tokens(text, fn):
    """Call fn(symbol, name, sub, slot) for every token of `text` (only the given string, no block
    texts), tokenised exactly like expand(): `sub` is set for ~name.sub, `slot` for ~name*slot (both
    None otherwise and for %Category). A str return value replaces the token, None keeps it."""
    def repl(m):
        symbol, name, sub = _parts(m)
        new = fn(symbol, name, sub, _slot_part(m))
        return m.group(0) if new is None else new

    return _TOKEN.sub(repl, text)


def references(text, symbol, name):
    # True if text contains the exact token symbol+name (not just a prefix of a longer name).
    # ~name.sub and ~name*slot count as a reference to block name.
    return any(_parts(m)[:2] == (symbol, name) for m in _TOKEN.finditer(text))


def sub_references(text, parent, sub):
    # True if text contains the exact token ~parent.sub (a ~parent*slot draw is not one).
    return any(_parts(m) == (BLOCK_SYMBOL, parent, sub) for m in _TOKEN.finditer(text))


def rename_token(text, symbol, old, new):
    # symbol+old -> symbol+new; for blocks also ~old.sub -> ~new.sub and ~old*slot -> ~new*slot.
    def repl(m):
        sym, name, sub = _parts(m)
        if sym == symbol and name == old:
            draw = _slot_part(m)
            if draw is not None:
                return symbol + new + SLOT_DRAW_SEPARATOR + draw
            return symbol + new + (SUB_SEPARATOR + sub if sub is not None else "")
        return m.group(0)

    return _TOKEN.sub(repl, text)


def rename_sub_tokens(text, parent, mapping):
    # Rename sub-block references: ~parent.old -> ~parent.mapping[old] for every key in mapping, all in
    # one pass (so swaps like {"a": "b", "b": "a"} work). ~parent*slot draw tokens, other blocks' tokens
    # and %Category tokens are left unchanged.
    def repl(m):
        sym, name, sub = _parts(m)
        if sym == BLOCK_SYMBOL and name == parent and sub in mapping:
            return BLOCK_SYMBOL + parent + SUB_SEPARATOR + mapping[sub]
        return m.group(0)

    return _TOKEN.sub(repl, text)


def find_unknown(expanded):
    # expand() leaves unknown names untouched, so any token still present
    # in the expanded text is a name that was not found at any depth.
    seen = []
    for m in _TOKEN.finditer(expanded):
        if m.group(0) not in seen:
            seen.append(m.group(0))
    return seen


def find_all_inactive(expanded, blocks):
    # Category names whose %Category token is still in the expanded text because the category
    # has blocks but all of them are inactive. A category with no blocks at all is not listed
    # here (it stays "unknown"). Works on the expanded text, so nested tokens are found too.
    result = []
    for m in _TOKEN.finditer(expanded):
        symbol, cat, _ = _parts(m)
        if symbol != CATEGORY_SYMBOL or cat in result:
            continue
        members = [b for b in blocks.values() if in_category(b, cat)]
        if members and not any(is_active(b) for b in members):
            result.append(cat)
    return result


def _without_loras(expanded, blocks):
    # The expanded text with every token-looking block LoRA text (section 9) blanked out, so a literal
    # LoRA text such as "<lora:x~y:1>" is not reported as an unknown block / category. Longest first, so
    # a LoRA text that contains another one is removed as a whole. Replaced by a space (not ""), so the
    # text around it cannot merge into a new token.
    loras = {block_lora(b) for b in blocks.values()}
    loras = sorted((t for t in loras if t is not None and _TOKEN.search(t)), key=len, reverse=True)
    for t in loras:
        expanded = expanded.replace(t, " ")
    return expanded


def preview_warnings(expanded, blocks):
    # (unknown, all_inactive) for the preview panel; all-inactive %Category tokens are not
    # also listed as unknown. Tokens that only occur inside a block's literal LoRA text are ignored.
    expanded = _without_loras(expanded, blocks)
    all_inactive = find_all_inactive(expanded, blocks)
    skip = {CATEGORY_SYMBOL + c for c in all_inactive}
    unknown = [u for u in find_unknown(expanded) if u not in skip]
    return unknown, all_inactive
