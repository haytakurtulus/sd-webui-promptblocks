"""WIRING: every event listener of the tab, in one place.

wire(c) attaches the handlers of form / fields / sidebar / tools / refresh to the components of
layout.build(), with the input / output lists of groups.py. Every listener is in the tab's single
concurrency group (common.QUEUE, section 23a fix 6); background refreshes and the block switch also hide
the progress overlay (common.BACKGROUND). The ORDER of the listeners below is part of the behaviour
(Gradio numbers them in this order); keep it.
"""
from .. import subs
from . import fields, form, refresh, sidebar, tools
from .common import BACKGROUND, QUEUE, chance_preview
from .groups import (BANS_HINT_INPUTS, BROWSER_INPUTS, BROWSER_OUTPUTS, BULK_ACTIVE_INPUTS, BULK_ACTIVE_OUTPUTS,
                     CAT_RENAME_INPUTS, CAT_RENAME_OUTPUTS, CATEGORIES_OUTPUTS, CATEGORY_CHANGED_INPUTS,
                     CATEGORY_CHANGED_OUTPUTS, CHANCE_INPUTS, DELETE_INPUTS, DOWN_BTNS, DUPLICATE_OUTPUTS,
                     FORM_OUTPUTS, HEALTH_OUTPUTS, HINT_INPUTS, HINT_OUTPUTS, LORA_ALL_INPUTS, LORA_ALL_OUTPUTS, LORA_FORM_INPUTS, LORA_FORM_OUTPUTS,
                     PICK_INPUTS, RENAME_INPUTS, RENAME_OUTPUTS, RESTORE_INPUTS, RESTORE_OUTPUTS, SAVE_INPUTS,
                     SAVE_OUTPUTS, SLOT_DROPDOWNS, SUB_ALL_BTNS, SUB_ALL_INPUTS, SUB_ALL_OUTPUTS, SUB_COMPONENTS,
                     SUB_MODES_INPUTS, SUB_MODES_OUTPUTS, SUB_SLOTS, SWITCH_INPUTS, SWITCH_OUTPUTS,
                     THUMB_TOUCHED_OUTPUTS, TILE_INPUTS, UP_BTNS, USE_LAST_OUTPUTS)


def _then(dep, fn, inputs=None, outputs=None):
    # One more chained step: a background refresh (same concurrency group, no overlay).
    return dep.then(fn, inputs=inputs, outputs=outputs, **BACKGROUND)


def _after_data_change(c, dep, hints=False, choices=True):
    # The follow-up chain of a handler that changed saved data (section 24 fix 1): only what is
    # secondary is chained; what the user looks at right after the press (status, hint lines,
    # the form) comes in the handler's own response. Order: the browser first (a new /
    # renamed tile, "(off)" captions), then the dropdown choices (seen only when a dropdown
    # is opened), then the backups list (inside "More actions"). `hints`: only for Refresh,
    # which writes no form field but may bring hand-edited data.
    if hints:
        dep = _then(dep, refresh.on_hints, c.pick(HINT_INPUTS), c.pick(HINT_OUTPUTS))
    dep = _then(dep, sidebar.on_browser, c.pick(BROWSER_INPUTS), c.pick(BROWSER_OUTPUTS))
    if choices:
        dep = _then(dep, refresh.on_categories_changed, c.cat_from, c.pick(CATEGORIES_OUTPUTS))
        dep = _then(dep, refresh.on_slots_changed, None, c.pick(SLOT_DROPDOWNS))
    return _then(dep, refresh.on_backups_changed, c.backups_dd, c.backups_dd)


def wire(c):
    p = c.pick
    # Block switch (section 26): dropdown pick (input = user selections only), tile click, New. No
    # follow-up chain: an auto-save brings its refreshes in the same response (refresh.data_refresh).
    # No progress overlay (BACKGROUND): the gallery is one of the outputs (refresh after an auto-save,
    # unselect after a tile click), and its overlay swallowed a tile click made while New was still
    # running (found with slowed handlers, the "first tile click after New does nothing" case of
    # section 24).
    c.picker.input(form.on_pick, inputs=p(PICK_INPUTS), outputs=p(SWITCH_OUTPUTS), **BACKGROUND)
    c.new_btn.click(form.on_new, inputs=p(SWITCH_INPUTS), outputs=p(SWITCH_OUTPUTS), **BACKGROUND)
    c.gallery.select(form.on_gallery_select, inputs=p(TILE_INPUTS), outputs=p(SWITCH_OUTPUTS), **BACKGROUND)
    c.reload_btn.click(form.on_reload, inputs=c.loaded_block, outputs=p(FORM_OUTPUTS), **QUEUE)
    c.duplicate_btn.click(tools.on_duplicate, inputs=c.name, outputs=p(DUPLICATE_OUTPUTS), **QUEUE)
    c.search.change(sidebar.on_browser, inputs=p(BROWSER_INPUTS), outputs=p(BROWSER_OUTPUTS), **QUEUE)
    c.cat_filter.change(sidebar.on_browser, inputs=p(BROWSER_INPUTS), outputs=p(BROWSER_OUTPUTS), **QUEUE)
    for i, (up_btn, down_btn) in enumerate(zip(p(UP_BTNS), p(DOWN_BTNS))):
        up_btn.click(fields.make_move(i, -1), inputs=p(SUB_COMPONENTS), outputs=p(SUB_COMPONENTS), **QUEUE)
        down_btn.click(fields.make_move(i, 1), inputs=p(SUB_COMPONENTS), outputs=p(SUB_COMPONENTS), **QUEUE)
    c.use_last_btn.click(fields.on_use_last, outputs=p(USE_LAST_OUTPUTS), **QUEUE)
    c.thumb.upload(fields.on_thumb_touched, outputs=p(THUMB_TOUCHED_OUTPUTS), **QUEUE)
    c.thumb.clear(fields.on_thumb_touched, outputs=p(THUMB_TOUCHED_OUTPUTS), **QUEUE)
    for btn in (c.save_btn, c.save_fab):
        # Both Save buttons: same handler, same inputs/outputs, same follow-up chain.
        _after_data_change(c, btn.click(form.on_save, inputs=p(SAVE_INPUTS), outputs=p(SAVE_OUTPUTS), **QUEUE))
    # Delete and Restore blank the form (hint lines included).
    _after_data_change(c, c.delete_btn.click(tools.on_delete, inputs=p(DELETE_INPUTS), outputs=p(FORM_OUTPUTS),
                                             **QUEUE))
    # A rename changes no category or slot, so no choices refresh.
    _after_data_change(c, c.rename_btn.click(tools.on_rename, inputs=p(RENAME_INPUTS), outputs=p(RENAME_OUTPUTS),
                                             **QUEUE),
                       choices=False)
    _after_data_change(c, c.refresh_btn.click(refresh.on_refresh, outputs=c.picker, **QUEUE), hints=True)
    _after_data_change(c, c.restore_btn.click(tools.on_restore, inputs=p(RESTORE_INPUTS),
                                              outputs=p(RESTORE_OUTPUTS), **QUEUE))
    c.lora_form_btn.click(tools.on_lora_form, inputs=p(LORA_FORM_INPUTS), outputs=p(LORA_FORM_OUTPUTS), **QUEUE)
    _after_data_change(c, c.lora_all_btn.click(tools.on_lora_all, inputs=p(LORA_ALL_INPUTS),
                                               outputs=p(LORA_ALL_OUTPUTS), **QUEUE))
    c.health_btn.click(tools.on_health, outputs=p(HEALTH_OUTPUTS), **QUEUE)
    _after_data_change(c, c.cat_rename_btn.click(tools.on_cat_rename, inputs=p(CAT_RENAME_INPUTS),
                                                 outputs=p(CAT_RENAME_OUTPUTS), **QUEUE))
    for btn, value in ((c.enable_shown_btn, True), (c.disable_shown_btn, False)):
        dep = btn.click(sidebar.make_bulk_active(value), inputs=p(BULK_ACTIVE_INPUTS),
                        outputs=p(BULK_ACTIVE_OUTPUTS), **QUEUE)
        # Active changes no category or slot, so no choices refresh.
        _after_data_change(c, dep, choices=False)

    c.category.change(fields.on_category_changed, inputs=p(CATEGORY_CHANGED_INPUTS),
                      outputs=p(CATEGORY_CHANGED_OUTPUTS), **BACKGROUND)
    c.block_slot.change(fields.on_block_slot_changed, inputs=c.block_slot, outputs=c.block_slot_hint, **BACKGROUND)
    for dd in p(SUB_SLOTS):
        dd.change(fields.on_row_slots_changed, inputs=p(SUB_SLOTS), outputs=c.sub_slot_hint, **BACKGROUND)
    c.weight.input(chance_preview, inputs=p(CHANCE_INPUTS), outputs=c.chance, **BACKGROUND)
    c.active.input(chance_preview, inputs=p(CHANCE_INPUTS), outputs=c.chance, **BACKGROUND)
    # Set sub-blocks of shown blocks (section 36 B), added last so the listeners above keep their numbers.
    # Sub-block modes change no category or slot, so no choices refresh.
    _after_data_change(c, c.sub_mode_bulk_btn.click(tools.on_sub_modes, inputs=p(SUB_MODES_INPUTS),
                                                    outputs=p(SUB_MODES_OUTPUTS), **QUEUE),
                       choices=False)
    # All Include | All Exclude | All Random of the open form (section 37 B): form only, no data change, so no
    # follow-up chain. Added after everything above so the existing listeners keep their numbers.
    for key, mode in zip(SUB_ALL_BTNS, subs.MODES):
        getattr(c, key).click(tools.make_sub_all(mode), inputs=p(SUB_ALL_INPUTS), outputs=p(SUB_ALL_OUTPUTS),
                              **QUEUE)
    # Bans hint while typing (section 38), added last so the listeners above keep their numbers.
    c.bans.input(fields.on_bans_input, inputs=p(BANS_HINT_INPUTS), outputs=c.bans_hint, **BACKGROUND)
