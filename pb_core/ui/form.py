"""FORM handlers: load a block into the form, switch blocks (tile / dropdown / New), Reload, Save.

Every block switch goes through switch() (section 26): it auto-saves a modified valid form, refuses a
modified invalid one, and loads the target. Return values follow the groups.py lists named in each
handler's comment.
"""
import gradio as gr

from .. import browser, formsave, guard, storage, subrows, weights
from .common import block_names, gallery_unselect, hint_values, load_values, new_gen, out, rows_to_values, signal
from .groups import FORM_COMPONENTS, REFRESH_OUTPUTS, SAVE_OUTPUTS, SWITCH_OUTPUTS, form_fields
from .refresh import data_refresh


def form_load(blocks, name, msg):
    # Values for FORM_OUTPUTS: block `name` of `blocks` loaded into the form, or the blank form
    # (name None / a block that does not exist). The category and slot dropdowns get fresh
    # choices with their value (an auto-save may just have added a category / slot), the form
    # a new generation and a "clean" signal, the dropdown shows the block (or nothing). The
    # New-name box of Rename is cleared only when the form is blanked.
    values, hints = load_values(blocks, name)
    selected = form_fields(values)["name"] or None
    img = storage.load_thumb(selected) if selected else None
    gen = new_gen()
    return (*values, img, selected, False, None, None, gr.update() if selected else "",
            signal("clean"), gen, gen, *hints,
            gr.update(choices=block_names(blocks), value=selected), msg)


def form_reload(blocks, name):
    # Values for RELOAD_OUTPUTS: the unmodified form of block `name` after a bulk change (Rename category,
    # Move LoRA tags in ALL blocks) wrote it, as form_load but without the thumbnail / dropdown / status.
    values, hints = load_values(blocks, name)
    gen = new_gen()
    return (*values, None, signal("clean"), gen, gen, *hints)


def commit_save(plan, img):
    # Write a successful formsave plan: blocks.json (backup first, see storage) and the thumbnail
    # of the saved name (the form's image, or none).
    storage.save_blocks(plan["blocks"])
    if img is not None:
        storage.save_thumb(plan["name"], img)
    else:
        storage.delete_thumb(plan["name"])


def switch(target, unselect, loaded, touched, seen_gen, cur_gen, img, search_text, cat, cur_from,
           cur_backup, vals):
    # The one block-switch path (section 26) of a tile click, a dropdown pick and New
    # (target None = blank form). Values for SWITCH_OUTPUTS.
    #   1. stale (the form was replaced after this event was triggered) or not modified: load;
    #   2. modified and valid: save exactly like the Save button (formsave), except that removing
    #      a referenced sub-block does not ask twice (the status warns), then load;
    #   3. modified and invalid: refuse; nothing is written, the form stays, the dropdown shows
    #      the form's block again, the status shows the error.
    # `unselect`: clear the gallery's selected index (tile clicks), so the same tile fires select
    # again next time (see common.gallery_unselect).
    blocks = storage.load_blocks()
    stale = guard.is_stale(seen_gen, cur_gen)
    modified = not stale and guard.is_modified(blocks, loaded, vals, touched)
    plan = formsave.plan_form_save(blocks, vals, loaded, confirm=False) if modified else None
    action = guard.switch_action(stale, modified, plan and plan["error"])
    gallery_update = gallery_unselect() if unselect else gr.update()
    no_refresh = (gallery_update,) + tuple(gr.update() for _ in REFRESH_OUTPUTS[1:])
    if action == "refuse":
        return out(SWITCH_OUTPUTS, ("picker", gr.update(value=loaded)),
                   ("status", guard.refusal_message(plan["error"])), ("gallery", gallery_update))
    msg = ""
    if action == "save":
        commit_save(plan, img)
        blocks = plan["blocks"]
        msg = plan["message"]
    if target is None:
        msg = (msg + " " if msg else "") + "New block: fill in Name, Category and Text, then press Save."
    loaded_part = form_load(blocks, target, msg)
    if action != "save":
        return loaded_part + no_refresh
    return loaded_part + data_refresh(blocks, search_text, cat, cur_from, cur_backup)


def on_pick(target, loaded, touched, seen_gen, cur_gen, img, search_text, cat, cur_from, cur_backup,
            *vals):
    # picker.input (inputs PICK_INPUTS): a block picked by the user (Gradio 4.40 fires input only for
    # user selections, never for a value a handler sets, so no follow-up event has to be swallowed). The
    # user cannot empty this dropdown (no custom values); a None target only puts the dropdown back.
    if target is None:
        return out(SWITCH_OUTPUTS, ("picker", gr.update(value=loaded)))
    return switch(target, False, loaded, touched, seen_gen, cur_gen, img, search_text, cat, cur_from,
                  cur_backup, vals)


def on_new(loaded, touched, seen_gen, cur_gen, img, search_text, cat, cur_from, cur_backup, *vals):
    # New (inputs SWITCH_INPUTS): switch to the blank form.
    return switch(None, False, loaded, touched, seen_gen, cur_gen, img, search_text, cat, cur_from,
                  cur_backup, vals)


def on_gallery_select(evt: gr.SelectData, names, loaded, touched, seen_gen, cur_gen, img, search_text,
                      cat, cur_from, cur_backup, *vals):
    # Tile click (inputs TILE_INPUTS): maps the clicked index through the list that was rendered
    # (browser_names, a State, so its value is the one when this runs) and switches to that block
    # directly (no chained second step: the switch does not depend on the dropdown value, and a click
    # made before an earlier response arrived is caught by the form generation, see common._GEN). The
    # event data must be the first parameter: Gradio only injects it into positional
    # parameters before *vals.
    name = browser.name_at(names, evt.index)
    if name is None:
        return out(SWITCH_OUTPUTS, ("gallery", gallery_unselect()))
    if name not in storage.load_blocks():
        return out(SWITCH_OUTPUTS, ("gallery", gallery_unselect()),
                   ("status", f"`{name}` no longer exists. Press ↻ to refresh the list."))
    return switch(name, True, loaded, touched, seen_gen, cur_gen, img, search_text, cat, cur_from,
                  cur_backup, vals)


def on_reload(loaded):
    # Reload (section 26), outputs FORM_OUTPUTS: the loaded block as saved on disk, or the blank form for
    # a new block (also when the loaded block no longer exists). No confirmation; the thumbnail-touched
    # flag is cleared with the rest of the form.
    blocks = storage.load_blocks()
    if loaded is not None and loaded in blocks:
        return form_load(blocks, loaded, f"Reloaded `{loaded}` (changes discarded).")
    return form_load(blocks, None, "Cleared the new block form.")


def on_save(loaded, pending, seen_gen, cur_gen, img, *vals):
    # Outputs: SAVE_OUTPUTS. Inputs: SAVE_INPUTS (loaded_block, pending_subs, form_gen_seen, form_gen,
    # thumb, then FORM_INPUTS). The whole rule (validation, the new data, the status, the two-step
    # confirm for removing a referenced sub-block) is formsave.plan_form_save, shared with the
    # auto-save of a block switch.
    # Stale save (section 23a fix 6): if the form was reloaded / blanked after Save was pressed
    # (another handler ran first), the values sent are still saved, but the response writes
    # only the dropdown's choices and the status: the form that is shown now (e.g. the blank
    # form of New, maybe already typed into) and its loaded block are left alone.
    # Section 24 fix 1: a successful save brings the hint lines (new counts) in this same
    # response instead of chained requests.
    blocks = storage.load_blocks()
    plan = formsave.plan_form_save(blocks, vals, loaded, pending=pending, confirm=True)
    if plan["error"]:
        return out(SAVE_OUTPUTS, ("status", plan["error"]), ("pending_subs", plan["pending"]))
    commit_save(plan, img)
    n, candidate = plan["name"], plan["blocks"]
    if guard.is_stale(seen_gen, cur_gen):
        return out(SAVE_OUTPUTS, ("picker", gr.update(choices=block_names(candidate))),
                   ("status", plan["message"]), ("pending_subs", None))
    # Rows reloaded from the saved block: compacted, and each row's identity is its saved name.
    rows = rows_to_values(subrows.rows_from_block(candidate[n]))
    f = form_fields(vals)
    # Hint lines for the form as it is shown after the save (category / block slot as typed,
    # the reloaded rows' slots).
    hints = hint_values([f[k] for k in FORM_COMPONENTS] + rows, candidate)
    return (gr.update(choices=block_names(candidate), value=n), plan["message"],
            weights.chance_line(candidate, n, (f["category"] or "").strip()), None, *rows,
            n, False, signal("clean"), *hints)
