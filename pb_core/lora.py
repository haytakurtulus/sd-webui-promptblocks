"""Block LoRA field (design notes section 9).

Pure Python with no imports from other pb_core modules, so parser.py, subrows.py and ui.py can all import
it without a circular import (subs.py already has to import parser lazily).

Stored shape: optional "lora": "<lora:name:0.8>" per block (any text). Missing / empty / whitespace-only /
non-string = no LoRA. Stored only when non-empty after strip (key removed otherwise).

Migration helpers (section 13): split_lora_tags / merge_lora / migrate_block / migrate_all move
<lora:...> / <lyco:...> tags from a block's main text into its "lora" field.
"""
import re

LORA_JOINER = ", "
# <lora:...> or <lyco:...>, tag name case-insensitive, no "<", ">" or line break inside.
_LORA_TAG = re.compile(r"<(?:lora|lyco):[^<>\r\n]+>", re.IGNORECASE)
_SEPARATORS = " \t,"
_NEWLINES = "\r\n"
_MULTI_COMMA = re.compile(r",(?:[ \t]*,)+")


def block_lora(block):
    """The block's LoRA text, stripped, or None (missing / empty / whitespace / non-string / no dict).
    Never raises."""
    if not isinstance(block, dict):
        return None
    value = block.get("lora")
    if not isinstance(value, str):
        return None
    return value.strip() or None


def set_block_lora(block, lora):
    """New block dict with "lora" set to the stripped text; None / "" / whitespace / non-string removes
    the key (old JSON shape). The input is not modified."""
    block = dict(block)
    value = lora.strip() if isinstance(lora, str) else ""
    if value:
        block["lora"] = value
    else:
        block.pop("lora", None)
    return block


def _remove_tag(text, start, end):
    # `text` without the tag at [start, end) and the separators next to it (spaces, tabs, commas on the
    # same line). Nothing farther away is touched:
    # - tag alone on its line (only separators around it): the whole line goes, with one line break;
    # - tag at the start / end of a line: the separators between it and the line edge go with it;
    # - tag between two pieces of text: one separator is kept (the right one if it has a comma, else the
    #   left one if it has a comma, else the spaces), with repeated commas collapsed to one.
    left = start
    while left > 0 and text[left - 1] in _SEPARATORS:
        left -= 1
    right = end
    while right < len(text) and text[right] in _SEPARATORS:
        right += 1
    at_line_start = left == 0 or text[left - 1] in _NEWLINES
    at_line_end = right == len(text) or text[right] in _NEWLINES
    if at_line_start and at_line_end:
        if right < len(text):
            right += 2 if text.startswith("\r\n", right) else 1
        elif left > 0:
            left -= 2 if text[:left].endswith("\r\n") else 1
        return text[:left] + text[right:]
    if at_line_start or at_line_end:
        return text[:left] + text[right:]
    before, after = text[left:start], text[end:right]
    if "," in after:
        joiner = after
    elif "," in before:
        joiner = before
    else:
        joiner = after or before or " "  # never glue two words together
    return text[:left] + _MULTI_COMMA.sub(",", joiner) + text[right:]


def split_lora_tags(text):
    """(clean_text, tags): every <lora:...> / <lyco:...> tag (tag name case-insensitive) removed from
    `text`, and the tags verbatim in order of appearance, exact duplicates dropped (first kept).
    Only separators next to a removed tag are cleaned (see _remove_tag); a text without tags is returned
    unchanged. Non-string text counts as ""."""
    if not isinstance(text, str):
        return "", []
    tags = []
    while True:
        m = _LORA_TAG.search(text)
        if m is None:
            return text, tags
        if m.group(0) not in tags:
            tags.append(m.group(0))
        text = _remove_tag(text, m.start(), m.end())


def lora_tags_in_order(text):
    """Every <lora:...> / <lyco:...> tag of `text` verbatim, in order of appearance, duplicates KEPT
    (design notes 35: the list Forge loads keeps them too). Non-string text -> []."""
    if not isinstance(text, str):
        return []
    return _LORA_TAG.findall(text)


def strip_lora_tags(text):
    """`text` with every <lora:...> / <lyco:...> tag removed (the same separator cleaning as
    split_lora_tags); the rest stays as written. Non-string text counts as ""."""
    return split_lora_tags(text)[0]


def merge_lora(existing, tags):
    """`existing` LoRA text with the tags not already in it appended (", "-joined, in order, no
    duplicates). Unchanged if nothing is new. Non-string `existing` counts as ""."""
    existing = existing if isinstance(existing, str) else ""
    present = split_lora_tags(existing)[1]
    new = []
    for t in tags:
        if t not in present and t not in new:
            new.append(t)
    if not new:
        return existing
    base = existing.strip()
    return LORA_JOINER.join(([base] if base else []) + new)


def migrate_block(block):
    """(new_block, changed): LoRA tags moved from the block's main "text" into its "lora" field
    (appended, no duplicates). Sub-block texts are left alone. The input is not modified; a block without
    tags in its text (or a non-dict / non-string text) is returned as is with changed=False. Idempotent."""
    if not isinstance(block, dict) or not isinstance(block.get("text"), str):
        return block, False
    clean, tags = split_lora_tags(block["text"])
    if not tags:
        return block, False
    new = dict(block)
    new["text"] = clean
    return set_block_lora(new, merge_lora(block_lora(block) or "", tags)), True


def migrate_all(blocks):
    """(new_blocks, changed_names, skipped_names) for migrate_block over every block, names sorted.
    A block whose text would become empty (only LoRA tags) is NOT migrated (the tab's Save refuses an
    empty Text) and is listed in skipped_names instead. The input dict and its blocks are not modified.
    Idempotent: a second run changes nothing."""
    new_blocks = dict(blocks)
    changed, skipped = [], []
    for name in sorted(blocks):
        new, did = migrate_block(blocks[name])
        if not did:
            continue
        if not new["text"].strip():
            skipped.append(name)
            continue
        new_blocks[name] = new
        changed.append(name)
    return new_blocks, changed, skipped
