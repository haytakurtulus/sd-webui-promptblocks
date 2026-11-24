"""Named input / output lists of the tab's listeners, as component KEYS (see layout.Components).

Each list is the exact order of one handler's parameters (inputs) or return values (outputs). Handlers
use these lists with common.out() to fill "only these outputs" responses; wiring.py turns them into
components with Components.pick(). A list is defined once here and reused everywhere.
"""
from .. import subrows, subs


def _rows(prefix):
    # Keys of one per-row group: prefix_0 .. prefix_{ROW_COUNT-1} (not common.N_SUBS: common imports us).
    return [f"{prefix}_{i}" for i in range(subrows.ROW_COUNT)]


SUB_NAMES = _rows("sub_name")
SUB_TEXTS = _rows("sub_text")
SUB_MODES = _rows("sub_mode")
SUB_CHANCES = _rows("sub_chance")
SUB_SLOTS = _rows("sub_slot")
UP_BTNS = _rows("up_btn")
DOWN_BTNS = _rows("down_btn")

# Same order as common.rows_to_values: names, texts, modes, slots, meta, chances.
SUB_COMPONENTS = SUB_NAMES + SUB_TEXTS + SUB_MODES + SUB_SLOTS + ["sub_meta"] + SUB_CHANCES
assert len(SUB_COMPONENTS) == len(subrows.rows_to_values(subrows.rows_from_block({}), with_chance=True))
SLOT_DROPDOWNS = ["block_slot"] + SUB_SLOTS
# ADetailer texts, tab 1st..4th (section 31a): layout keys ad_text_1 .. ad_text_4.
AD_TEXTS = [f"ad_text_{k + 1}" for k in range(len(subrows.ADETAILER_FIELDS))]
FORM_COMPONENTS = (["name", "category", "block_slot", "weight", "active", "chance", "text", "lora_box"] + AD_TEXTS
                   + ["bans"])
assert len(FORM_COMPONENTS) == len(subrows.FORM_FIELDS)

# The form values every "modified" check and every save reads (guard / formsave layout): the
# block fields (incl. the chance line, which is not compared) and the sub-block row values.
FORM_INPUTS = FORM_COMPONENTS + SUB_COMPONENTS


def form_fields(values):
    # FORM_INPUTS values (a handler's *vals) -> {component key: value}: form values by name, not position.
    assert len(values) == len(FORM_INPUTS)
    return dict(zip(FORM_INPUTS, values))


HINT_OUTPUTS = ["category_hint", "block_slot_hint", "sub_slot_hint", "bans_hint"]
GEN_OUTPUTS = ["form_gen", "form_gen_seen"]
# Outputs of every handler that loads a block into the form or blanks it (block switch, New,
# Reload, Delete, Restore): see form.form_load. The hint lines and the form generation are part of
# the same response as the form, so nothing lags behind a load (section 23a fixes 2, 4).
FORM_OUTPUTS = (FORM_COMPONENTS + SUB_COMPONENTS
                + ["thumb", "loaded_block", "thumb_touched", "pending_subs", "pending_delete", "new_name",
                   "form_epoch"]
                + GEN_OUTPUTS + HINT_OUTPUTS + ["picker", "status"])
# Refreshes a block switch brings in its own response when its auto-save wrote data (see
# refresh.data_refresh); the other data-changing handlers chain them instead (wiring.after_data_change).
REFRESH_INPUTS = ["search", "cat_filter", "cat_from", "backups_dd"]
REFRESH_OUTPUTS = ["gallery", "browser_names", "browser_note", "cat_filter", "cat_from", "backups_dd"]

# Block switch (section 26): tile click, dropdown pick, New.
SWITCH_INPUTS = ["loaded_block", "thumb_touched", "form_gen_seen", "form_gen", "thumb"] + REFRESH_INPUTS + FORM_INPUTS
SWITCH_OUTPUTS = FORM_OUTPUTS + REFRESH_OUTPUTS
PICK_INPUTS = ["picker"] + SWITCH_INPUTS
TILE_INPUTS = ["browser_names"] + SWITCH_INPUTS

SAVE_INPUTS = ["loaded_block", "pending_subs", "form_gen_seen", "form_gen", "thumb"] + FORM_INPUTS
SAVE_OUTPUTS = (["picker", "status", "chance", "pending_subs"] + SUB_COMPONENTS
                + ["loaded_block", "thumb_touched", "form_epoch"] + HINT_OUTPUTS)
DUPLICATE_OUTPUTS = ["picker", "name", "status", "pending_delete", "pending_subs", "new_name", "loaded_block",
                     "form_epoch"]
USE_LAST_OUTPUTS = ["thumb", "status", "thumb_touched", "form_epoch"]
THUMB_TOUCHED_OUTPUTS = ["thumb_touched", "form_epoch"]

# "More actions".
GUARD_INPUTS = ["loaded_block", "thumb_touched"] + FORM_INPUTS
DELETE_INPUTS = ["picker", "pending_delete"]
RENAME_INPUTS = ["picker", "new_name", "loaded_block", "name"]
RENAME_OUTPUTS = ["picker", "status", "new_name", "name", "loaded_block"]
RESTORE_INPUTS = ["backups_dd", "pending_restore"]
RESTORE_OUTPUTS = FORM_OUTPUTS + ["pending_restore", "backups_dd"]
LORA_FORM_INPUTS = ["text", "lora_box"]
LORA_FORM_OUTPUTS = ["text", "lora_box", "status", "form_epoch"]
LORA_ALL_INPUTS = ["pending_lora_all"] + GUARD_INPUTS
# Reload of an unmodified form after a bulk change (form.form_reload): the form, its signal and generation,
# and the hint lines (section 24 fix 1: a category rename changes the category counts).
RELOAD_OUTPUTS = FORM_INPUTS + ["pending_subs", "form_epoch"] + GEN_OUTPUTS + HINT_OUTPUTS
LORA_ALL_OUTPUTS = ["picker", "status", "pending_lora_all"] + RELOAD_OUTPUTS
CAT_RENAME_INPUTS = ["cat_from", "cat_to", "pending_cat_rename"] + GUARD_INPUTS
CAT_RENAME_OUTPUTS = ["status", "pending_cat_rename", "cat_from", "cat_to"] + RELOAD_OUTPUTS
# Set sub-blocks of shown blocks (section 36 B): the browser's listed names and filter, the mode, the
# pending confirm key, then the form (reload / keep rule as Move LoRA tags in ALL blocks).
SUB_MODES_INPUTS = ["browser_names", "sub_mode_bulk", "pending_sub_modes", "search", "cat_filter"] + GUARD_INPUTS
SUB_MODES_OUTPUTS = ["status", "pending_sub_modes"] + RELOAD_OUTPUTS
HEALTH_OUTPUTS = ["status", "health_md", "health_acc"]
# "All Include | All Exclude | All Random" of the open form (section 37 B): form only, like LORA_FORM_*.
SUB_ALL_BTNS = [f"sub_all_{m}" for m in subs.MODES]
SUB_ALL_INPUTS = SUB_NAMES + SUB_TEXTS + SUB_MODES
SUB_ALL_OUTPUTS = SUB_MODES + ["status", "form_epoch"]

# Browser sidebar.
BROWSER_INPUTS = ["search", "cat_filter"]
BROWSER_OUTPUTS = ["gallery", "browser_names", "browser_note", "cat_filter"]
BULK_ACTIVE_INPUTS = ["browser_names", "name", "category", "weight", "active", "loaded_block", "search",
                      "cat_filter"]
BULK_ACTIVE_OUTPUTS = ["status", "active", "chance"]

# Follow-up refreshes and field hints.
CATEGORIES_OUTPUTS = ["category", "cat_from"]
HINT_INPUTS = ["form_gen_seen", "form_gen", "category", "block_slot", "name", "bans"] + SUB_SLOTS
CHANCE_INPUTS = ["name", "category", "weight", "active"]
# The category also decides the Bans hint (own-category ban, section 38).
CATEGORY_CHANGED_INPUTS = CHANCE_INPUTS + ["bans"]
CATEGORY_CHANGED_OUTPUTS = ["category_hint", "chance", "bans_hint"]
BANS_HINT_INPUTS = ["name", "category", "bans"]
