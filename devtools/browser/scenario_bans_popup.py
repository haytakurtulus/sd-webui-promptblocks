"""Scenario: design notes section 39 - the autocomplete popup in the management tab's Bans box
(`#pb_bans`, a single-line Gradio Textbox, i.e. an <input>): ~ lists blocks, % lists categories, Enter /
mouse insert and dispatch `input` (Save marker, bans hint line), Esc closes, the popup sits at the caret,
and `~name.` / `~name*` open no sub-block / slot list there. A harness part checks that the prompt box
still lists sub-blocks after `~saber.` and slots after `~saber*`.

Starts preview_tab.py (with two extra scratch blocks, PB_EXTRA_BLOCKS) / harness_server.py and a headless
browser itself (all stopped at the end). Exit code 0 = all passed.
"""
import asyncio
import json

from scenario_lib import (S, check, check_page_errors, click_at, expect, finish, harness_load, idle, key,
                          load_tab, run_part, set_prompt, settle, tile, type_real, type_text, wait_for)

EXTRA = {
    "happy": {"category": "PEmotion", "text": "smile, happy",
              "subs": [{"name": "grin", "text": "grin", "mode": "include", "slot": "mouth"}]},
    "sad": {"category": "PEmotion", "text": "sad, tears"},
}

BANS = "#pb_bans input"
Q = json.dumps(BANS)
HINT = "return (document.querySelector('#pb_bans_hint') || {}).innerText.trim();"
OPEN = "return document.querySelector('.pb-popup').style.display === 'block';"
NAMES = "return [...document.querySelectorAll('.pb-popup .pb-item .pb-name')].map(e => e.textContent);"
ACTIVE = "return (document.querySelector('.pb-popup .pb-item.pb-active .pb-name') || {}).textContent || null;"
VALUE = "return document.querySelector(%s).value;" % Q


async def popup_names(b, timeout=5):
    ok = await wait_for(b, OPEN, timeout)
    return ok, await b.js(NAMES)


async def closed_after(b, delay=0.5):
    await asyncio.sleep(delay)
    return not await b.js(OPEN)


async def set_value(b, value):
    """Put `value` back into the Bans box (input event, like a user edit) and wait until idle."""
    await b.js("const e = document.querySelector(%s); e.value = %s;"
               "e.dispatchEvent(new Event('input', {bubbles: true})); return 1;" % (Q, json.dumps(value)))
    await settle(b)


async def part_tab(b):
    await load_tab(b)
    await tile(b, "saber")
    expect("T1 saber loaded, not modified", await S(b), name="saber", dirty=False)

    tag = await b.js("const e = document.querySelector('#pb_bans input, #pb_bans textarea');"
                     "return e ? e.tagName : null;")
    check(tag == "INPUT", "T2 the Bans box renders an <input> (Gradio 4 Textbox lines=1, max_lines=1)", tag)
    hidden = await b.js("return document.querySelector(%s).offsetParent === null;" % Q)
    check(hidden, "T3 Bans box hidden while 'Random pick settings' is collapsed")

    # Open the collapsed accordion now: the JS attached at boot, no re-attach needed.
    await b.click("#pb_pick_settings .label-wrap")
    shown = await wait_for(b, "return document.querySelector(%s).offsetParent !== null;" % Q, 10)
    check(shown, "T4 accordion opened, Bans box visible")
    await b.js("document.querySelector(%s).scrollIntoView({block: 'center'}); return 1;" % Q)

    # 1. ~ha lists happy; Enter inserts ~happy; Save marker + hint line.
    await type_real(b, BANS, "~ha")
    ok, names = await popup_names(b)
    check(ok and "~happy" in names, "A1 '~ha' in Bans lists ~happy", names)
    check(bool(names) and all(n.startswith("~") for n in names), "A1b block list only", names)
    pos = await b.js("""const p = document.querySelector('.pb-popup').getBoundingClientRect();
        const r = document.querySelector(%s).getBoundingClientRect();
        return {pl: p.left, pt: p.top, pb: p.bottom, il: r.left, ir: r.right, it: r.top, ib: r.bottom};""" % Q)
    at_caret = (pos["il"] <= pos["pl"] <= pos["il"] + 40
                and (abs(pos["pt"] - (pos["ib"] + 2)) < 3 or abs(pos["pb"] - (pos["it"] - 2)) < 3))
    check(at_caret, "A2 popup at the token start, just below (or above) the Bans box", pos)
    await settle(b)
    hint_typed = await b.js(HINT)
    check(bool(hint_typed), "A3 hint line warns about the half-typed ~ha", hint_typed)
    await key(b, "Enter")
    await settle(b)
    check(await b.js(VALUE) == "~happy", "A4 Enter inserted ~happy", await b.js(VALUE))
    check(await closed_after(b, 0.2), "A5 popup closed after Enter")
    expect("A6 Save marker lit after the insert", await S(b), dirty=True, name="saber")
    hint_after = await b.js(HINT)
    check(hint_after != hint_typed, "A7 hint line updated after the insert", [hint_typed, hint_after])

    # Caret further right -> popup further right (measured at the caret, not at the box start).
    await type_real(b, BANS, ", ~s")
    ok, _ = await popup_names(b)
    left2 = await b.js("return document.querySelector('.pb-popup').getBoundingClientRect().left;")
    check(ok and left2 > pos["pl"] + 20, "A8 popup follows the caret to the right", [pos["pl"], left2])
    await key(b, "Escape")
    await set_value(b, "~happy")

    # 2. %PE lists PEmotion; keyboard Up/Down; Enter inserts %PEmotion.
    await type_real(b, BANS, ", %P")
    ok, names = await popup_names(b)
    check(ok and names == ["%PCharacter", "%PEmotion", "%PPose"], "B0 '%P' lists the P categories", names)
    await key(b, "ArrowDown", times=2)
    await key(b, "ArrowUp")
    check(await b.js(ACTIVE) == "%PEmotion", "B2 ArrowDown / ArrowUp move the highlight", await b.js(ACTIVE))
    await type_text(b, "E")
    ok, names = await popup_names(b)
    check(ok and bool(names) and names[0] == "%PEmotion", "B1 '%PE' lists %PEmotion first", names)
    await key(b, "Enter")
    await settle(b)
    check(await b.js(VALUE) == "~happy, %PEmotion", "B3 Enter inserted %PEmotion", await b.js(VALUE))

    # 3. ~happy. and ~happy* open nothing in Bans.
    before = await b.js(VALUE)
    await type_real(b, BANS, ", ~happy.")
    check(await closed_after(b), "C1 '~happy.' opens no sub-block list in Bans", await b.js(NAMES))
    await type_real(b, BANS, "g")
    check(await closed_after(b), "C2 '~happy.g' opens no sub-block list in Bans", await b.js(NAMES))
    await set_value(b, before)
    await type_real(b, BANS, ", ~happy*")
    check(await closed_after(b), "C3 '~happy*' opens no slot list in Bans", await b.js(NAMES))
    await set_value(b, before)

    # 4. Mouse: a click on an item inserts it; Esc closes without changing the text.
    await type_real(b, BANS, ", ~sa")
    ok, names = await popup_names(b)
    check(ok and "~saber" in names, "D1 '~sa' lists ~saber", names)
    xy = await b.js("""const it = [...document.querySelectorAll('.pb-popup .pb-item')]
        .find(r => r.querySelector('.pb-name').textContent === '~saber');
        const r = it.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2];""")
    await click_at(b, xy[0], xy[1])
    await settle(b)
    check(await b.js(VALUE) == before + ", ~saber", "D2 mouse click inserted ~saber", await b.js(VALUE))
    check(await b.js("return document.activeElement === document.querySelector(%s);" % Q),
          "D3 focus stays in the Bans box after the click")
    value = await b.js(VALUE)
    await type_real(b, BANS, ", %P")
    ok, names = await popup_names(b)
    check(ok and "%PEmotion" in names, "D4 '%P' opens the category list", names)
    await key(b, "Escape")
    check(await closed_after(b, 0.2), "D5 Esc closed the popup")
    check(await b.js(VALUE) == value + ", %P", "D6 Esc left the typed text alone", await b.js(VALUE))
    await idle(b)
    await check_page_errors(b)


async def part_harness(b):
    # Prompt box: ~saber. still lists sub-blocks, ~saber* still lists slots (acceptance 3 and 5).
    await harness_load(b)
    await set_prompt(b, "")
    await asyncio.sleep(0.5)
    await type_text(b, "~saber.")
    ok = await wait_for(b, OPEN, 5)
    names = await b.js(NAMES)
    check(ok and bool(names) and all(n.startswith("~saber.") for n in names),
          "H1 '~saber.' in txt2img still lists sub-blocks", names)
    await key(b, "Escape")
    await type_text(b, " ~saber*")
    ok = await wait_for(b, OPEN, 5)
    names = await b.js(NAMES)
    check(ok and bool(names) and all(n.startswith("~saber*") for n in names),
          "H2 '~saber*' in txt2img still lists slots", names)
    await key(b, "Escape")
    check(await b.js("return document.querySelector(%s) === null;" % Q),
          "H3 harness page has no Bans box (boot only warns)")
    await check_page_errors(b)


if __name__ == "__main__":
    run_part("tab", part_tab, env={"PB_EXTRA_BLOCKS": json.dumps(EXTRA)})
    run_part("harness", part_harness)
    finish()
