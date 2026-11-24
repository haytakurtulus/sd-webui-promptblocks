"""Scenario: design notes section 23a (management tab fixes) in the real management tab.

Starts preview_tab.py with every save slowed down by PB_SLOW_SAVE seconds (default 0.6; like a busy Forge),
so ordering problems show up, and a headless browser; both are stopped at the end. Every wait is a
condition wait (scenario_lib.idle). Exit code 0 = all passed.
"""
import asyncio
import json
import os
import time

from scenario_lib import (BLANK_SUBS, DATA_FILE, F, after_event, check_page_errors, expect, fail, finish, idle,
                          load_tab, open_more, pick_in, press, run_part, sent, settle, tile, type_real, wait_for)

SLOW = os.environ.get("PB_SLOW_SAVE", "0.6")
NAME = "#pb_name textarea, #pb_name input"


async def main(b):
    await load_tab(b)

    # Fix 3: status cleared by a real load; New keeps its own message.
    await tile(b, "saber")
    await press(b, "#pb_save_btn")
    expect("1 save saber: status", await F(b), status_has="Saved saber")
    await tile(b, "rin")
    expect("2 load rin: status cleared", await F(b), name="rin", status="")
    await press(b, "#pb_new_btn")
    expect("3 New keeps its message", await F(b), name="", status_has="New block:")

    # Tile loads (fix 4's panel check went away with the panel, section 27).
    await tile(b, "swimsuit")
    expect("4 tile swimsuit loads", await F(b), name="swimsuit", text_has="swimsuit")
    await tile(b, "runscene")
    expect("5 tile runscene loads", await F(b), name="runscene", text_has="running, motion blur")

    # Fix 2: category hint count right after saving a new block in an existing category.
    await press(b, "#pb_new_btn")
    await type_real(b, NAME, "zzA")
    await type_real(b, "#pb_category input", "PCharacter")
    await type_real(b, "#pb_text textarea", "zz text")
    # The Category value is committed on blur (custom value), which sends its change event.
    await b.click("#pb_text textarea")
    ok = await wait_for(b, "return (document.querySelector('#pb_block_group .pb-hintline').innerText || '')"
                           ".trim() === 'Existing category (3 blocks).';", 30)
    await settle(b)
    expect("6 typed new block in PCharacter: hint before save", await F(b),
           hint="Existing category (3 blocks).")
    if not ok:
        fail("6 hint never showed the count")
    await press(b, "#pb_save_btn")
    expect("7 after Save: hint counts the new block", await F(b), status_has="Saved zzA", picker="zzA",
           hint="Existing category (4 blocks).")

    # Fix 5: health report lists a block that calls its own category (written into the SCRATCH data file).
    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)
    data["blocks"]["mirror"] = {"category": "PPose", "text": "pose, %PPose"}
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    await open_more(b)
    await press(b, "#pb_health_btn")
    expect("8 health report: self-referencing category", await F(b),
           health_has="Blocks that call their own category", status_has="Health check")
    st = await F(b)
    expect("9 health report names mirror and %PPose", st, health_has="mirror: %PPose is this block's own category")

    # Fix 6: Save, then New within ~100 ms, then typing (real clicks + trusted typing). The typing starts
    # as soon as the blank form is shown, while Save's follow-up chain (browser, choices, backups) is
    # still queued behind New: what a user does who types right away into the new form.
    for i, (start_block, edit) in enumerate((("saber", False), ("saber", True), ("rin", False))):
        await tile(b, start_block)
        if edit:
            await type_real(b, "#pb_text textarea", ", EDIT")
            await settle(b)
        t0 = time.time()
        before = await sent(b)
        await b.click("#pb_save_btn")
        await wait_for(b, "return (window.__pb ? window.__pb.sent : 0) > %d;" % before, 30)
        await b.click("#pb_new_btn")
        blank = await wait_for(b, "const n = document.querySelector('#pb_name textarea, #pb_name input').value;"
                                  "const l = document.querySelector('#pb_lora textarea, #pb_lora input').value;"
                                  "return n === '' && l === '';", timeout=30)
        t_blank = round(time.time() - t0, 2)
        # What a click on the Category field hits right now (a status overlay would swallow it).
        hit = await b.js("const e = document.querySelector('#pb_category input'); const r = e.getBoundingClientRect();"
                         "const h = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);"
                         "return h === e ? 'input' : (h ? h.tagName + '.' + h.className : null);")
        # Type at once (the Save chain is still running): Category, then Name.
        await type_real(b, "#pb_category input", "Foo", per_char=0.1)
        await type_real(b, NAME, "zz%d" % i)
        await settle(b)
        st = await F(b)
        st["t_blank"] = t_blank
        st["hit"] = hit
        expect("10.%d Save(%s%s) then New, then typing: blank form, typed text intact"
               % (i, start_block, " edited" if edit else ""), st,
               name="zz%d" % i, category="Foo", text="", lora="", subs=BLANK_SUBS, picker="")
        if not blank:
            fail("10.%d form never blank" % i)
        # Discard the typed (invalid: no Text) new form for the next round.
        await press(b, "#pb_reload_btn")

    # Fix 6, stale Save: Save, New, Save within ~100 ms each. The second Save runs after New (it was
    # triggered on the old form): it still saves, but must not write saber's rows into the blank form.
    await tile(b, "saber")
    before = await sent(b)
    await b.click("#pb_save_btn")
    await asyncio.sleep(0.1)  # the reproduction's timing (clicks ~100 ms apart), not a wait
    await b.click("#pb_new_btn")
    await asyncio.sleep(0.1)
    # The floating Save (own listener; the top one is still pending and trigger_mode "once" would drop
    # a second click on it).
    await b.click("#pb_save_fab")
    # All three events must have been sent before waiting for idle.
    await wait_for(b, "return (window.__pb ? window.__pb.sent : 0) >= %d;" % (before + 3), 30)
    await after_event(b, before)
    events = await b.js("return window.__pb.sent;") - before
    st = await F(b)
    st["events"] = events
    expect("10.3 Save, New, Save: stale second Save leaves the blank form", st,
           name="", category="", text="", lora="", subs=BLANK_SUBS, picker="", status_has="Saved saber")
    await tile(b, "rin")
    expect("10.4 after the stale Save the form is the blank new form: a tile loads, nothing auto-saved",
           await F(b), name="rin", status="")

    # Fix 1: category merge in exactly two presses, REAL typing into To, then real clicks at once.
    await open_more(b)
    await pick_in(b, "#pb_cat_from", "Clothes", event=False)
    await type_real(b, "#pb_cat_to textarea, #pb_cat_to input", "PCharacter")
    await press(b, "#pb_cat_rename_btn")
    expect("11 merge, first press: warns", await F(b), status_has="will be merged into PCharacter")
    await press(b, "#pb_cat_rename_btn")
    expect("12 merge, second press: merged", await F(b), status_has="Merged Clothes (1 block) into PCharacter")
    with open(DATA_FILE, encoding="utf-8") as f:
        cat = json.load(f)["blocks"]["swimsuit"]["category"]
    expect("13 swimsuit moved on disk", {"category": cat}, category="PCharacter")

    await check_page_errors(b)


if __name__ == "__main__":
    run_part("tab", main, env={"PB_SLOW_SAVE": SLOW})
    finish()
