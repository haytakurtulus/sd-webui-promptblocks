"""Block bans (design notes section 38): the stored field, the form box, hints, rename / delete / health
helpers (step 1), and the runtime pieces parser.expand() uses (step 2): reaches_bans() for the fast-path
decision, BanState (the active bans of one expand() call + what they changed) and ban_lines() /
console_line() for the preview panel and the debug console.

Pure Python, no WebUI / gradio imports. Stored shape: optional block field "bans": ["~happy", "%PEmotion"],
a list of tokens `~name` (a block) or `%Category` (a whole category), names by parser.NAME_PATTERN.
Normalised (block_bans): only valid tokens (stripped), no duplicates, written order. Stored only when the
normalised list is non-empty (key removed otherwise), so a block without bans keeps the old JSON shape.
Broken stored values (not a list, non-string or invalid entries, duplicates) are ignored; the health check
reports them (ignored_details).

Form box: comma separated text (parse_text / to_text). `~name.sub`, `~name*slot` and anything else that is
not exactly one `~name` / `%Category` token is a Save error.
"""
import re

from . import parser, weights
from .subs import normalize_subs

FIELD = "bans"
JOINER = ", "
_TOKEN = re.compile("(" + re.escape(parser.BLOCK_SYMBOL) + "|" + re.escape(parser.CATEGORY_SYMBOL) + ")("
                    + parser.NAME_PATTERN + ")")


def parse_token(value):
    """(symbol, name) of a ban token `~name` / `%Category` (surrounding whitespace allowed), else None.
    Never raises."""
    if not isinstance(value, str):
        return None
    m = _TOKEN.fullmatch(value.strip())
    return (m.group(1), m.group(2)) if m else None


def _token(value):
    # The stripped token string of a valid ban token, else None.
    parts = parse_token(value)
    return parts[0] + parts[1] if parts else None


def block_bans(block):
    """The block's usable bans: valid tokens, stripped, duplicates dropped (first kept), stored order.
    Missing / broken field -> []. Never raises."""
    raw = block.get(FIELD) if isinstance(block, dict) else None
    if not isinstance(raw, list):
        return []
    result = []
    for v in raw:
        t = _token(v)
        if t is not None and t not in result:
            result.append(t)
    return result


def to_text(bans):
    """Bans list -> the form box text ("~happy, %PEmotion"; "" for none)."""
    return JOINER.join(bans or [])


def parse_text(text):
    """Form box text -> (normalised list, None) or (None, error message). Comma separated; blank items
    (e.g. a trailing comma) are skipped; duplicates are dropped (first kept). None / non-string = []."""
    if not isinstance(text, str):
        return [], None
    result, bad = [], []
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        t = _token(item)
        if t is None:
            if item not in bad:
                bad.append(item)
        elif t not in result:
            result.append(t)
    if bad:
        listed = ", ".join("`" + b.replace("`", "'") + "`" for b in bad)
        return None, (f"Bans: {listed} {'is' if len(bad) == 1 else 'are'} not a valid ban "
                      f"(write `{parser.BLOCK_SYMBOL}name` for a block or `{parser.CATEGORY_SYMBOL}Category` "
                      f"for a category, separated by commas).")
    return result, None


def snapshot_value(text):
    """Comparable value of the form box for the "modified" check: the normalised list when the text is
    valid, else the stripped text (so any edit of an invalid text counts as a change)."""
    bans, err = parse_text(text)
    if err:
        return text.strip()
    return bans


def set_block_bans(block, bans):
    """New block dict with "bans" set to the normalised `bans` (a list of tokens; invalid entries and
    duplicates dropped), or without the key when nothing is left (old JSON shape). Input not modified."""
    block = dict(block)
    cleaned = block_bans({FIELD: list(bans) if isinstance(bans, (list, tuple)) else []})
    if cleaned:
        block[FIELD] = cleaned
    else:
        block.pop(FIELD, None)
    return block


def rewrite(block, fn):
    """(new "bans" list, changed) with fn(text) applied to every string entry of the stored list (other
    entries are kept as they are). When something changed, equal string entries are reduced to the first
    one (e.g. after a category merge); an unchanged list is returned as it is. (None, False) when the field is not a list."""
    raw = block.get(FIELD) if isinstance(block, dict) else None
    if not isinstance(raw, list):
        return None, False
    new = [fn(v) if isinstance(v, str) else v for v in raw]
    changed = new != raw
    if changed:
        kept, seen = [], set()
        for v in new:
            if isinstance(v, str):
                if v in seen:
                    continue
                seen.add(v)
            kept.append(v)
        new = kept
    return new, changed


# ---- what a ban list covers ----

def covers(bans, name, block):
    """True when the ban list `bans` (normalised tokens) bans block `name` (stored `block`): `~name` is
    listed, or `%C` with C the block's category."""
    if parser.BLOCK_SYMBOL + name in bans:
        return True
    cat = block.get("category") if isinstance(block, dict) else None
    return isinstance(cat, str) and parser.CATEGORY_SYMBOL + cat in bans


def ban_users(blocks, token, exclude=None):
    """Sorted names of blocks (other than `exclude`) whose usable bans list `token` exactly."""
    return sorted(n for n, b in blocks.items() if n != exclude and token in block_bans(b))


def mutual(blocks, name, block, bans):
    """Sorted names of OTHER blocks that `bans` (the bans of block `name`, stored `block`) cover and whose
    own bans cover this block back (by `~name` or by its category)."""
    result = []
    for other, b in blocks.items():
        if other == name or not isinstance(b, dict):
            continue
        if covers(bans, other, b) and covers(block_bans(b), name, block):
            result.append(other)
    return sorted(result)


def emptied_pools(blocks, name, bans):
    """[(category, [banned names])] of the categories whose whole %Category pick pool (active blocks) is
    banned by the `~name` tokens of `bans` (the bans of block `name`): when that block is used, a
    `%Category` call there finds no candidate. A category banned as `%C` itself is left out (silencing it
    is the stated intent); so is the banning block (never banned by its own bans). Sorted by category."""
    named = {n for s, n in (parse_token(t) for t in bans) if s == parser.BLOCK_SYMBOL and n != name}
    cats = {b.get("category") for n, b in blocks.items() if n in named and isinstance(b, dict)}
    result = []
    for c in sorted(c for c in cats if isinstance(c, str)):
        if parser.CATEGORY_SYMBOL + c in bans:
            continue
        pool = weights.category_pool(blocks, c)
        if pool and all(n in named for n in pool):
            result.append((c, pool))
    return result


def problems(blocks, name, category, bans):
    """Static notes about the ban list `bans` of block `name` with category `category` (the form's values
    or the stored block), against the saved data `blocks`: a list of (kind, text) with kind
    "unknown" (no such block / category), "self" (the block's own name or category), "mutual",
    "empty_pool". Texts are Markdown fragments."""
    stored = blocks.get(name)
    block = dict(stored if isinstance(stored, dict) else {}, category=category)
    found = []
    for t in bans:
        symbol, ref = parse_token(t)
        if symbol == parser.BLOCK_SYMBOL:
            if ref == name:
                found.append(("self", f"`{t}` is this block itself; a block is never banned by its own bans"))
            elif ref not in blocks:
                found.append(("unknown", f"`{t}`: no block named `{ref}`"))
        else:
            if ref == category:
                found.append(("self", f"`{t}` is this block's own category: the other blocks of `{t}` are "
                                      f"banned when this block is used (this block itself is not)"))
            elif not any(weights.in_category(b, ref) for b in blocks.values()):
                found.append(("unknown", f"`{t}`: no block has category `{ref}`"))
    for other in mutual(blocks, name, block, bans):
        found.append(("mutual", f"`{parser.BLOCK_SYMBOL}{other}` bans this block too (mutual ban: the block "
                                f"further left in the prompt wins)"))
    for c, pool in emptied_pools(blocks, name, bans):
        found.append(("empty_pool", f"bans every active block of `{parser.CATEGORY_SYMBOL}{c}` ("
                                    + ", ".join(f"`{parser.BLOCK_SYMBOL}{n}`" for n in pool)
                                    + f"): `{parser.CATEGORY_SYMBOL}{c}` gives nothing when this block is used"))
    return found


def hint(name, category, text, blocks):
    """Hint line under the form's Bans box ("" when there is nothing to say): the parse error, or the
    problems() of the typed bans: unknown names / categories, own name / category, mutual bans (emptied
    pools are left to the health check)."""
    bans, err = parse_text(text)
    if err:
        return "⚠ " + err
    if not bans:
        return ""
    name = name.strip() if isinstance(name, str) else ""
    category = category.strip() if isinstance(category, str) else ""
    found = [p for p in problems(blocks if isinstance(blocks, dict) else {}, name, category, bans)
             if p[0] != "empty_pool"]
    if not found:
        return ""
    return "⚠ Bans: " + "; ".join(note for _, note in found) + "."


def ignored_details(block, show=repr):
    """Health check texts for stored ban values that are ignored: a field that is not a list, entries
    that are not text or not a valid token, duplicates. [] when all is fine. None / missing = not set.
    `show(value)` formats a stored value."""
    if not isinstance(block, dict) or block.get(FIELD) is None:
        return []
    raw = block[FIELD]
    if not isinstance(raw, list):
        return [f"bans {show(raw)} is not a list; the block bans nothing"]
    result, seen = [], []
    for i, v in enumerate(raw, 1):
        t = _token(v)
        if t is None:
            what = "not text" if not isinstance(v, str) else (
                f"not `{parser.BLOCK_SYMBOL}name` / `{parser.CATEGORY_SYMBOL}Category`")
            result.append(f"ban entry #{i} {show(v)} is {what}; ignored")
        elif t in seen:
            result.append(f"ban entry #{i} {show(v)} is a duplicate; ignored")
        else:
            seen.append(t)
    return result


# ---- at Generate / Preview (step 2) ----

def reaches_bans(prompt, blocks):
    """True when some block that `prompt` can reach has non-empty usable bans: blocks called directly
    (~x, ~x.sub, ~x*slot), every block of a called category (active or not), and, transitively, the blocks
    reached through their texts and all their sub-block texts (whatever the mode or slot). A superset of
    what expand() can insert, so False guarantees the plain expansion (fast path). Block LoRA texts are
    never expanded and are not scanned. Never raises on broken entries."""
    if not isinstance(prompt, str) or not isinstance(blocks, dict):
        return False
    banning = {n for n, b in blocks.items() if block_bans(b)}
    if not banning:
        return False
    members = None
    seen, seen_cats, stack = set(), set(), [prompt]
    while stack:
        for symbol, name in parser.token_names(stack.pop()):
            if symbol == parser.BLOCK_SYMBOL:
                names = [name]
            else:
                if name in seen_cats:
                    continue
                seen_cats.add(name)
                if members is None:
                    members = {}
                    for n, b in blocks.items():
                        if isinstance(b, dict) and isinstance(b.get("category"), str):
                            members.setdefault(b["category"], []).append(n)
                names = members.get(name, [])
            for n in names:
                b = blocks.get(n)
                if n in seen or not isinstance(b, dict):
                    continue
                if n in banning:
                    return True
                seen.add(n)
                if isinstance(b.get("text"), str):
                    stack.append(b["text"])
                stack.extend(s["text"] for s in normalize_subs(b))
    return False


def normalize_initial(initial):
    """{banner name: normalised bans} of a parser.expand(bans=...) argument (a dict name -> list of
    tokens), in its order; non-string names and banners without usable bans are dropped. Not a dict ->
    {}. Never raises."""
    if not isinstance(initial, dict):
        return {}
    result = {}
    for name, raw in initial.items():
        if not isinstance(name, str):
            continue
        found = block_bans({FIELD: list(raw) if isinstance(raw, (list, tuple)) else []})
        if found:
            result[name] = found
    return result


def used_bans(blocks, uses):
    """Step 4: the ban set of one expanded prompt, {banner name: bans} of every block in a
    parser.expand(uses=...) list (each once, order of first use) with non-empty bans. On the ban path a
    banned / silenced block leaves no `uses` entry and a redrawn pick is recorded with its final block,
    so this is exactly the set of bans active when that expansion ended (every used block's bans).
    No bans reachable -> {}."""
    result = {}
    if not isinstance(blocks, dict):
        return result
    for u in uses or []:
        name = u.get("block") if isinstance(u, dict) else None
        if not isinstance(name, str) or name in result:
            continue
        found = block_bans(blocks.get(name))
        if found:
            result[name] = found
    return result


class BanState:
    """The active bans of one parser.expand() call on the ban path, plus what they changed.

    `active`: {banner name: [count, bans]} in the order the banners were first used; a block used several
    times is counted, remove() drops one use. Only blocks with non-empty bans are listed. `events`: the
    caller's list (or None) that note() appends to. `pre_added` / `selected` / `top` are filled by
    parser's pre-scan / selection pass (keys = token start offsets in the outermost string). `redrawn`:
    keys of the depth-0 picks the fix-up pass redrew (or silenced while redrawing); `late`: {key: name}
    of the redrawn picks whose bans are added only when that token is expanded.
    `initial` (step 4, ADetailer texts): {banner name: bans} active from the start (normalised here;
    banners whose bans are empty are skipped), one use each."""

    def __init__(self, events=None, initial=None):
        self.active = {}
        for name, found in normalize_initial(initial).items():
            self.active[name] = [1, found]
        self.events = events
        self.pre_added = {}
        self.selected = {}
        self.redrawn = set()
        self.late = {}
        self.top = 0

    def add(self, name, block):
        found = block_bans(block)
        if found:
            self.active.setdefault(name, [0, found])[0] += 1

    def remove(self, name):
        entry = self.active.get(name)
        if entry is not None:
            entry[0] -= 1
            if entry[0] <= 0:
                del self.active[name]

    def covering(self, name, block):
        """Banners (other than `name` itself: a block is never banned by its own bans) whose bans cover
        block `name` by `~name` or by its category. [] = not banned."""
        return [n for n, (_, b) in self.active.items() if n != name and covers(b, name, block)]

    def category_banners(self, category):
        """Banners whose bans list `%category`."""
        token = parser.CATEGORY_SYMBOL + category
        return [n for n, (_, b) in self.active.items() if token in b]

    def note(self, kind, by, **details):
        """Record one ban effect: kind "kept_out" (block=, category=), "silenced" (token=, optional
        via= the %Category token that had picked it, empty=True when every pool block was banned) or
        "redrawn" (block= the banned pick, category=, new= the new pick, optional mutual_with= the
        earlier pick that bans it back and kept its place)."""
        if self.events is not None:
            banners = []
            for b in by:
                if b not in banners:
                    banners.append(b)
            self.events.append({"kind": kind, "by": banners, **details})


def _event_text(e, arrow):
    by = ", ".join(e.get("by") or [])
    b, c = parser.BLOCK_SYMBOL, parser.CATEGORY_SYMBOL
    if e.get("kind") == "kept_out":
        return f"{by}: {b}{e['block']} kept out of {c}{e['category']}"
    if e.get("kind") == "redrawn":
        moved = f"{b}{e['block']} redrawn in {c}{e['category']} {arrow} {b}{e['new']}"
        if e.get("mutual_with"):
            return f"{b}{e['mutual_with']} and {b}{e['block']} ban each other: {moved} (first in prompt wins)"
        return f"{by}: {moved}"
    if e.get("empty"):
        return f"{by}: {e['token']} silenced (every block of it is banned)"
    if e.get("via"):
        return f"{by}: {e['token']} (picked by {e['via']}) silenced"
    return f"{by}: {e['token']} silenced"


def ban_lines(events, prefix="⛔ ", arrow="→"):
    """Preview lines of an expand(ban_events=...) list, e.g. "⛔ ninja: ~happy kept out of %PEmotion",
    "⛔ ninja: ~kiss_pose redrawn in %PPose → ~walk", "⛔ ~a and ~b ban each other: ~b redrawn in
    %Cat → ~c (first in prompt wins)"; each line once, in order. [] when no ban changed anything."""
    lines = []
    for e in events or []:
        line = prefix + _event_text(e, arrow)
        if line not in lines:
            lines.append(line)
    return lines


def console_line(events):
    """One ASCII console text for the ban effects of one image ("" when none)."""
    return "; ".join(ban_lines(events, prefix="", arrow="->"))
