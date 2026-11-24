"""Create a new block from a prompt selection (design notes section 16). No WebUI imports."""

import random

from . import parser


def build_new_block(blocks, name, category, text):
    """Validate and add a brand-new block.

    Returns (new_blocks, None) on success, where new_blocks is a copy of `blocks` with
    new_blocks[name] == {"category": category, "text": text} (all three inputs stripped),
    or (None, error message). `blocks` is never mutated. An existing name is refused
    (no overwrite from the txt2img / img2img accordion)."""
    n = (name or "").strip()
    c = (category or "").strip()
    t = (text or "").strip()
    if not parser.is_valid_name(n):
        return None, f"Invalid name: `{n}` (must start with a letter; letters, digits, _)"
    cerr = parser.category_error(c)
    if cerr:
        return None, cerr
    if not t:
        return None, "Text cannot be empty."
    if n in blocks:
        return None, f"A block named `{n}` already exists - edit it in the PromptBlocks tab"
    candidate = dict(blocks)
    candidate[n] = {"category": c, "text": t}
    # Same idea as the tab's save-time check: one seed (CLAUDE.md 2b). Nothing can reference the new
    # name yet, but its text can reference an existing cycle.
    try:
        parser.expand(parser.BLOCK_SYMBOL + n, candidate, random.Random(0), apply_bans=False)
    except parser.BlockCycleError as e:
        return None, f"Not saved: {e}"
    return candidate, None
