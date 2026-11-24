# Picks of random tokens (design notes section 15): infotext summary and "Pin last picks".
# Pure Python, no WebUI imports. The picks list is what parser.expand(..., picks=[...]) recorded.
import random
from collections import deque

from . import parser
from .subs import get_sub

CATEGORY = "category"
SLOT = "slot"


def _slot_label(p):
    return p["name"] + parser.SLOT_DRAW_SEPARATOR + p["slot"]


def expand_recorded(prompts, rng_seeds, blocks, uses=None, ban_events=None):
    """Like expanding each prompt with random.Random(seed) (LoRA on, positive prompts), but also
    recording per image the depth-0 picks and the sub-block trace. Returns three index-aligned lists
    (expanded, picks, traces). May raise parser.BlockCycleError.
    `uses`: if a list, one list of block uses per image (parser.expand(uses=...), section 31a) is
    appended to it, index-aligned with the returned lists.
    `ban_events`: likewise, one parser.expand(ban_events=...) list per image (section 38)."""
    expanded, all_picks, traces = [], [], []
    for prompt, seed in zip(prompts, rng_seeds):
        pk, tr = [], []
        us = [] if uses is not None else None
        ev = [] if ban_events is not None else None
        expanded.append(parser.expand(prompt, blocks, random.Random(seed), trace=tr, picks=pk, uses=us,
                                      ban_events=ev))
        all_picks.append(pk)
        traces.append(tr)
        if uses is not None:
            uses.append(us)
        if ban_events is not None:
            ban_events.append(ev)
    return expanded, all_picks, traces


def summary(picks, trace):
    """Readable summary for infotext, e.g. "PCharacter=saber, saber*outfit=dress; subs: saber.sword".
    The picks part lists every recorded pick in order. The "subs:" part lists the sub-blocks from the
    trace (parent, sub) de-duplicated in order, without the ones already shown as a depth-0 slot pick.
    Each part is omitted when empty; "" when there is nothing at all. Picks a ban silenced (section 38,
    "silenced": True) are left out: the summary shows the final picks only."""
    items = []
    shown = set()
    for p in picks or []:
        if p.get("silenced"):
            continue
        if p.get("kind") == CATEGORY:
            items.append(f'{p["category"]}={p["block"]}')
        elif p.get("kind") == SLOT:
            items.append(f'{_slot_label(p)}={p["sub"]}')
            shown.add((p["name"], p["sub"]))
    subs = []
    for parent, sub in trace or []:
        if (parent, sub) in shown:
            continue
        s = parent + parser.SUB_SEPARATOR + sub
        if s not in subs:
            subs.append(s)
    parts = []
    if items:
        parts.append(", ".join(items))
    if subs:
        parts.append("subs: " + ", ".join(subs))
    return "; ".join(parts)


def pin_prompt(prompt, picks, blocks):
    """Replace the random depth-0 tokens of `prompt` with the recorded picks: %Category -> ~block,
    ~name*slot -> ~name.sub. Picks are consumed in order per kind (FIFO per category, FIFO per
    (name, slot)). A token with no remaining pick is left alone; a pick whose block / sub-block no longer
    exists in `blocks`, or a silenced pick (section 38, block / sub None), is consumed but its token is
    left alone. Returns (new_prompt, n_replaced)."""
    queues = {}
    for p in picks or []:
        if p.get("kind") == CATEGORY:
            key = (CATEGORY, p.get("category"))
        elif p.get("kind") == SLOT:
            key = (SLOT, p.get("name"), p.get("slot"))
        else:
            continue
        queues.setdefault(key, deque()).append(p)
    count = 0

    def fn(symbol, name, sub, slot):
        nonlocal count
        if symbol == parser.CATEGORY_SYMBOL:
            q = queues.get((CATEGORY, name))
            if not q:
                return None
            block = q.popleft().get("block")
            if (not isinstance(block, str) or not parser.is_valid_name(block)
                    or not isinstance(blocks.get(block), dict)):
                return None
            count += 1
            return parser.BLOCK_SYMBOL + block
        if slot is None:
            return None
        q = queues.get((SLOT, name, slot))
        if not q:
            return None
        picked = q.popleft().get("sub")
        parent = blocks.get(name)
        if not isinstance(picked, str) or not isinstance(parent, dict) or get_sub(parent, picked) is None:
            return None
        count += 1
        return parser.BLOCK_SYMBOL + name + parser.SUB_SEPARATOR + picked

    new = parser.replace_tokens(prompt, fn)
    return new, count


def pin_response(prompt, stored, blocks, generated):
    """Body of POST /promptblocks/pin: {prompt, replaced, available, generated}. `stored` is the
    recorded picks list of the tab (None = nothing recorded), `generated` whether a Generate ran in
    that tab (design notes 23b)."""
    stored = stored if isinstance(stored, list) else []
    new_prompt, n = pin_prompt(prompt, stored, blocks)
    return {"prompt": new_prompt, "replaced": n, "available": len(stored), "generated": bool(generated)}
