"""FIELD handlers: small reactions inside the form that save nothing.

Sub-block row moves, the thumbnail (upload / clear / Use last generated image), and the hint lines and
chance line that follow the Category / slot / weight / active fields (chance line: common.chance_preview).
"""
import gradio as gr

from .. import bans, state, storage, subrows, suggest
from .common import chance_preview, rows_from_values, rows_to_values, signal


def make_move(index, delta):
    # Handler of row `index`'s ↑ (delta -1) / ↓ (delta 1) button. Inputs / outputs: SUB_COMPONENTS.
    def on_move(*values):
        return tuple(rows_to_values(subrows.move_row(rows_from_values(values), index, delta)))
    return on_move


def on_use_last():
    # Outputs: USE_LAST_OUTPUTS (thumb, status, thumb_touched, form_epoch).
    if state.last_image is None:
        return gr.update(), "No image generated since WebUI started.", gr.update(), gr.update()
    return (state.last_image, "Last generated image loaded. Press Save to keep it.", True,
            signal("dirty"))


def on_thumb_touched():
    # Outputs: THUMB_TOUCHED_OUTPUTS (thumb_touched, form_epoch). Image upload (file, drop, paste) and
    # clear are user-only events in Gradio 4.40 (setting the image from a handler fires only change).
    return True, signal("dirty")


def on_category_changed(n, c, w, act, banned):
    # One handler for all outputs (CATEGORY_CHANGED_OUTPUTS): typo hint + chance line + Bans hint (own-category
    # ban, section 38) from the current form values (inputs CATEGORY_CHANGED_INPUTS). Also fires when a load fills the field; then the form holds the stored block's
    # values, so chance_preview gives the same line as the load's chance_line (no stale/wrong line).
    blocks = storage.load_blocks()
    return suggest.category_hint(c, blocks), chance_preview(n, c, w, act), bans.hint(n, c, banned, blocks)


def on_bans_input(n, c, banned):
    # bans.input (user typing only; a load sets the hint in its own response). Inputs: BANS_HINT_INPUTS.
    return bans.hint(n, c, banned, storage.load_blocks())


def on_block_slot_changed(value):
    return suggest.slot_hint(value, storage.load_blocks())


def on_row_slots_changed(*values):
    # One shared hint line for all rows, computed from all row slot values, so the result
    # does not depend on which row's change event fired last.
    return suggest.row_slots_hint(values, storage.load_blocks())
