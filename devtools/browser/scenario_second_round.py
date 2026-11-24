"""Scenario: design notes section 24 (second round of fixes, all four items).

Runs three parts one after the other, each with a fresh server and a fresh headless browser:
  1. preview_tab.py at normal speed: item 1 (hints in the handlers' own response) and item 2
     (first tile click after New);
  2. preview_tab.py with PB_SLOW_ALL=0.3 (every tab handler 0.3 s slower, like a busy Forge; needed to
     reproduce item 2): item 2 with quick clicks;
  3. harness_server.py: items 3 (transient accordion messages) and 4 (preview after "Save selection").
Every step is asserted. The tab parts use condition waits (scenario_lib.idle); the harness part keeps its
real delays where it measures message timeouts. Exit code 0 = all passed.

Item 2 with section 26: New on a modified form auto-saves it (it used to warn, and a second New
discarded); the first tile click after it must still load the block, also when it is made before New's
response has arrived (then the tile event is stale and only loads).
"""
import asyncio
import json
import os
import time

from scenario_lib import (TA, F, S, after_event, check, clear_and_type, click, finish, harness_load, key,
                          load_tab, open_more, pick_in, post, press, run_part, select_range, sent, set_prompt,
                          settle, text_of, tile, tile_now, type_into, type_real, type_text, wait_for)
import devenv  # noqa: E402  (after scenario_lib, which sets sys.dont_write_bytecode)

# ------------------------------------------------------------------ tab helpers

# In-page probe armed before a click on `btn`: the first moment the status contains `want_status`,
# record the hint line and the status as they are at that moment; also the time (ms after the
# mousedown) when the hint first reaches the expected value.
PROBE = """window.__p = null; window.__t = {}; const btn = %s, wantStatus = %s, wantHint = %s;
let t0 = null;
document.querySelector(btn).addEventListener('mousedown', () => { t0 = performance.now(); }, {once: true});
const get = () => ({status: (document.querySelector('#pb_status').innerText || '').trim(),
  hint: (document.querySelector('#pb_block_group .pb-hintline').innerText || '').trim(),
  category: document.querySelector('#pb_category input').value});
const iv = setInterval(() => {
  if (t0 === null) return;
  const now = Math.round(performance.now() - t0), s = get();
  if (!window.__p && s.status.includes(wantStatus)) window.__p = Object.assign(s, {t: now});
  if (window.__t.hint === undefined && wantHint && s.hint === wantHint) window.__t.hint = now;
  if (now > 60000) clearInterval(iv);
}, 3); return 1;"""


async def arm(b, btn, want_status, want_hint=None):
    await b.js(PROBE % tuple(json.dumps(x) for x in (btn, want_status, want_hint)))


async def probe_result(b):
    return await b.js("return {p: window.__p, t: window.__t};")


# ------------------------------------------------------------------ item 1 (tab, normal speed)

async def item1(b):
    await load_tab(b)

    # 1a. New block in an existing category: the hint's new count is in Save's response.
    await press(b, "#pb_new_btn")
    await type_real(b, "#pb_name textarea, #pb_name input", "zzHint")
    await type_real(b, "#pb_category input", "PCharacter")
    await type_real(b, "#pb_text textarea", "zz hint text")  # the click commits the Category (change event)
    await settle(b)
    st = await F(b)
    check(st["hint"] == "Existing category (3 blocks).", "1a before Save: hint shows the old count", st["hint"])
    await arm(b, "#pb_save_btn", "Saved zzHint", "Existing category (4 blocks).")
    await press(b, "#pb_save_btn")
    r = await probe_result(b)
    p = r["p"] or {}
    check(p.get("hint") == "Existing category (4 blocks).",
          "1a new block: hint has the new count at the moment the status says Saved", r)
    tile_ok = await b.js("return [...document.querySelectorAll('#pb_gallery img')].some(i => i.alt === 'zzHint');")
    check(tile_ok, "1a new block: its tile is in the gallery (chained browser refresh)")

    # 1b. Existing block: the edit is saved.
    await tile(b, "rin")
    await tile(b, "saber")
    await type_into(b, "#pb_text textarea", ", EDIT24")
    await arm(b, "#pb_save_btn", "Saved saber")
    await press(b, "#pb_save_btn")
    r = await probe_result(b)
    check(r["p"] is not None, "1b existing block: the status says Saved", r)

    # 1c. Rename category: the Category field follows, the hint comes with the status.
    await tile(b, "swimsuit")
    await open_more(b)
    await pick_in(b, "#pb_cat_from", "Clothes", event=False)
    await type_real(b, "#pb_cat_to textarea, #pb_cat_to input", "Wear")
    await settle(b)
    await arm(b, "#pb_cat_rename_btn", "Renamed category", "Existing category (1 block).")
    await press(b, "#pb_cat_rename_btn")
    r = await probe_result(b)
    p = r["p"] or {}
    check(p.get("hint") == "Existing category (1 block).", "1c rename category: hint with the status", r)

    # 1d. Disable shown (search = rin): the status reports it.
    await tile(b, "rin")
    await type_real(b, "#pb_search textarea, #pb_search input", "rin")
    await settle(b)
    await arm(b, "#pb_disable_shown_btn", "Disabled")
    await press(b, "#pb_disable_shown_btn")
    r = await probe_result(b)
    check(r["p"] is not None, "1d disable shown: the status says Disabled", r)
    errors = await b.js("return window.__errors;")
    check(errors == [], "item 1: no page errors", errors)


# ------------------------------------------------------------------ item 2 (tab)

SLOW = 0.0  # seconds every tab handler is slowed down by in the current part (PB_SLOW_ALL)


RIN_THUMB = os.path.join(str(devenv.PREVIEW_DATA), "thumbs", "rin.webp")
_rin_thumb = []


async def new_then_click(b, edit, target, fast):
    # Load rin (it has a thumbnail), modify the form, New (auto-saves, blanks), click a tile.
    # A "thumb" case auto-saves rin WITHOUT its thumbnail, so the file is put back before every case.
    if not _rin_thumb:
        with open(RIN_THUMB, "rb") as f:
            _rin_thumb.append(f.read())
    with open(RIN_THUMB, "wb") as f:
        f.write(_rin_thumb[0])
    await load_tab(b)
    await tile(b, "rin")
    if edit == "text":
        await type_into(b, "#pb_text textarea", ", EDIT")
    else:
        await press(b, "#pb_thumb button[aria-label='Remove Image']")  # user clears the thumbnail
    before = await sent(b)
    await b.click("#pb_new_btn")
    if fast:
        await asyncio.sleep(0.05)  # the reproduction's timing (click 50 ms after New), not a wait
        st_new = None
        mid = await S(b)
    else:
        await after_event(b, before)
        st_new = mid = await S(b)
    before_tile = await sent(b)
    await tile_now(b, target)
    await after_event(b, before_tile)
    return st_new, mid, await S(b)


async def item2(b):
    cases = [("text", "saber", False), ("text", "rin", False), ("thumb", "saber", False), ("thumb", "rin", False)]
    if SLOW:
        cases = [("text", "rin", True), ("text", "saber", True), ("thumb", "rin", True), ("thumb", "saber", True)]
    for edit, target, fast in cases:
        label = "2 %s: rin, %s edit, New, %s tile %s" % ("slow" if SLOW else "normal", edit,
                                                         "quick (50 ms)" if fast else "", target)
        st_new, mid, after = await new_then_click(b, edit, target, fast)
        if fast:
            # The reproduction condition: the click happened before New's response had arrived.
            check(mid.get("picker") == "rin", label + ": click made before the blank form arrived", mid.get("picker"))
        else:
            check("Saved rin" in (st_new.get("status") or ""), label + ": New saved the modified form",
                  st_new.get("status"))
            check(mid.get("name") == "" and mid.get("picker") == "", label + ": blank before the click", mid)
        check(after.get("name") == target and after.get("picker") == target
              and "Unsaved" not in (after.get("status") or ""),
              label + ": the FIRST click loads the block", after)
    errors = await b.js("return window.__errors;")
    check(errors == [], "item 2: no page errors", errors)


# ------------------------------------------------------------------ items 3 and 4 (harness)

async def msg(b, kind, tab="txt2img"):
    return await b.js("const e = document.querySelector('#pb_%s_msg_%s'); return e ? e.textContent : null;"
                      % (kind, tab))


async def wait_msg(b, kind, pred, tab="txt2img", timeout=30):
    """Wait until the accordion message line `kind` ("create" / "pin") satisfies the JS expression
    `pred` over its text `t` (the check after it reports a timeout)."""
    await wait_for(b, "const e = document.querySelector('#pb_%s_msg_%s'); const t = e ? e.textContent : null;"
                      "return t !== null && (%s);" % (kind, tab, pred), timeout)


async def item3(b):
    await harness_load(b)
    await set_prompt(b, "masterpiece, %PCharacter, blue eyes")
    await asyncio.sleep(0.6)

    # (b) prompt input clears; warning text first.
    await click(b, "#pb_create_txt2img")  # caret only -> warning
    await wait_msg(b, "create", "t === 'Select some text in the prompt first'")
    check(await msg(b, "create") == "Select some text in the prompt first", "3 warning shown")
    await click(b, TA)
    await key(b, "End", ctrl=True)
    await type_text(b, " x")
    await wait_msg(b, "create", "t === ''")
    check(await msg(b, "create") == "", "3b typing in the prompt clears the create line", await msg(b, "create"))

    # (a) timeout: warning 10 s, restarted when replaced.
    await click(b, "#pb_create_txt2img")
    t0 = time.time()
    await asyncio.sleep(5)
    await click(b, "#pb_create_txt2img")  # same warning again at t0 + 5 -> timer restarts
    t1 = time.time()
    await asyncio.sleep(max(0, t0 + 11 - time.time()))
    check(await msg(b, "create") == "Select some text in the prompt first",
          "3a replaced warning still shown 11 s after the first (6 s after the replacement)")
    await asyncio.sleep(max(0, t1 + 10.6 - time.time()))
    check(await msg(b, "create") == "", "3a warning gone 10.6 s after the replacement", await msg(b, "create"))

    # (a) info message 6 s: Pin with nothing generated is a warning; a successful create is info.
    await set_prompt(b, "masterpiece, zzQ, long hair")
    await select_range(b, len("masterpiece, "), 3)
    await clear_and_type(b, "#pb_new_name_txt2img", "zzT24")
    await clear_and_type(b, "#pb_new_cat_txt2img", "Misc")
    await click(b, "#pb_create_txt2img")
    t0 = time.time()
    await wait_msg(b, "create", "t === 'Saved ~zzT24'")
    check(await msg(b, "create") == "Saved ~zzT24", "3 create ok: info message")
    await asyncio.sleep(max(0, t0 + 5.3 - time.time()))
    check(await msg(b, "create") == "Saved ~zzT24", "3a info message still shown at 5.3 s")
    await asyncio.sleep(max(0, t0 + 6.7 - time.time()))
    check(await msg(b, "create") == "", "3a info message gone at 6.7 s", await msg(b, "create"))

    # Other action of the accordion succeeds -> the other line is cleared.
    await set_prompt(b, "%PCharacter, rest")
    await click(b, "#pb_create_txt2img")  # warning on the create line
    await wait_msg(b, "create", "t !== ''")
    post("/harness/generate", {"prompt": "%PCharacter, rest", "seed": 3, "tab": "txt2img"})
    await click(b, "#pb_pin_txt2img")
    await wait_msg(b, "pin", "t.startsWith('Pinned')")
    check((await msg(b, "pin")).startswith("Pinned 1 pick"), "3 pin succeeded", await msg(b, "pin"))
    check(await msg(b, "create") == "", "3 successful Pin clears the create line", await msg(b, "create"))
    await set_prompt(b, "a, blue eyes")
    await click(b, "#pb_pin_txt2img")  # nothing to pin -> warning on the pin line
    await wait_msg(b, "pin", "t === 'Nothing to pin in this prompt'")
    check(await msg(b, "pin") == "Nothing to pin in this prompt", "3 pin warning shown", await msg(b, "pin"))
    await click(b, TA)
    await select_range(b, 3, len("blue eyes"))
    await clear_and_type(b, "#pb_new_name_txt2img", "zzT24b")
    await click(b, "#pb_create_txt2img")
    await wait_msg(b, "create", "t === 'Saved ~zzT24b'")
    check(await msg(b, "create") == "Saved ~zzT24b", "3 create succeeded", await msg(b, "create"))
    check(await msg(b, "pin") == "", "3 successful create clears the pin line", await msg(b, "pin"))

    # (c) new Pin press clears at once; generation start / end clears the pin line.
    await click(b, "#pb_pin_txt2img")
    await wait_msg(b, "pin", "t !== ''")
    check(await msg(b, "pin") != "", "3c pin message shown", await msg(b, "pin"))
    await b.js("document.querySelector('#txt2img_interrupt').style.display = 'block'; return 1;")
    await wait_msg(b, "pin", "t === ''")
    check(await msg(b, "pin") == "", "3c generation start (Interrupt shown) clears the pin line", await msg(b, "pin"))
    await click(b, "#pb_pin_txt2img")
    await wait_msg(b, "pin", "t !== ''")
    check(await msg(b, "pin") != "", "3c pin message shown during the generation", await msg(b, "pin"))
    await b.js("document.querySelector('#txt2img_interrupt').style.display = 'none'; return 1;")
    await wait_msg(b, "pin", "t === ''")
    check(await msg(b, "pin") == "", "3c generation end (Interrupt hidden) clears the pin line", await msg(b, "pin"))
    await b.js("document.querySelector('#txt2img_interrupt').style.display = 'none'; return 1;")
    await click(b, "#pb_pin_txt2img")
    await wait_msg(b, "pin", "t !== ''")
    before = await msg(b, "pin")
    await b.js("window.__pinSeen = []; const e = document.querySelector('#pb_pin_msg_txt2img');"
               "new MutationObserver(() => window.__pinSeen.push(e.textContent)).observe(e, {childList: true, characterData: true, subtree: true});"
               "return 1;")
    await click(b, "#pb_pin_txt2img")
    await wait_for(b, "const s = window.__pinSeen; return s.length >= 2 && s[s.length - 1] !== '';", 30)
    seen = await b.js("return window.__pinSeen;")
    check(before and seen and seen[0] == "" and seen[-1] == before, "3c a new Pin press clears first, then shows",
          [before, seen])

    # Missing message elements: no exception.
    await b.js("document.querySelector('#pb_pin_msg_img2img').remove(); document.querySelector('#pb_create_msg_img2img').remove();"
               "return 1;")
    await click(b, "#pb_pin_img2img")
    await click(b, "#pb_create_img2img")
    await click(b, "#img2img_prompt textarea")
    await type_text(b, "z")
    await asyncio.sleep(0.6)
    errors = await b.js("return window.__errors;")
    check(errors == [], "3 missing message elements: no page errors", errors)


NET = """window.__net = []; const f0 = window.fetch; const T0 = performance.now();
window.fetch = async (u, o) => { const t = Math.round(performance.now() - T0);
  const e = {url: String(u), t, body: o && o.body ? JSON.parse(o.body) : null}; window.__net.push(e);
  const r = await f0(u, o); const c = r.clone();
  try { e.res = await c.json(); } catch (x) {} e.tDone = Math.round(performance.now() - T0); return r; };
window.__box = []; const box = document.querySelector('#pb_preview_txt2img');
new MutationObserver(() => window.__box.push([Math.round(performance.now() - T0), box.innerText]))
  .observe(box, {childList: true, subtree: true, characterData: true}); return 1;"""


async def item4(b):
    for seed in (None, 7):
        await harness_load(b)
        if seed is not None:
            await clear_and_type(b, "#pb_block_seed_txt2img input", str(seed))
        prompt = "masterpiece, blue eyes, long hair"
        await set_prompt(b, prompt)
        await asyncio.sleep(1.2)
        await select_range(b, prompt.index("blue eyes"), len("blue eyes"))
        await clear_and_type(b, "#pb_new_name_txt2img", "zzEyes")
        await clear_and_type(b, "#pb_new_cat_txt2img", "Eyes")
        await asyncio.sleep(0.8)
        before = await text_of(b, "#pb_preview_txt2img")
        await b.js(NET)
        await click(b, "#pb_create_txt2img")
        await wait_for(b, "return window.__net.some(e => e.url.endsWith('/promptblocks/preview') && e.tDone !== undefined);", 30)
        await asyncio.sleep(1.0)  # real delay: proves that no SECOND preview request follows
        net = await b.js("return window.__net;")
        boxes = await b.js("return window.__box;")
        after = await text_of(b, "#pb_preview_txt2img")
        tag = "4 seed field %s" % ("-1" if seed is None else seed)
        create = next((e for e in net if e["url"].endswith("/promptblocks/create")), None)
        previews = [e for e in net if e["url"].endswith("/promptblocks/preview")]
        check(create and create["res"]["ok"], tag + ": block created", create)
        check(len(previews) == 1, tag + ": exactly one preview request after the replacement", previews)
        if create and previews:
            p = previews[0]
            check(p["t"] >= create["tDone"], tag + ": preview sent after the save finished",
                  {"create_done": create["tDone"], "preview_sent": p["t"]})
            check(p["body"]["prompt"] == "masterpiece, ~zzEyes, long hair", tag + ": preview uses the new prompt",
                  p["body"])
            check(p["res"]["unknown"] == [] and p["res"]["text"] == prompt,
                  tag + ": server knows ~zzEyes; expanded text equals the old prompt (by construction)", p["res"])
        check(len(boxes) >= 1, tag + ": preview box re-rendered after the request", boxes)
        if seed is None:
            check(before != after and after.startswith("Random example (seed"),
                  tag + ": label shows the new random seed", [before, after])
        else:
            check(before == after, tag + ": fixed seed -> identical box (same seed, same text)", [before, after])
    errors = await b.js("return window.__errors;")
    check(errors == [], "item 4: no page errors", errors)


# ------------------------------------------------------------------ runner

async def part_tab(b):
    await item1(b)
    await item2(b)


async def part_tab_slow(b):
    await item2(b)


async def part_harness(b):
    await item3(b)
    await item4(b)


if __name__ == "__main__":
    run_part("tab", part_tab)
    SLOW = 0.3
    run_part("tab", part_tab_slow, env={"PB_SLOW_ALL": "0.3"})
    run_part("harness", part_harness)
    finish()
