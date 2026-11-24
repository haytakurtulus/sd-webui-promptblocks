"""TOOLS under "More actions": Duplicate, Rename, Delete, Rename category, Backups / Restore,
Move LoRA tags (form / all blocks), Set sub-blocks of shown blocks, Check all blocks; also the
"All Include | All Exclude | All Random" buttons of the Sub-blocks accordion (form only, section 37 B).

Two-step confirms (Delete, Restore, Rename category merge, LoRA in ALL blocks, sub-block modes) keep their key in a
gr.State; the key holds the data the warning was about, so no reset event is needed (section 23a fix 1).
"""
import gradio as gr

from .. import browser, bulk, guard, health, lora, parser, storage, subrows, subs, suggest
from .common import block_names, category_names, chance_preview, hint_values, out, signal
from .form import form_load, form_reload
from .groups import (CAT_RENAME_OUTPUTS, FORM_OUTPUTS, HINT_OUTPUTS, LORA_ALL_OUTPUTS, RENAME_OUTPUTS,
                     RESTORE_OUTPUTS, SUB_MODES_OUTPUTS, SUB_NAMES, form_fields)


def on_duplicate(n):
    # Outputs: DUPLICATE_OUTPUTS (picker, name, status, pending_delete, pending_subs, new_name,
    # loaded_block, form_epoch).
    # All other form fields (incl. thumbnail and sub-block rows) are left as they are. The form
    # becomes a NEW form (loaded_block None): it differs from the blank form, so it is modified,
    # which is correct (a block switch saves the copy, like Save). The dropdown is cleared so
    # Delete / Rename no longer target the original; a value set by a handler fires no input
    # event.
    blocks = storage.load_blocks()
    copy = subrows.duplicate_name(n, blocks)
    source = (n or "").strip() or "this form"
    msg = (f"Duplicate of `{source}`: Name set to `{copy}`. Edit anything, then press **Save** to "
           f"create the new block (the original stays unchanged).")
    return gr.update(value=None), copy, msg, None, None, "", None, signal("dirty")


def on_delete(n, pending):
    # Outputs: FORM_OUTPUTS (pending_delete is part of it). Inputs: DELETE_INPUTS. A successful delete
    # blanks the form.
    def keep(msg, pending_value=None):
        return out(FORM_OUTPUTS, ("status", msg), ("pending_delete", pending_value))

    n = (n or "").strip()
    if not n:
        return keep("Select a block in the dropdown first.")
    blocks = storage.load_blocks()
    if n not in blocks:
        return keep(f"No block named `{n}`.")
    # Every delete asks twice (section 33 B); a used block's message lists its warnings.
    # The confirm key names the block AND the data the warning was about: it stays valid as
    # long as both are unchanged (no event has to reset it), a change asks again.
    key = repr((n, guard.data_key(blocks)))
    if pending != key:
        return keep(suggest.delete_confirm_message(blocks, n), key)
    del blocks[n]
    storage.save_blocks(blocks)
    storage.delete_thumb(n)
    browser.remove_placeholders(n, storage.tile_cache_dir())
    return form_load(blocks, None, f"Deleted `{n}`.")


def on_rename(old, new, loaded, form_name):
    # Outputs: RENAME_OUTPUTS (picker, status, new_name, name, loaded_block). Inputs: RENAME_INPUTS
    # (picker, new_name, loaded_block, name).
    # The rename is saved data; the form is left as it is (with any edits). If the form belongs
    # to the renamed block, loaded_block follows it, and so does a Name field showing the old
    # name (so the form is not "modified" by the rename alone). The hint lines need no refresh
    # (no category / slot count changes).
    def fail(msg):
        return out(RENAME_OUTPUTS, ("status", msg))

    old, new = (old or "").strip(), (new or "").strip()
    if not old:
        return fail("Select a block in the dropdown first.")
    blocks = storage.load_blocks()
    if old not in blocks:
        return fail(f"No block named `{old}`.")
    if not parser.is_valid_name(new):
        return fail(f"Invalid new name: `{new}`")
    if new in blocks:
        return fail(f"A block named `{new}` already exists.")

    blocks[new] = blocks.pop(old)
    # ~old and ~old.sub, in block texts and sub-block texts.
    blocks, updated = subs.rename_block_refs(blocks, old, new)
    storage.save_blocks(blocks)
    storage.rename_thumb(old, new)
    browser.remove_placeholders(old, storage.tile_cache_dir())

    msg = f"Renamed `{old}` → `{new}`."
    if updated:
        msg += f" Updated references in: {', '.join(sorted(updated))}."
    if loaded != old:
        return out(RENAME_OUTPUTS, ("picker", gr.update(choices=block_names(blocks), value=loaded)),
                   ("status", msg), ("new_name", ""))
    name_update = new if (form_name or "").strip() == old else gr.update()
    return gr.update(choices=block_names(blocks), value=new), msg, "", name_update, new


def on_cat_rename(old, new, pending, loaded, touched, *vals):
    # Outputs: CAT_RENAME_OUTPUTS. Inputs: CAT_RENAME_INPUTS (cat_from, cat_to, pending_cat_rename,
    # loaded_block, thumb_touched, then FORM_INPUTS).
    # A merge (To already exists) needs a second press with the same plan. An unmodified form
    # whose block was moved or rewritten (%Old -> %New) is reloaded from disk. A modified form is
    # left as it is, except that a Category field showing the old name follows the rename (so a
    # later save does not move the block back) and the chance line is recomputed; if its texts
    # were rewritten on disk, the status warns.
    # The merge confirm is NOT reset by From / To change events (section 23a fix 1: a late
    # change event of To used to cancel the first press); the key holds From, To and both
    # counts, so a different plan asks again anyway.
    f = form_fields(vals)

    def keep(msg, pending_value=None):
        return out(CAT_RENAME_OUTPUTS, ("status", msg), ("pending_cat_rename", pending_value))

    blocks = storage.load_blocks()
    check = bulk.check_category_rename(blocks, old, new)
    if check["error"]:
        return keep(check["error"])
    old, new = check["old"], check["new"]
    if check["merge"]:
        key = repr((old, new, check["moved"], check["existing"]))
        if pending != key:
            return keep(check["warning"], key)
    modified = guard.is_modified(blocks, loaded, vals, touched)
    new_blocks, moved, rewritten = bulk.rename_category(blocks, old, new)
    storage.save_blocks(new_blocks)
    if check["merge"]:
        msg = (f"Merged `{old}` ({len(moved)} block{'' if len(moved) == 1 else 's'}) into `{new}` "
               f"(now {bulk.category_size(new_blocks, new)} blocks).")
    else:
        msg = (f"Renamed category `{old}` → `{new}` "
               f"({len(moved)} block{'' if len(moved) == 1 else 's'}).")
    if rewritten:
        msg += (f" Rewrote `{parser.CATEGORY_SYMBOL}{old}` → `{parser.CATEGORY_SYMBOL}{new}` in: "
                + ", ".join(rewritten) + ".")
    choices = category_names(new_blocks)
    if loaded is not None and (loaded in rewritten or loaded in moved):
        if not modified:
            # Unmodified form of a changed block: show the saved version.
            return (msg + f" The form shows the updated `{loaded}`.", None,
                    gr.update(choices=choices, value=None), "", *form_reload(new_blocks, loaded))
        if loaded in rewritten:
            msg += (f" ⚠ The open form (changes kept) still shows `{parser.CATEGORY_SYMBOL}{old}` "
                    f"in its texts; change it to `{parser.CATEGORY_SYMBOL}{new}` before saving, or "
                    f"press Reload.")
    form_c = (f["category"] or "").strip()
    if form_c == old:
        cat_update = gr.update(choices=choices, value=new)
        form_c = new
    else:
        cat_update = gr.update(choices=choices)
    # Hint lines from the form as shown now (its Category may just have followed the rename).
    hints = hint_values(list(dict(f, category=form_c).values()), new_blocks)
    return out(CAT_RENAME_OUTPUTS, ("status", msg), ("pending_cat_rename", None), ("category", cat_update),
               ("chance", chance_preview(f["name"], form_c, f["weight"], f["active"])),
               ("cat_from", gr.update(choices=choices, value=None)), ("cat_to", ""),
               *zip(HINT_OUTPUTS, hints))


def on_restore(file_name, pending):
    # Outputs: RESTORE_OUTPUTS (FORM_OUTPUTS, pending_restore, backups_dd). Inputs: RESTORE_INPUTS.
    # First press asks for confirmation, second press (same backup, same current data) restores.
    # The key is (backup file, guard.data_key(current blocks)): choosing another backup or saving
    # anything in between asks again, without any reset events (section 23a fix 1). After a
    # restore the form is cleared like New (the selected block may not exist in the restored data).
    def keep(msg, pending_value=None, backups_update=None):
        return out(RESTORE_OUTPUTS, ("status", msg), ("pending_restore", pending_value),
                   ("backups_dd", backups_update or gr.update()))

    if not file_name:
        return keep("Select a backup in the *Backups* dropdown first.")
    entry = next((e for e in storage.list_backups() if e["file"] == file_name), None)
    if entry is None:
        return keep(f"Backup `{file_name}` no longer exists.",
                    backups_update=gr.update(choices=storage.backup_choices(), value=None))
    if entry["count"] is None:
        return keep(f"Backup from {entry['time']} cannot be read; nothing restored.")
    current = storage.load_blocks()
    key = repr((file_name, guard.data_key(current)))
    if pending != key:
        now = len(current)
        return keep(f"⚠ Restore the backup from {entry['time']} ({entry['count']} "
                    f"block{'' if entry['count'] == 1 else 's'})? This "
                    f"replaces all current blocks ({now} now); the current state is backed up "
                    f"first. **Press Restore backup again to confirm.**", key)
    try:
        blocks = storage.restore_backup(file_name)
    except ValueError as e:
        return keep(f"Restore failed: {e}")
    msg = (f"Restored the backup from {entry['time']} "
           f"({len(blocks)} block{'' if len(blocks) == 1 else 's'}). "
           f"The previous state was backed up first (see *Backups*).")
    return (*form_load(blocks, None, msg), None, gr.update(choices=storage.backup_choices(), value=None))


def on_lora_form(t, lo):
    # Outputs: LORA_FORM_OUTPUTS (text, lora_box, status, form_epoch). Inputs: LORA_FORM_INPUTS.
    # Acts on the form only (no save, no confirm): the form is now modified (a block switch would
    # save it), and the Save marker is set.
    clean, tags = lora.split_lora_tags(t or "")
    if not tags:
        return gr.update(), gr.update(), "No LoRA tags in Text.", gr.update()
    msg = ("Moved to the LoRA box: " + ", ".join(f"`{tag}`" for tag in tags)
           + ". Press **Save** to keep it.")
    if not clean.strip():
        msg += " ⚠ Text is now empty; Save needs a non-empty Text."
    return clean, lora.merge_lora(lo or "", tags), msg, signal("dirty")


def make_sub_all(mode):
    # Section 37 B: handler of one "All <mode>" button. Outputs: SUB_ALL_OUTPUTS (the mode dropdowns,
    # status, form_epoch). Inputs: SUB_ALL_INPUTS (names, texts, modes). Like on_lora_form it acts on the
    # form only (no save, no confirm): filled rows get `mode`, blank rows keep theirs; the Save marker is
    # set only when a mode changed (the guard then sees a modified form, so a block switch saves it).
    def on_sub_all(*vals):
        n = len(SUB_NAMES)
        names, texts, modes = vals[:n], vals[n:2 * n], vals[2 * n:3 * n]
        new, changed, filled = subrows.set_row_modes(names, texts, modes, mode)
        msg = subrows.row_modes_status(mode, changed, filled)
        if not changed:
            return (*[gr.update()] * n, msg, gr.update())
        return (*new, msg, signal("dirty"))
    return on_sub_all


def on_lora_all(pending, loaded, touched, *vals):
    # Outputs: LORA_ALL_OUTPUTS (picker, status, pending_lora_all, then the form reload values).
    # Inputs: LORA_ALL_INPUTS (pending_lora_all, loaded_block, thumb_touched, FORM_INPUTS).
    # First press reports what would change, second press (same plan on the same data: the key
    # holds the changed names and guard.data_key, no reset events needed) saves once. If the
    # loaded block changed and the form is not modified, it is reloaded from disk; a modified
    # form is kept and the status warns instead.
    def keep(msg, pending_value=None, picker_update=None):
        return out(LORA_ALL_OUTPUTS, ("picker", picker_update or gr.update()), ("status", msg),
                   ("pending_lora_all", pending_value))

    blocks = storage.load_blocks()
    new_blocks, changed, skipped = lora.migrate_all(blocks)
    skip_msg = ""
    if skipped:
        skip_msg = (" Skipped (Text would be empty, only LoRA tags): "
                    + ", ".join(f"`{s}`" for s in skipped)
                    + " — use *Move LoRA tags to LoRA box* on them and add some Text.")
    if not changed:
        return keep("No block has LoRA tags in its Text." + skip_msg)
    key = repr((changed, guard.data_key(blocks)))
    if pending != key:
        return keep(f"⚠ {len(changed)} block(s) would change: "
                    + ", ".join(f"`{c}`" for c in changed)
                    + ". LoRA tags are moved from each block's Text to its LoRA box (sub-block texts "
                      "are not changed); a backup is made first. "
                      "**Press Move LoRA tags in ALL blocks again to confirm.**" + skip_msg,
                    key)
    modified = guard.is_modified(blocks, loaded, vals, touched)
    storage.save_blocks(new_blocks)
    msg = f"Moved LoRA tags in {len(changed)} block(s): " + ", ".join(f"`{c}`" for c in changed) + "."
    choices = gr.update(choices=block_names(new_blocks))
    if loaded not in changed:
        return keep(msg + skip_msg, picker_update=choices)
    if modified:
        msg += (f" ⚠ The form still shows the OLD version of `{loaded}` with your changes: saving "
                f"it (Save, or opening another block) would undo the move for this block. Press "
                f"Reload to see the moved version.")
        return keep(msg + skip_msg, picker_update=choices)
    # Unmodified form of a changed block: show the migrated version (hint lines recomputed with it).
    msg += f" The form shows the updated `{loaded}`."
    return (choices, msg + skip_msg, None, *form_reload(new_blocks, loaded))


def on_sub_modes(names, mode, pending, search_text, cat, loaded, touched, *vals):
    # Outputs: SUB_MODES_OUTPUTS (status, pending_sub_modes, then the form reload values).
    # Inputs: SUB_MODES_INPUTS (browser_names, sub_mode_bulk, pending_sub_modes, search, cat_filter,
    # loaded_block, thumb_touched, FORM_INPUTS).
    # Section 36 B: acts on the names listed in the browser (the same list as Enable shown). First
    # press reports N sub-blocks in M blocks, second press (same plan on the same data: the key holds
    # the changed names, the mode and guard.data_key, no reset events needed) saves once. Same form
    # rule as Move LoRA tags in ALL blocks: an unmodified form of a changed block is reloaded from
    # disk; a modified form is kept and the status warns.
    def keep(msg, pending_value=None):
        return out(SUB_MODES_OUTPUTS, ("status", msg), ("pending_sub_modes", pending_value))

    mode = mode if mode in subs.MODES else bulk.BULK_INITIAL_MODE
    names = list(names or [])
    blocks = storage.load_blocks()
    listed = len(names)
    total = len(browser.shown_names(blocks, search_text, cat, storage.thumb_path))
    more = bulk.capped_more(listed, total, browser.MAX_TILES)
    new_blocks, changed, count = bulk.set_sub_modes(blocks, names, mode)
    if not changed:
        return keep(bulk.sub_modes_status(mode, 0, 0, listed, more))
    key = bulk.sub_modes_key(blocks, changed, mode)
    if pending != key:
        return keep(bulk.sub_modes_confirm(mode, count, len(changed), listed, more), key)
    modified = guard.is_modified(blocks, loaded, vals, touched)
    storage.save_blocks(new_blocks)
    msg = bulk.sub_modes_status(mode, count, len(changed), listed, more)
    if loaded not in changed:
        return keep(msg)
    if modified:
        return keep(msg + f" ⚠ The form still shows the OLD modes of `{loaded}` with your changes: saving "
                          f"it (Save, or opening another block) would undo the change for this block. "
                          f"Press Reload to see the new modes.")
    # Unmodified form of a changed block: show the saved version.
    return (msg + f" The form shows the updated `{loaded}`.", None, *form_reload(new_blocks, loaded))


def on_health():
    # Outputs: HEALTH_OUTPUTS (status, health_md, health_acc). Read-only (saved data + thumbnail
    # folder); the report accordion is opened when it is filled.
    try:
        blocks = storage.load_blocks()
    except Exception as e:
        msg = f"Health check failed: blocks.json cannot be read ({type(e).__name__}: {e})."
        return msg, msg, gr.update(open=True)
    findings = health.report(blocks, health.thumb_names())
    count = len(blocks) if isinstance(blocks, dict) else 0
    return (health.summary_line(findings), health.format_report(findings, count),
            gr.update(open=True))
