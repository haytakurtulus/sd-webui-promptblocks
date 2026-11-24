"""Scenario: design notes section 23b (accordion / popup JS) against the JS harness - selection read at
click time, popup refetch on opening, Pin messages, dark / light theme styling of the accordion inputs.

Starts harness_server.py and a headless browser itself (both stopped at the end). Exit code 0 = all
passed.
"""
import asyncio
import json

from scenario_lib import (TA, check, clear_and_type, click, click_at, finish, harness_load, key, post, rect,
                          run_part, sel_of, select_range, set_prompt, text_of, type_text, val)

# ---------------------------------------------------------------- fix 1


async def fix1(b):
    await harness_load(b)
    prompt = "masterpiece, zzF, long hair"
    await set_prompt(b, prompt)
    await clear_and_type(b, "#pb_new_name_txt2img", "zzStale")
    await clear_and_type(b, "#pb_new_cat_txt2img", "Eyes")
    # User's exact scenario: select zzF, click elsewhere in the prompt (caret only), press the button.
    await click(b, TA)
    await select_range(b, prompt.index("zzF"), 3)
    s = await sel_of(b)
    check(s == [13, 16], "fix1: keys selected zzF", s)
    l, t, r, bt = await rect(b, TA)
    await click_at(b, r - 20, bt - 10)  # inside the prompt, after the text -> caret at the end
    s = await sel_of(b)
    check(s[0] == s[1], "fix1: click elsewhere collapsed the selection", s)
    await click(b, "#pb_create_txt2img")
    await asyncio.sleep(0.5)
    msg = await text_of(b, "#pb_create_msg_txt2img")
    check(msg == "Select some text in the prompt first", "fix1: stale selection -> message", msg)
    check(await val(b, TA) == prompt, "fix1: prompt unchanged", await val(b, TA))
    check("zzStale" not in post("/harness/state")["blocks"], "fix1: nothing saved")

    # Select -> click Name -> type -> click Category -> type -> click button.
    await click(b, TA)
    await select_range(b, prompt.index("zzF"), 3)
    before = await sel_of(b)
    await clear_and_type(b, "#pb_new_name_txt2img", "zzNew")
    after_name = await sel_of(b)
    await clear_and_type(b, "#pb_new_cat_txt2img", "Eyes")
    after_cat = await sel_of(b)
    focused = await b.js("return document.activeElement.id;")
    check(before == after_name == after_cat == [13, 16],
          "fix1: blurred textarea keeps selectionStart/End while Name / Category are focused and typed in",
          [before, after_name, after_cat])
    check(focused == "pb_new_cat_txt2img", "fix1: focus really moved to the Category input", focused)
    # Mouse down on the button (before the click handler) must not change it either.
    l, t, r, bt = await rect(b, "#pb_create_txt2img")
    await b.js("window.__selAtDown = null; document.querySelector('#pb_create_txt2img').addEventListener('mousedown',"
               " () => { const t = document.querySelector('#txt2img_prompt textarea');"
               " window.__selAtDown = [t.selectionStart, t.selectionEnd]; }, {once: true}); return 1;")
    await click_at(b, (l + r) / 2, (t + bt) / 2)
    await asyncio.sleep(0.6)
    check(await b.js("return window.__selAtDown;") == [13, 16], "fix1: selection intact at button mousedown",
          await b.js("return window.__selAtDown;"))
    msg = await text_of(b, "#pb_create_msg_txt2img")
    v = await val(b, TA)
    check(v == "masterpiece, ~zzNew, long hair", "fix1: right range replaced", v)
    check(msg == "Saved ~zzNew", "fix1: saved message", msg)
    check(post("/harness/state")["blocks"].get("zzNew") == {"category": "Eyes", "text": "zzF"},
          "fix1: block stored as {category, text}")
    check(await val(b, "#pb_new_name_txt2img") == "", "fix1: Name cleared")
    cats = await b.js("return [...document.querySelectorAll('#pb_cats_txt2img option')].map(o => o.value);")
    check("Eyes" in cats, "fix1: datalist refreshed after create (refetch after /create)", cats)
    # The popup knows the new block (refetch after create).
    await click(b, TA)
    await key(b, "End", ctrl=True)
    await type_text(b, ", ~zzN")
    await asyncio.sleep(0.3)
    names = await b.js("return [...document.querySelectorAll('.pb-popup .pb-item .pb-name')].map(e => e.textContent);")
    check("~zzNew" in names, "fix1: popup lists the created block", names)
    await key(b, "Escape")

    # Edge whitespace trimmed; whitespace-only selection = no selection.
    prompt2 = "a, blue eyes ,b"
    await set_prompt(b, prompt2)
    await select_range(b, prompt2.index(" blue eyes "), len(" blue eyes "))
    await clear_and_type(b, "#pb_new_name_txt2img", "zzBlue")
    await click(b, "#pb_create_txt2img")
    await asyncio.sleep(0.6)
    v = await val(b, TA)
    check(v == "a, ~zzBlue ,b", "fix1: edge whitespace stays in the prompt", v)
    prompt3 = "a,    b"
    await set_prompt(b, prompt3)
    await select_range(b, 2, 4)
    await clear_and_type(b, "#pb_new_name_txt2img", "zzSpace")
    await click(b, "#pb_create_txt2img")
    await asyncio.sleep(0.5)
    check(await text_of(b, "#pb_create_msg_txt2img") == "Select some text in the prompt first",
          "fix1: whitespace-only selection -> message")
    check(await val(b, TA) == prompt3, "fix1: whitespace-only: prompt unchanged")

    # Prompt edited while the request runs -> range re-check refuses the replacement.
    await set_prompt(b, "x, zzQ, y")
    await select_range(b, 3, 3)
    await clear_and_type(b, "#pb_new_name_txt2img", "zzRace")
    await b.js("const f = window.fetch; window.fetch = async (u, o) => { const r = await f(u, o);"
               " if (String(u).includes('/create')) { const t = document.querySelector('#txt2img_prompt textarea');"
               " t.value = 'changed ' + t.value; } return r; }; return 1;")
    await click(b, "#pb_create_txt2img")
    await asyncio.sleep(0.6)
    check(await val(b, TA) == "changed x, zzQ, y", "fix1: changed prompt is not touched")
    check("insert ~zzRace yourself" in await text_of(b, "#pb_create_msg_txt2img"), "fix1: changed-prompt message")


# ---------------------------------------------------------------- fix 2

POPUP_NAMES = "return [...document.querySelectorAll('.pb-popup .pb-item .pb-name')].map(e => e.textContent);"
ACTIVE = "return (document.querySelector('.pb-popup .pb-item.pb-active .pb-name') || {}).textContent || null;"


async def watch_popup(b):
    # Counts how often the popup gets hidden (style display none) from now on.
    await b.js("window.__hides = 0; const p = document.querySelector('.pb-popup'); let was = p.style.display;"
               " new MutationObserver(() => { if (was === 'block' && p.style.display !== 'block') window.__hides++;"
               " was = p.style.display; }).observe(p, {attributes: true, attributeFilter: ['style']}); return 1;")


async def fix2(b):
    await harness_load(b)
    await set_prompt(b, "")  # textarea focused, data fetched on focus
    await asyncio.sleep(0.5)
    new_blocks = dict(post("/harness/state")["blocks"])
    new_blocks["runscene"] = {**new_blocks["runscene"], "category": "Poses"}  # PPose renamed
    new_blocks["zzNewcat"] = {"category": "NewCat", "text": "new"}
    post("/harness/blocks_delay", {"seconds": 0.4})  # the open popup is first built from the OLD data
    post("/harness/set_blocks", {"blocks": new_blocks})
    await watch_popup(b)
    fetches0 = await b.js("return window.__blockFetches;")
    await type_text(b, "%")
    await asyncio.sleep(0.1)
    first = await b.js(POPUP_NAMES)
    check("%PPose" in first and "%NewCat" not in first, "fix2: first render used the old data (stale)", first)
    await key(b, "ArrowDown", times=2)
    hl = await b.js(ACTIVE)
    await asyncio.sleep(1.0)
    after = await b.js(POPUP_NAMES)
    check("%NewCat" in after and "%Poses" in after and "%PPose" not in after,
          "fix2: popup rebuilt with the new category list", after)
    check(await b.js("return document.querySelector('.pb-popup').style.display;") == "block"
          and await b.js("return window.__hides;") == 0, "fix2: popup stayed open (no close / reopen)")
    check(await b.js(ACTIVE) == hl, "fix2: highlighted item kept by name", [hl, await b.js(ACTIVE)])
    await asyncio.sleep(1.0)
    fetches1 = await b.js("return window.__blockFetches;")
    check(fetches1 - fetches0 == 1, "fix2: exactly one refetch for the opening (no loop)", fetches1 - fetches0)
    await key(b, "Escape")

    # Typing on inside the open popup does not refetch.
    await type_text(b, " %P")
    await asyncio.sleep(0.2)
    f2 = await b.js("return window.__blockFetches;")
    await type_text(b, "C")
    await asyncio.sleep(0.6)
    check(await b.js("return window.__blockFetches;") == f2, "fix2: no refetch while the popup stays open")
    await key(b, "Escape")

    # Closed by the user before the refetch resolves -> stays closed.
    post("/harness/blocks_delay", {"seconds": 0.5})
    nb = dict(post("/harness/state")["blocks"])
    nb["zzOther"] = {"category": "OtherCat", "text": "o"}
    post("/harness/set_blocks", {"blocks": nb})
    await type_text(b, " %")
    await asyncio.sleep(0.05)
    await key(b, "Escape")
    await asyncio.sleep(1.0)
    check(await b.js("return document.querySelector('.pb-popup').style.display;") != "block",
          "fix2: popup closed by the user is not reopened")

    # Accepted before the refetch resolves -> no reopen, inserted text intact.
    nb["zzThird"] = {"category": "ThirdCat", "text": "t"}
    post("/harness/set_blocks", {"blocks": nb})
    await set_prompt(b, "")
    await asyncio.sleep(0.8)
    nb["zzFourth"] = {"category": "FourthCat", "text": "f"}
    post("/harness/set_blocks", {"blocks": nb})
    await type_text(b, "%Cl")
    await asyncio.sleep(0.05)
    await key(b, "Enter")
    await asyncio.sleep(1.0)
    check(await val(b, TA) == "%Clothes" and
          await b.js("return document.querySelector('.pb-popup').style.display;") != "block",
          "fix2: accepted item not disturbed by the late refetch", await val(b, TA))
    post("/harness/blocks_delay", {"seconds": 0})


# ---------------------------------------------------------------- fix 3

PIN_MSG = "#pb_pin_msg_txt2img"


async def pin_press(b):
    await click(b, "#pb_pin_txt2img")
    await asyncio.sleep(0.3)
    first = await text_of(b, PIN_MSG)
    await asyncio.sleep(1.3)  # > the 400 ms preview debounce + request
    return first, await text_of(b, PIN_MSG)


async def fix3(b):
    await harness_load(b)
    prompt = "%PCharacter, ~saber*outfit, %Nope"
    await set_prompt(b, prompt)
    await asyncio.sleep(0.6)
    a, a2 = await pin_press(b)
    check(a == a2 == "No picks recorded yet - generate first", "fix3: not generated yet", [a, a2])
    pv = await text_of(b, "#pb_preview_txt2img")
    check("generate first" not in pv, "fix3: message not in the preview box", pv)

    post("/harness/generate", {"prompt": "~saber", "seed": 1, "tab": "txt2img"})
    a, a2 = await pin_press(b)
    check(a == a2 == "The last Generate made no random picks - nothing to pin", "fix3: generated, no picks", [a, a2])

    g = post("/harness/generate", {"prompt": prompt, "seed": 3, "tab": "txt2img"})
    check(len(g["picks"]) == 2, "fix3: harness recorded 2 picks", g)
    pv_before = await text_of(b, "#pb_preview_txt2img")
    a, a2 = await pin_press(b)
    check(a == a2 == "Pinned 2 picks from the last Generate.", "fix3: pinned, visible after the preview refresh", [a, a2])
    v = await val(b, TA)
    check("%PCharacter" not in v and "*outfit" not in v and v.endswith("%Nope"), "fix3: prompt pinned", v)
    pv_after = await text_of(b, "#pb_preview_txt2img")
    check(pv_after != pv_before and "Pinned" not in pv_after, "fix3: preview refreshed independently", pv_after)
    check(await b.js("return document.querySelector('.pb-popup').style.display;") != "block", "fix3: no popup after pin")

    a, a2 = await pin_press(b)
    check(a == a2 == "Nothing to pin in this prompt", "fix3: nothing to pin", [a, a2])
    warn = await b.js(f"return document.querySelector({json.dumps(PIN_MSG)}).classList.contains('pb-create-msg-warn');")
    col = await b.js(f"return getComputedStyle(document.querySelector({json.dumps(PIN_MSG)})).color;")
    check(warn and col == "rgb(239, 68, 68)", "fix3: warn message red (beats .prose *)", col)


# ---------------------------------------------------------------- fix 4

STYLE_JS = r"""
function rgb(s) { const m = s.match(/[\d.]+/g).map(Number); return m; }
function lum(c) { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); }
function contrast(a, b) { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); }
const out = {};
for (const id of ["pb_new_name_txt2img", "pb_new_cat_txt2img", "pb_reroll_txt2img", "pb_pin_txt2img", "pb_create_txt2img"]) {
  const e = document.getElementById(id), cs = getComputedStyle(e);
  const ph = getComputedStyle(e, "::placeholder");
  out[id] = { bg: cs.backgroundColor, image: cs.backgroundImage, color: cs.color, border: cs.borderTopColor, radius: cs.borderTopLeftRadius,
              padding: cs.padding, scheme: cs.colorScheme, fontSize: cs.fontSize,
              contrast: contrast(rgb(cs.backgroundColor), rgb(cs.color)),
              placeholder: e.tagName === "INPUT" ? ph.color : null,
              phContrast: e.tagName === "INPUT" ? contrast(rgb(cs.backgroundColor), rgb(ph.color)) : null };
}
// Probe: a plain text input in the same .prose gets Gradio's white background (shows Gradio's css is active).
const probe = document.createElement("input"); probe.type = "text";
document.querySelector("#pb_create_row_txt2img").parentElement.appendChild(probe);
out.probe = getComputedStyle(probe).backgroundColor; probe.remove();
out.bodyDark = document.body.classList.contains("dark");
out.themeVar = getComputedStyle(document.body).getPropertyValue("--input-background-fill").trim();
return out;
"""


async def fix4(b):
    for dark in (True, False):
        await harness_load(b, dark=dark)
        st = await b.js(STYLE_JS)
        tag = "dark" if dark else "light"
        check(st["probe"] == "rgb(255, 255, 255)", f"fix4 {tag}: Gradio css active (plain input is white)", st["probe"])
        check(bool(st["themeVar"]), f"fix4 {tag}: theme variables present", st["themeVar"])
        for id_, s in st.items():
            if not isinstance(s, dict):
                continue
            ok_bg = s["bg"] not in ("rgba(0, 0, 0, 0)", "transparent") and (not dark or s["bg"] != "rgb(255, 255, 255)")
            check(ok_bg, f"fix4 {tag}: {id_} background styled", s)
            if "reroll" in id_ or "pin" in id_ or "create_" in id_:
                check(s["image"].startswith("linear-gradient"), f"fix4 {tag}: {id_} theme gradient applied "
                      "(beats Gradio's background-image:none)", s["image"])
            check(s["contrast"] >= 4.5, f"fix4 {tag}: {id_} text contrast {s['contrast']:.1f}", s)
            check(s["radius"] != "0px" and s["padding"] != "0px", f"fix4 {tag}: {id_} radius / padding", s)
            check(s["scheme"] == ("dark" if dark else "light"), f"fix4 {tag}: {id_} color-scheme", s["scheme"])
            if s["placeholder"]:
                check(s["phContrast"] >= 2.5, f"fix4 {tag}: {id_} placeholder readable {s['phContrast']:.1f}", s)
        if dark:
            print(json.dumps(st, indent=1))
            # Screenshot state: messages filled, Name focused.
            await set_prompt(b, "masterpiece, %PCharacter, long hair")
            await click(b, "#pb_pin_txt2img")
            await asyncio.sleep(0.3)
            await click(b, "#pb_create_txt2img")
            await asyncio.sleep(0.3)
            await click(b, "#pb_new_cat_txt2img")
            await type_text(b, "Ey")
            await b.cmd("Input.dispatchMouseEvent", type="mouseMoved", x=5, y=5)
            await b.js("window.scrollTo(0, 0); return 1;")
            await asyncio.sleep(0.6)
            await b.shot("accordion_dark.png")


# ---------------------------------------------------------------- design notes 38 step 2: ban lines

BAN_LINES_JS = ("return [...document.querySelectorAll('#pb_preview_txt2img .pb-preview-ban')]"
                ".map(e => e.textContent);")


async def ban_lines(b):
    await harness_load(b)
    blocks = dict(post("/harness/state")["blocks"])
    blocks["zzNinja"] = {"category": "PChar2", "text": "ninja, mask", "bans": ["~zzHappy"]}
    blocks["zzHappy"] = {"category": "PEmo2", "text": "smile"}
    post("/harness/set_blocks", {"blocks": blocks})
    await set_prompt(b, "~zzNinja, ~zzHappy, x")
    await asyncio.sleep(1.3)  # > the 400 ms preview debounce + request
    lines = await b.js(BAN_LINES_JS)
    check(lines == ["⛔ zzNinja: ~zzHappy silenced"], "bans: preview shows the ban line", lines)
    pv = await text_of(b, "#pb_preview_txt2img")
    check("ninja, mask, x" in pv and "smile" not in pv, "bans: preview text without the banned block", pv)
    col = await b.js("const e = document.querySelector('#pb_preview_txt2img .pb-preview-ban');"
                     "return e ? getComputedStyle(e).color : null;")
    check(col == "rgb(239, 68, 68)", "bans: ban line styled like the warnings", col)
    await set_prompt(b, "~zzNinja, x")
    await asyncio.sleep(1.3)
    lines = await b.js(BAN_LINES_JS)
    check(lines == [], "bans: no ban line when no ban changed anything", lines)


async def main(b):
    for f in (fix1, fix2, fix3, fix4, ban_lines):
        try:
            await f(b)
        except Exception as e:
            check(False, f"{f.__name__} crashed", repr(e)[:500])
    errs = await b.js("return window.__errors;")
    check(not errs, "no page errors", errs)


if __name__ == "__main__":
    run_part("harness", main)
    finish()
