"""REFRESH handlers: bring lists and choices up to date after saved data changed.

data_refresh() is the in-response variant (used by a block switch whose auto-save wrote data); the
on_* handlers are the chained steps of wiring.after_data_change and the ↻ button.
"""
import gradio as gr

from .. import bans, guard, storage, suggest
from .common import block_names, browser_values, category_names, keep_or_clear, slot_choices
from .groups import SLOT_DROPDOWNS


def data_refresh(blocks, search_text, cat, cur_from, cur_backup):
    # Values for REFRESH_OUTPUTS after a write, as the chained sidebar.on_browser / on_categories_changed /
    # on_backups_changed (a value that no longer exists is cleared), except that the gallery's selected
    # index is cleared on purpose.
    items, names, note, filter_update = browser_values(blocks, search_text, cat)
    return (gr.Gallery(value=items, selected_index=None), names, note, filter_update,
            keep_or_clear(category_names(blocks), cur_from), on_backups_changed(cur_backup))


def on_refresh():
    # ↻ button, output picker: fresh block names (hand-edited data); the rest is chained.
    return gr.update(choices=block_names(storage.load_blocks()))


def on_hints(seen_gen, cur_gen, c, bs, n, banned, *row_slots):
    # Outputs: HINT_OUTPUTS. Inputs: HINT_INPUTS (form_gen_seen, form_gen, category, block_slot, name, bans,
    # the row slot dropdowns). Refreshes the four hint lines from the form's current values after Refresh
    # (hand-edited data). Skipped when the form was reloaded / blanked after this chain was
    # triggered (stale values).
    if guard.is_stale(seen_gen, cur_gen):
        return gr.update(), gr.update(), gr.update(), gr.update()
    blocks = storage.load_blocks()
    return suggest.form_hints(c, bs, row_slots, blocks) + (bans.hint(n, c, banned, blocks),)


def on_categories_changed(current_from):
    # Outputs: CATEGORIES_OUTPUTS (category, cat_from). Only choices for the form's Category: the value
    # the user is editing stays as it is. The Rename category "from" dropdown keeps its value unless
    # that category is gone (then it is cleared).
    choices = category_names(storage.load_blocks())
    return gr.update(choices=choices), keep_or_clear(choices, current_from)


def on_slots_changed():
    # Outputs: SLOT_DROPDOWNS. Only choices, for the block slot and every row slot; values stay as
    # they are.
    choices = slot_choices()
    return tuple(gr.update(choices=choices) for _ in SLOT_DROPDOWNS)


def on_backups_changed(current):
    # Output: backups_dd. Fresh choices after anything that may have written a backup; the
    # value is dropped only if that backup is gone (pruned). A pending restore confirmation
    # does not need a reset here: its key holds the current data (guard.data_key), so a save
    # in between makes the next Restore press ask again.
    choices = storage.backup_choices()
    return keep_or_clear(choices, current, [v for _, v in choices])
