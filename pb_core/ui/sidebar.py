"""BROWSER sidebar handlers: search / category filter, Enable shown / Disable shown.

The tile click itself is a block switch (form.on_gallery_select).
"""
import gradio as gr

from .. import browser, bulk, storage
from .common import browser_values, chance_preview


def on_browser(search_text, cat):
    # Outputs: BROWSER_OUTPUTS (gallery, browser_names, browser_note, cat_filter); see
    # common.browser_values. The gallery's selected index is left as it is.
    return browser_values(storage.load_blocks(), search_text, cat)


def make_bulk_active(value):
    # Handler of Enable shown (value True) / Disable shown (value False).
    def on_bulk_active(names, n, c, w, act, loaded, search_text, cat):
        # Outputs: BULK_ACTIVE_OUTPUTS (status, active, chance). Inputs: BULK_ACTIVE_INPUTS.
        # Acts on the names listed in the browser (browser_names). Saves once, only if something
        # changes. If the form's block changed, its Active checkbox follows (so the form is not
        # "modified" by it); the chance line is recomputed (the pool changed). When the gallery was
        # capped (search_text / cat match more blocks), the status says so.
        blocks = storage.load_blocks()
        listed = len(names or [])
        total = len(browser.shown_names(blocks, search_text, cat, storage.thumb_path))
        more = bulk.capped_more(listed, total, browser.MAX_TILES)
        new_blocks, changed = bulk.set_active(blocks, names or [], value)
        # The hint lines need no refresh: Active changes no category or slot count.
        if not changed:
            return bulk.active_status(value, 0, 0, listed, more), gr.update(), gr.update()
        storage.save_blocks(new_blocks)
        shown = {x for x in (names or []) if isinstance(blocks.get(x), dict)}
        msg = bulk.active_status(value, len(changed), len(shown) - len(changed), listed, more)
        if loaded in changed:
            act = value
            act_update = gr.update(value=value)
        else:
            act_update = gr.update()
        return msg, act_update, chance_preview(n, c, w, act)
    return on_bulk_active
