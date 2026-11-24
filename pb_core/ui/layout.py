"""LAYOUT of the management tab: creates every component, in DOM order, and nothing else.

build() must run inside the tab's `gr.Blocks` context. It returns a Components object: every component
under a key (the attribute name, e.g. `c.picker`, `c.sub_name_0`). The keys are the names used by
groups.py; no event listener is attached here (see wiring.py).
"""
import gradio as gr

from .. import adetailer, browser, bulk, storage, subrows, subs
from .common import (MODE_CHOICES, N_SUBS, block_names, browser_gallery, category_names, rows_to_values,
                     slot_choices)
from .groups import AD_TEXTS
from .help_text import CHEAT_SHEET

# Column widths of the sub-block rows; the header line uses the same values so the titles line up.
_SUB_COLS = {"name": (2, 100), "text": (5, 160), "mode": (2, 110), "chance": (1, 58), "slot": (2, 110)}
_MOVE_BTN_WIDTH = 36


class Components:
    """Every component of the tab by key: `c.add(key, component)` while building, `c.<key>` to read one,
    `c.pick(keys)` for the component list of a groups.py key list. Keys are unique."""

    def __init__(self):
        self._all = {}

    def add(self, key, component):
        assert key not in self._all, key
        self._all[key] = component
        return component

    def __getattr__(self, key):
        try:
            return self.__dict__["_all"][key]
        except KeyError:
            raise AttributeError(key) from None

    def pick(self, keys):
        return [self._all[k] for k in keys]


def build():
    c = Components()
    _states(c)
    initial_blocks = storage.load_blocks()
    initial_browser = browser_gallery(initial_blocks, "", browser.ALL_CATEGORIES)

    # 1. Action bar (top, not sticky) + status line. The floating Save button is at the end.
    _action_bar(c, initial_blocks)

    # 2. Cheat sheet.
    with gr.Accordion("How it works", open=False, elem_id="pb_help"):
        gr.Markdown(CHEAT_SHEET)

    # 3. Three columns: block browser | form | thumbnail + actions.
    with gr.Row(elem_id="pb_main"):
        _browser_column(c, initial_blocks, initial_browser)
        _form_column(c, initial_blocks)
        _right_column(c, initial_blocks)

    # 3b. Health report (section 18): full width under the three columns, filled by Check all blocks.
    with gr.Accordion("Health report", open=False, elem_id="pb_health") as health_acc:
        c.add("health_acc", health_acc)
        c.add("health_md", gr.Markdown("Press *Check all blocks* (under *More actions*) to run the check.",
                                       elem_id="pb_health_report"))

    _footer(c)
    return c


def _states(c):
    c.add("pending_delete", gr.State(None))
    # File name of the backup whose Restore was pressed once (two-step confirm, like Delete).
    c.add("pending_restore", gr.State(None))
    # Key of the "Move LoRA tags in ALL blocks" plan that was announced by the first press.
    c.add("pending_lora_all", gr.State(None))
    # Key of the category merge that was announced by the first Rename category press.
    c.add("pending_cat_rename", gr.State(None))
    # Key of the "Set sub-blocks of shown blocks" plan that was announced by the first press (section 36 B).
    c.add("pending_sub_modes", gr.State(None))
    # The block the form belongs to (None = a new / blank / duplicated form). "Modified" (section 26)
    # compares the form with this block as saved on disk; it cannot be derived from the dropdown,
    # whose browser value is the user's NEW pick when the dropdown's input event runs.
    c.add("loaded_block", gr.State(None))
    # Whether the user changed the thumbnail since the form was loaded / saved / blanked: the image
    # itself is not compared with the file on disk.
    c.add("thumb_touched", gr.State(False))
    # Form generation (see common._GEN): the server's value; its browser-side copy (form_gen_seen) is a
    # hidden Textbox created in _footer.
    c.add("form_gen", gr.State("0"))


def _action_bar(c, blocks):
    with gr.Column(elem_id="pb_actionbar"):
        with gr.Row(elem_id="pb_actionbar_row"):
            c.add("picker", gr.Dropdown(label="Block", choices=block_names(blocks),
                                        value=None, interactive=True, scale=4, container=False,
                                        elem_id="pb_picker"))
            c.add("new_btn", gr.Button("New", scale=0, min_width=90, elem_id="pb_new_btn",
                                       elem_classes=["pb-bar-btn"]))
            c.add("save_btn", gr.Button("Save", variant="primary", scale=0, min_width=90,
                                        elem_id="pb_save_btn", elem_classes=["pb-bar-btn"]))
            c.add("reload_btn", gr.Button("Reload", scale=0, min_width=90, elem_id="pb_reload_btn",
                                          elem_classes=["pb-bar-btn"]))
            c.add("refresh_btn", gr.Button("↻", scale=0, min_width=44, elem_id="pb_refresh_btn",
                                           elem_classes=["pb-bar-btn", "pb-icon-btn"]))
        c.add("status", gr.Markdown("", elem_id="pb_status"))


def _browser_column(c, blocks, initial_browser):
    with gr.Column(scale=2, min_width=240, elem_id="pb_browser"):
        # Section 40: full-content search + quick filters (browser.filter_names).
        c.add("search", gr.Textbox(label="Search", placeholder="name or content; :off :nothumb :subs …",
                                   lines=1, max_lines=1, elem_id="pb_search"))
        c.add("cat_filter", gr.Dropdown(label="Category",
                                        choices=browser.category_filter_choices(blocks),
                                        value=browser.ALL_CATEGORIES, interactive=True, filterable=False,
                                        elem_id="pb_cat_filter"))
        c.add("gallery", gr.Gallery(value=initial_browser["items"], label="Blocks", show_label=False,
                                    columns=3, height=460, allow_preview=False, object_fit="cover",
                                    show_download_button=False, show_share_button=False,
                                    interactive=False, elem_id="pb_gallery"))
        c.add("browser_note", gr.Markdown(initial_browser["note"], elem_classes=["pb-hintline"],
                                          elem_id="pb_browser_note"))
        with gr.Row(elem_id="pb_browser_bulk"):
            c.add("enable_shown_btn", gr.Button("Enable shown", size="sm", min_width=0,
                                                elem_id="pb_enable_shown_btn"))
            c.add("disable_shown_btn", gr.Button("Disable shown", size="sm", min_width=0,
                                                 elem_id="pb_disable_shown_btn"))
        # The names in the order they were rendered: a clicked index maps back through this.
        c.add("browser_names", gr.State(initial_browser["names"]))


def _form_column(c, blocks):
    with gr.Column(scale=4, elem_id="pb_left"):
        with gr.Group(elem_id="pb_block_group"):
            with gr.Row():
                c.add("name", gr.Textbox(label="Name", elem_id="pb_name"))
                c.add("category", gr.Dropdown(label="Category", choices=category_names(blocks),
                                              value=None, allow_custom_value=True, interactive=True,
                                              elem_id="pb_category"))
            c.add("category_hint", gr.Markdown("", elem_classes=["pb-hintline"]))
            c.add("text", gr.Textbox(label="Text", lines=4, elem_id="pb_text"))
            c.add("lora_box", gr.Textbox(label="LoRA", lines=1, max_lines=1, placeholder="<lora:name:0.8>",
                                         info="Added once whenever this block or one of its sub-blocks "
                                              "is used",
                                         elem_id="pb_lora"))

        _adetailer_tabs(c)

        with gr.Accordion("Sub-blocks", open=True, elem_id="pb_subs"):
            _sub_mode_buttons(c)
            _sub_rows(c)
            c.add("sub_slot_hint", gr.Markdown("", elem_classes=["pb-hintline"]))

        with gr.Accordion("Random pick settings", open=False, elem_id="pb_pick_settings"):
            with gr.Row():
                c.add("weight", gr.Number(label="Weight", value=1, info="0 < weight ≤ 100, 1 = normal",
                                          elem_id="pb_weight"))
                c.add("block_slot", gr.Dropdown(label="Slot (block)", choices=slot_choices(),
                                                value=None, allow_custom_value=True, interactive=True,
                                                info="optional, e.g. outfit", elem_id="pb_block_slot"))
                c.add("active", gr.Checkbox(label="Active", value=True,
                                            info="in %Category picks", elem_id="pb_active"))
            c.add("chance", gr.Markdown("", elem_classes=["pb-hintline"]))
            c.add("block_slot_hint", gr.Markdown("", elem_classes=["pb-hintline"]))
            # Section 38: applied at Generate and in the preview (parser.expand).
            c.add("bans", gr.Textbox(label="Bans", lines=1, max_lines=1, placeholder="~happy, %PEmotion",
                                     info="Blocks (~name) or categories (%Category) that must not be used "
                                          "together with this block, comma separated.",
                                     elem_id="pb_bans"))
            c.add("bans_hint", gr.Markdown("", elem_classes=["pb-hintline"], elem_id="pb_bans_hint"))


def _adetailer_tabs(c):
    # Section 31a: one text per ADetailer tab (1st..4th), like ADetailer's own panel; keys ad_text_1..4
    # (groups.AD_TEXTS). Inside #pb_left, so typing sets the Save buttons' "modified" marker.
    with gr.Accordion("ADetailer", open=False, elem_id="pb_adetailer"):
        with gr.Tabs(elem_id="pb_adetailer_tabs"):
            for k, (key, label) in enumerate(zip(AD_TEXTS, adetailer.TAB_LABELS)):
                with gr.Tab(label, elem_id=f"pb_adetailer_tab_{k + 1}"):
                    c.add(key, gr.Textbox(
                        label=f"ADetailer {label}", show_label=False, lines=2,
                        placeholder=f"Added to ADetailer tab {k + 1} ({label}) when this block is used",
                        elem_id=f"pb_ad_text_{k + 1}"))


def _sub_mode_buttons(c):
    # Section 37 B: "All Include | All Exclude | All Random" for the open form, at the TOP of the accordion
    # (an accordion header cannot hold buttons in Gradio 4). Keys sub_all_<mode> (groups.SUB_ALL_BTNS).
    with gr.Row(elem_id="pb_subs_all"):
        for label, mode in MODE_CHOICES:
            c.add(f"sub_all_{mode}", gr.Button(f"All {label}", size="sm", scale=0, min_width=0,
                                               elem_id=f"pb_subs_all_{mode}", elem_classes=["pb-subs-all-btn"]))


def _sub_rows(c):
    # Header line + N_SUBS rows: name, text, mode, chance, slot, move up / down (keys as in groups.py).
    with gr.Row(elem_classes=["pb-subhead"]):
        for key, title in (("name", "Name"), ("text", "Text"), ("mode", "Mode"),
                           ("chance", "%"), ("slot", "Slot")):
            sc, mw = _SUB_COLS[key]
            with gr.Column(scale=sc, min_width=mw):
                gr.Markdown(title)
        with gr.Column(scale=0, min_width=2 * _MOVE_BTN_WIDTH + 8):
            gr.Markdown("Move")
    for i in range(N_SUBS):
        with gr.Row(elem_classes=["pb-subrow"], equal_height=True):
            sc, mw = _SUB_COLS["name"]
            c.add(f"sub_name_{i}", gr.Textbox(
                label=f"Sub-block {i + 1} name", show_label=False, container=False,
                placeholder="name", scale=sc, min_width=mw,
                elem_id=f"pb_sub_name_{i}"))
            sc, mw = _SUB_COLS["text"]
            c.add(f"sub_text_{i}", gr.Textbox(
                label=f"Sub-block {i + 1} text", show_label=False, container=False,
                placeholder="text", scale=sc, min_width=mw, elem_id=f"pb_sub_text_{i}"))
            sc, mw = _SUB_COLS["mode"]
            c.add(f"sub_mode_{i}", gr.Dropdown(
                choices=MODE_CHOICES, value=subs.NEW_ROW_MODE, label=f"Sub-block {i + 1} mode",
                show_label=False, container=False, interactive=True, filterable=False,
                scale=sc, min_width=mw, elem_id=f"pb_sub_mode_{i}"))
            sc, mw = _SUB_COLS["chance"]
            # Chance in percent, only used for Random (section 14); always visible.
            c.add(f"sub_chance_{i}", gr.Number(
                value=subs.DEFAULT_CHANCE, label=f"Sub-block {i + 1} chance (%)",
                show_label=False, container=False, precision=0,
                # No minimum / maximum here: Gradio would reject an out-of-range value
                # on EVERY event that reads the rows (also the move buttons) with its own
                # error. Save validates the range and shows our message instead.
                scale=sc, min_width=mw, elem_id=f"pb_sub_chance_{i}"))
            sc, mw = _SUB_COLS["slot"]
            c.add(f"sub_slot_{i}", gr.Dropdown(
                label=f"Sub-block {i + 1} slot", show_label=False, container=False,
                choices=slot_choices(), value=None, allow_custom_value=True,
                interactive=True, scale=sc, min_width=mw, elem_id=f"pb_sub_slot_{i}"))
            c.add(f"up_btn_{i}", gr.Button("↑", size="sm", scale=0, min_width=_MOVE_BTN_WIDTH,
                                           elem_classes=["pb-move-btn"]))
            c.add(f"down_btn_{i}", gr.Button("↓", size="sm", scale=0, min_width=_MOVE_BTN_WIDTH,
                                             elem_classes=["pb-move-btn"]))


def _right_column(c, blocks):
    with gr.Column(scale=2, min_width=220, elem_id="pb_right"):
        c.add("thumb", gr.Image(label="Thumbnail", type="pil", height=200,
                                sources=["upload", "clipboard"], elem_id="pb_thumb"))
        c.add("use_last_btn", gr.Button("Use last generated image", elem_id="pb_use_last_btn"))
        with gr.Accordion("More actions", open=False, elem_id="pb_manage"):
            c.add("duplicate_btn", gr.Button("Duplicate", elem_id="pb_duplicate_btn"))
            gr.Markdown("Duplicate copies the form under a new name; Save creates the copy.",
                        elem_classes=["pb-hintline"])
            gr.Markdown("Rename / Delete act on the block selected in the *Block* dropdown.",
                        elem_classes=["pb-hintline"])
            c.add("new_name", gr.Textbox(label="New name", elem_id="pb_new_name"))
            c.add("rename_btn", gr.Button("Rename block", elem_id="pb_rename_btn"))
            c.add("delete_btn", gr.Button("Delete", variant="stop", elem_id="pb_delete_btn"))
            c.add("cat_from", gr.Dropdown(label="Rename category: from", choices=category_names(blocks),
                                          value=None, interactive=True, elem_id="pb_cat_from"))
            c.add("cat_to", gr.Textbox(label="To", lines=1, max_lines=1, elem_id="pb_cat_to"))
            c.add("cat_rename_btn", gr.Button("Rename category", elem_id="pb_cat_rename_btn"))
            gr.Markdown("Moves every block of the category and rewrites `%From` → `%To` in all "
                        "block and sub-block texts and bans. An existing *To* merges the two (asks first).",
                        elem_classes=["pb-hintline"])
            c.add("backups_dd", gr.Dropdown(label="Backups", choices=storage.backup_choices(), value=None,
                                            interactive=True, filterable=False,
                                            info="blocks.json before each save (newest first)",
                                            elem_id="pb_backups"))
            c.add("restore_btn", gr.Button("Restore backup", elem_id="pb_restore_btn"))
            gr.Markdown("Restore replaces all blocks with the chosen backup; the current state is "
                        "backed up first. Thumbnails are not part of backups.",
                        elem_classes=["pb-hintline"])
            c.add("lora_form_btn", gr.Button("Move LoRA tags to LoRA box", elem_id="pb_lora_form_btn"))
            c.add("lora_all_btn", gr.Button("Move LoRA tags in ALL blocks", elem_id="pb_lora_all_btn"))
            gr.Markdown("The first button moves `<lora:…>` / `<lyco:…>` tags from Text to the LoRA "
                        "box in the form only (press Save to keep it). The second one does it for "
                        "the main Text of every saved block (sub-block texts are not changed), "
                        "after a confirmation.",
                        elem_classes=["pb-hintline"])
            c.add("sub_mode_bulk", gr.Dropdown(label="Sub-block mode", choices=MODE_CHOICES,
                                               value=bulk.BULK_INITIAL_MODE, interactive=True, filterable=False,
                                               elem_id="pb_sub_mode_bulk"))
            c.add("sub_mode_bulk_btn", gr.Button("Set sub-blocks of shown blocks",
                                                 elem_id="pb_sub_mode_bulk_btn"))
            gr.Markdown("Sets the mode of every sub-block of the blocks listed in the browser (the "
                        "current search + category filter), after a confirmation. Only the mode "
                        "changes; a Random sub-block keeps its % chance.",
                        elem_classes=["pb-hintline"])
            c.add("health_btn", gr.Button("Check all blocks", elem_id="pb_health_btn"))
            gr.Markdown("Checks every saved block for unknown references, cycles, bans, LoRA tags in "
                        "Text, ignored values and thumbnails without a block. Read-only: nothing is "
                        "changed. The report opens below the columns.",
                        elem_classes=["pb-hintline"])


def _footer(c):
    # 4. Floating Save button (position: fixed via style.css; same handler and chain as the top
    # one). It is a child of this tab, so it is hidden together with the tab.
    c.add("save_fab", gr.Button("Save", variant="primary", scale=0, min_width=0, elem_id="pb_save_fab"))
    # Form signal for the Save buttons' "modified" marker (section 20): "clean N" / "dirty N", see
    # common.signal. Must stay in the DOM (visible=True) for the JS observer; hidden by style.css.
    c.add("form_epoch", gr.HTML('<span data-pb-form="clean 0">clean 0</span>', elem_id="pb_form_epoch"))
    # Browser-side copy of form_gen (see common._GEN). Hidden components still send their value as an
    # input.
    c.add("form_gen_seen", gr.Textbox("0", visible=False, elem_id="pb_form_gen"))
    # Initial identity meta: the value after the four row groups (the chance group follows it).
    c.add("sub_meta", gr.State(rows_to_values(subrows.rows_from_block({}))[4 * N_SUBS]))
    c.add("pending_subs", gr.State(None))
