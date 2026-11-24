"""Scenario: design notes section 21 small fixes in the real management tab - gallery highlight of the
loaded block, form reload after Rename category, placeholder tile cleanup on Delete.

Starts preview_tab.py and a headless browser itself (both stopped at the end). Every wait is a condition
wait (scenario_lib.idle). Exit code 0 = all passed.
"""
import json
import os

from scenario_lib import (TILE_DIR, S, check_page_errors, ctrl_s, expect, finish, idle, load_tab, open_more,
                          pick_in, press, run_part, settle, tile, type_into, wait_for)

HL = """return {hl: [...document.querySelectorAll('#pb_gallery button.thumbnail-item.pb-loaded')]
                     .map(b => (b.querySelector('img') || {}).alt),
                sel: document.querySelectorAll('#pb_gallery button.thumbnail-item.selected').length,
                tiles: document.querySelectorAll('#pb_gallery button.thumbnail-item').length};"""


# True once the promptblocks_*.js files has applied the highlight for the dropdown's current value (it does so 60 ms
# after a change, with a 500 ms poll as a safety net): exactly the tiles named like the dropdown value.
HL_SETTLED = """const v = (document.querySelector('#pb_picker input').value || '').trim();
const name = btn => ((btn.querySelector('img') || {}).alt || '').trim().split(/\\s+/)[0];
return [...document.querySelectorAll('#pb_gallery button.thumbnail-item')]
  .every(btn => btn.classList.contains('pb-loaded') === (!!v && name(btn) === v));"""


async def state(b):
    await idle(b)
    await wait_for(b, HL_SETTLED, 10)  # on timeout the expectations below report the wrong highlight
    st = await S(b)
    st.update(await b.js(HL))
    return st


async def clear_and_type(b, selector, text):
    # Tab fields: select the whole value, then type (or clear with real Backspace); then wait until idle.
    await b.click(selector)
    await b.js("const e = document.querySelector(%s); e.focus(); e.select(); return 1;" % json.dumps(selector))
    if text:
        await b.cmd("Input.insertText", text=text)
    else:
        for t in ("rawKeyDown", "keyUp"):
            await b.cmd("Input.dispatchKeyEvent", type=t, key="Backspace", code="Backspace", windowsVirtualKeyCode=8)
    await settle(b)


async def main(b):
    await load_tab(b)

    expect("1 initial: nothing highlighted", await state(b), hl=[], tiles=5)
    await tile(b, "saber")
    expect("2 tile saber", await state(b), hl=["saber"], sel=0, picker="saber")
    await pick_in(b, "#pb_picker", "rin")
    expect("3 dropdown rin", await state(b), hl=["rin"], name="rin")

    # A refused switch (invalid form: Text emptied) keeps the highlight on the form's block.
    await clear_and_type(b, "#pb_text textarea", "")
    await tile(b, "swimsuit")
    expect("4 refused switch keeps highlight on rin", await state(b), hl=["rin"], sel=0, name="rin",
           status_has="Text cannot be empty.")
    await press(b, "#pb_reload_btn")
    expect("5 Reload: saved text back, highlight stays", await state(b), hl=["rin"], text_has="tohsaka rin",
           dirty=False)
    await type_into(b, "#pb_text textarea", ", EDIT")
    await ctrl_s(b)
    expect("6 save keeps highlight", await state(b), hl=["rin"], status_has="Saved", dirty=False)

    # "saku", not "sa": since section 40 the search also looks into the text, and rin's has "tohsaka".
    await clear_and_type(b, "#pb_search textarea, #pb_search input", "saku")
    expect("7 search 'saku' hides rin: no highlight", await state(b), hl=[], picker="rin")
    await tile(b, "sakura")
    expect("8 inactive tile '(off)' highlighted", await state(b), hl=["sakura (off)"], picker="sakura")
    await clear_and_type(b, "#pb_search textarea, #pb_search input", "")
    expect("9 search cleared: rebuild keeps highlight", await state(b), hl=["sakura (off)"], tiles=5)
    await press(b, "#pb_refresh_btn")
    expect("10 refresh keeps highlight", await state(b), hl=["sakura (off)"])

    await press(b, "#pb_new_btn")
    expect("11 New: nothing highlighted", await state(b), hl=[], name="")

    # Fix 6: a block whose text uses %PCharacter, then Rename category with a clean form.
    await type_into(b, "#pb_name textarea, #pb_name input", "pick")
    await type_into(b, "#pb_category input", "PPose")
    await type_into(b, "#pb_text textarea", "random %PCharacter")
    await ctrl_s(b)
    expect("12 new block pick saved and highlighted", await state(b), hl=["pick"], picker="pick",
           status_has="Saved", dirty=False)
    tile_file = os.path.join(TILE_DIR, "pick_128.png")
    expect("13 placeholder tile file for pick exists", {"exists": os.path.exists(tile_file)}, exists=True)

    await open_more(b)
    await pick_in(b, "#pb_cat_from", "PCharacter", event=False)
    await type_into(b, "#pb_cat_to textarea, #pb_cat_to input", "Chars")
    await press(b, "#pb_cat_rename_btn")
    expect("14 rename category, clean form: reloaded", await state(b), text="random %Chars",
           status_has="The form shows the updated `pick`".replace("`", ""), dirty=False, hl=["pick"])
    await tile(b, "rin")
    expect("15 switch after reload: loads, nothing to save", await state(b), name="rin", status="")

    await tile(b, "pick")
    await type_into(b, "#pb_text textarea", ", EDIT")
    await pick_in(b, "#pb_cat_from", "Chars", event=False)
    await type_into(b, "#pb_cat_to textarea, #pb_cat_to input", "Heroes")
    await press(b, "#pb_cat_rename_btn")
    expect("16 rename category, modified form: kept + warned", await state(b), text="random %Chars, EDIT",
           status_has="still shows", dirty=True, hl=["pick"])

    # Discard the edits (Reload) + delete pick: its placeholder tile goes away, others stay.
    await press(b, "#pb_reload_btn")
    expect("17 Reload: pick as saved (text has %Heroes)", await state(b), text="random %Heroes",
           hl=["pick"], dirty=False)
    await press(b, "#pb_delete_btn")
    # Section 33 B: every delete asks twice; the first press only asks.
    expect("18a delete pick, first press: asks to confirm", await state(b),
           status_has="Press Delete again to confirm.")
    await press(b, "#pb_delete_btn")
    st = await state(b)
    st["pick_tile"] = os.path.exists(tile_file)
    st["saber_tile"] = os.path.exists(os.path.join(TILE_DIR, "saber_128.png"))
    expect("18 delete pick: tile file removed, others kept, no highlight", st, pick_tile=False,
           saber_tile=True, hl=[], status_has="Deleted")

    await check_page_errors(b)


if __name__ == "__main__":
    run_part("tab", main)
    finish()
