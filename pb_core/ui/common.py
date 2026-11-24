"""Shared constants and small helpers of the management tab (no components, no handlers).

Everything here is used by more than one module of the package: the queue settings of every listener,
the form signal / form generation counters, `out()` for "update only these outputs" responses, and
thin wrappers around the pure `pb_core` modules.
"""
import itertools

import gradio as gr

from .. import bans, browser, formsave, parser, storage, subrows, suggest, weights
from .groups import SLOT_DROPDOWNS, SUB_SLOTS, form_fields

N_SUBS = subrows.ROW_COUNT
MODE_CHOICES = [("Include", "include"), ("Exclude", "exclude"), ("Random", "random")]

# Counter of the form signal (#pb_form_epoch, section 20): every value is new, so the element always
# changes and the JS observer sees it. "clean N" = the form was loaded / saved / blanked / reloaded;
# "dirty N" = a handler changed the form programmatically (e.g. Duplicate), which has no DOM input event.
# Only the Save buttons' cosmetic "modified" marker uses it; the server decides "modified" itself
# (guard.is_modified).
_EPOCH = itertools.count(1)

# Form generation (section 23a fix 6): a new value whenever a handler reloads or blanks the form fields
# (block load, New, Reload, Delete, Restore, a reload after Rename category / Move LoRA tags in ALL
# blocks). It is kept twice: in a gr.State (the server's current value, read when a handler RUNS) and in
# a hidden Textbox (the browser's value, sent when the event is TRIGGERED). A handler whose two values
# differ was triggered on a form that has been replaced since (guard.is_stale): the form values it got
# are not the form on screen. Gradio reads a State input when the handler starts; that equals "while it
# runs" only because all handlers of the tab run one at a time (QUEUE). Two users of it:
# - Save: Save, New, Save clicked within a few ms: the second Save runs after New; it still saves, but
#   must not write the first block's rows into New's blank form.
# - A block switch (section 26): New, then a tile within a few ms: the tile's values are the form before
#   New; they must not be auto-saved (New already handled that form), the target is simply loaded.
_GEN = itertools.count(1)

# Every event listener of the tab runs in one Gradio concurrency group with limit 1 (section 23a fix 6):
# the queue (gradio/queueing.py) keeps one FIFO deque per concurrency_id and starts an event of a group
# only while fewer than concurrency_limit of it are running, so the tab's handlers run one at a time in
# the order the browser triggered them and their responses arrive in that order. Without it every
# handler function had its own group, and a slow Save could finish after a later New.
QUEUE = {"concurrency_id": "promptblocks_tab", "concurrency_limit": 1}
# Background refreshes (follow-up chains, hint lines) and the block switch: same group, and no progress
# overlay. While an event is queued / running, Gradio covers each of its output components with a status
# overlay (statustracker .wrap, pointer-events on) that swallows clicks, so a queued choices-only refresh
# of the Category dropdown made a click into it (and the typing after it) miss the field.
BACKGROUND = dict(QUEUE, show_progress="hidden")


def new_gen():
    return str(next(_GEN))


def signal(kind):
    # The value sits in a data attribute: the element's textContent also contains Gradio's loading
    # indicator while an event runs, which made the JS see "changes" that were none.
    value = f"{kind} {next(_EPOCH)}"
    return f'<span data-pb-form="{value}">{value}</span>'


def gallery_unselect():
    # Clears the gallery's selected index. gr.update(selected_index=None) does NOT work in Gradio 4.40:
    # blocks.postprocess_data runs utils.delete_none() on update dicts, which drops the None, so the
    # index stayed and a second click on the same tile fired no select event. A component instance is
    # converted from its constructor_args instead (no delete_none), so selected_index=None is sent.
    return gr.Gallery(selected_index=None)


def out(keys, *pairs):
    # One value per output (`keys`: a list of component keys from groups.py): gr.update() (unchanged)
    # except for the given (key, value) pairs.
    values = [gr.update() for _ in keys]
    for key, value in pairs:
        values[keys.index(key)] = value
    return tuple(values)


def chance_preview(n, c, w, active):
    # Chance line for the values currently in the form (block may be unsaved or have an unsaved weight).
    n, c = (n or "").strip(), (c or "").strip()
    if not parser.is_valid_name(n) or not parser.is_valid_name(c):
        return ""
    w, err = weights.validate_weight(w)
    if err:
        return "⚠ " + err
    blocks = dict(storage.load_blocks())
    blocks[n] = formsave.with_active(formsave.with_weight({**formsave.stored(blocks, n), "category": c}, w),
                                     active)
    return weights.chance_line(blocks, n, c)


def block_names(blocks):
    return sorted(blocks.keys())


def category_names(blocks):
    return sorted(suggest.category_counts(blocks).keys())


def rows_to_values(rows):
    # Row dicts -> values for the sub-block row components (groups.SUB_COMPONENTS order:
    # names..., texts..., modes..., slots..., sub_meta, chances...).
    return subrows.rows_to_values(rows, with_chance=True)


def rows_from_values(values):
    # Inverse of rows_to_values. Slot and chance come from the visible fields; sub_meta only holds
    # each row's identity (loaded name).
    return subrows.rows_from_values(values, N_SUBS)


def hint_values(values, blocks):
    # Values for groups.HINT_OUTPUTS from flat form values (groups.FORM_INPUTS layout).
    f = form_fields(values)
    return (suggest.form_hints(f["category"], f["block_slot"], [f[k] for k in SUB_SLOTS], blocks)
            + (bans.hint(f["name"], f["category"], f["bans"], blocks),))


def load_values(blocks, name):
    # (FORM_INPUTS values, HINT_OUTPUTS values) of block `name` (blank form if it does not exist); the
    # category and slot dropdowns get fresh choices with their value (the data may have a new one).
    plain = subrows.form_values(subrows.block_form(blocks, name), with_chance=True)
    f = form_fields(plain)
    f["category"] = gr.update(choices=category_names(blocks), value=f["category"])
    slots = subrows.slot_choices(blocks)
    for k in SLOT_DROPDOWNS:
        f[k] = gr.update(choices=slots, value=f[k])
    return list(f.values()), hint_values(plain, blocks)


def slot_choices():
    return subrows.slot_choices(storage.load_blocks())


def browser_gallery(blocks, search_text, cat):
    # Gallery content of the block browser for the current search text + category filter.
    return browser.build_gallery(blocks, search_text, cat, storage.thumb_path, storage.tile_cache_dir())


def browser_values(blocks, search_text, cat):
    # (gallery items, names, note, cat_filter update) of the block browser. The filter's value is only sent
    # when it falls back to "all" (its category is gone), so cat_filter.change never re-fires unchanged.
    kept = browser.normalize_filter(cat, blocks)
    result = browser_gallery(blocks, search_text, kept)
    choices = browser.category_filter_choices(blocks)
    cat_update = gr.update(choices=choices) if kept == cat else gr.update(choices=choices, value=kept)
    return result["items"], result["names"], result["note"], cat_update


def keep_or_clear(choices, current, values=None):
    # Fresh dropdown choices; the value is cleared only when `current` is not one of `values` any more.
    if current is not None and current not in (choices if values is None else values):
        return gr.update(choices=choices, value=None)
    return gr.update(choices=choices)
