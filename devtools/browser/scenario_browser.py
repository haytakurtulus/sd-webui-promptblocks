"""Scenario: design notes section 40 in the real management tab - dimmed inactive tiles (pb-tile-off), tile
hover summaries (title), block counts in the category filter labels (value unchanged), full-content search
and quick filters; all following Enable shown / Disable shown and Save.

Starts preview_tab.py and a headless browser itself (both stopped at the end). Every wait is a condition
wait (scenario_lib.idle / wait_for). Exit code 0 = all passed.
"""
import json

from scenario_lib import (check, check_page_errors, ctrl_s, disk, expect, finish, idle, load_tab, pick_in, press,
                          run_part, settle, tile, type_into, wait_for)

SEARCH = "#pb_search textarea, #pb_search input"
CAT = "#pb_cat_filter input"

TILES = """return [...document.querySelectorAll('#pb_gallery button.thumbnail-item')].map(btn => {
  const img = btn.querySelector('img');
  const cap = ((img && img.getAttribute('alt')) || '').trim();
  return {cap, name: cap.split(/\\s+/)[0], off: btn.classList.contains('pb-tile-off'),
          loaded: btn.classList.contains('pb-loaded'), title: btn.title,
          op: img ? parseFloat(getComputedStyle(img).opacity) : null,
          filt: img ? getComputedStyle(img).filter : null, bop: parseFloat(getComputedStyle(btn).opacity)};
});"""

# The JS has applied classes and titles for the current captions (60 ms after a change, 500 ms poll).
SETTLED = """return [...document.querySelectorAll('#pb_gallery button.thumbnail-item')].every(btn => {
  const img = btn.querySelector('img');
  const cap = ((img && img.getAttribute('alt')) || '').trim();
  return btn.classList.contains('pb-tile-off') === cap.endsWith(' (off)')
      && (btn.title || '').split('\\n')[0].startsWith(cap);
});"""


async def tiles(b, extra_cond=None):
    await idle(b)
    await wait_for(b, SETTLED, 10)
    if extra_cond:
        await wait_for(b, extra_cond, 10)
    got = await b.js(TILES)
    return {t["name"]: t for t in got}


def title_cond(name, text):
    # The tile `name` has a title containing `text` (the summary comes from a debounced refetch).
    return ("const b = [...document.querySelectorAll('#pb_gallery button.thumbnail-item')].find(x => "
            "((x.querySelector('img') || {}).alt || '').trim().split(/\\s+/)[0] === %s);"
            "return !!b && (b.title || '').includes(%s);" % (json.dumps(name), json.dumps(text)))


def off_names(t):
    return sorted(n for n, x in t.items() if x["off"])


async def cat_label(b):
    return await b.js("return document.querySelector(%s).value;" % json.dumps(CAT))


async def set_search(b, text):
    await b.click(SEARCH)
    await b.js("const e = document.querySelector(%s); e.focus(); e.select(); return 1;" % json.dumps(SEARCH))
    if text:
        await b.cmd("Input.insertText", text=text)
    else:
        for t in ("rawKeyDown", "keyUp"):
            await b.cmd("Input.dispatchKeyEvent", type=t, key="Backspace", code="Backspace", windowsVirtualKeyCode=8)
    await settle(b)


async def main(b):
    await load_tab(b)

    # 1. Initial tiles: only sakura is inactive; dimmed image, clear button.
    t = await tiles(b, title_cond("saber", "Category: PCharacter"))
    check(off_names(t) == ["sakura"], "B1 pb-tile-off only on the inactive block", off_names(t))
    await wait_for(b, "const i = [...document.querySelectorAll('#pb_gallery img')].find(i => "
                      "(i.alt || '').startsWith('sakura')); return !!i && parseFloat(getComputedStyle(i).opacity) < 0.5;",
                   10)
    t = await tiles(b)
    s, r = t.get("sakura", {}), t.get("rin", {})
    check(s.get("op") is not None and s["op"] < 0.5 and "grayscale" in (s.get("filt") or "") and s.get("bop") == 1,
          "B2 inactive tile: image dimmed + grayscale, the button itself not", s)
    check(r.get("op") == 1 and r.get("filt") in ("none", None), "B2b active tile not dimmed", r)

    # 2. Hover summaries from the block data.
    sab = t.get("saber", {}).get("title", "")
    check(all(x in sab for x in ("saber", "Category: PCharacter", "1girl, saber (fate)", "LoRA: <lora:saber_v2:0.8>",
                                 "Sub-blocks: armor, dress, sword")), "B3 saber title: category, text, LoRA, subs", sab)
    check("Weight: 3" in t.get("rin", {}).get("title", ""), "B3b rin title shows its weight", t.get("rin"))
    check("Slot: outfit" in t.get("swimsuit", {}).get("title", ""), "B3c swimsuit title shows its slot",
          t.get("swimsuit"))
    check(t.get("sakura", {}).get("title", "").startswith("sakura (off)"), "B3d sakura title marks it off",
          t.get("sakura"))

    # 3. Category filter labels with counts.
    check(await cat_label(b) == "(all categories) (4/5 active)", "B4 all-categories label with counts",
          await cat_label(b))

    # 4. Full-content search and quick filters.
    await set_search(b, "tohsaka")
    t = await tiles(b)
    check(sorted(t) == ["rin"], "B5 content search: 'tohsaka' (in rin's text) lists rin", sorted(t))
    await set_search(b, "outfit")
    t = await tiles(b)
    check(sorted(t) == ["saber", "swimsuit"], "B5b content search: slot / sub-block slot 'outfit'", sorted(t))
    await set_search(b, ":off")
    t = await tiles(b)
    check(sorted(t) == ["sakura"], "B6 quick filter :off", sorted(t))
    await set_search(b, ":thumb")
    t = await tiles(b)
    check(sorted(t) == ["rin"], "B6b quick filter :thumb (only rin has a thumbnail)", sorted(t))

    # 5. Enable shown (search "sakura"): tile no longer dimmed, labels recount, value unchanged.
    await set_search(b, "sakura")
    await press(b, "#pb_enable_shown_btn")
    t = await tiles(b, "return document.querySelector(%s).value === '(all categories) (5)';" % json.dumps(CAT))
    check(sorted(t) == ["sakura"] and off_names(t) == [] and not t["sakura"]["title"].startswith("sakura (off)"),
          "B7 Enable shown: sakura not dimmed, title without (off)", t)
    check(await cat_label(b) == "(all categories) (5)", "B7b label recounted after Enable shown", await cat_label(b))
    check(disk()["blocks"]["sakura"].get("active", True) is True, "B7c sakura active on disk")

    # 6. Filter PCharacter, Disable shown: label "(0/3 active)", the filter value stays (3 tiles shown).
    await set_search(b, "")
    # The options carry no value attribute: they are picked by their label (which now has the counts).
    await pick_in(b, "#pb_cat_filter", "PCharacter (3)")
    t = await tiles(b)
    check(sorted(t) == ["rin", "saber", "sakura"] and await cat_label(b) == "PCharacter (3)",
          "B8 filter PCharacter: label with count", [sorted(t), await cat_label(b)])
    await press(b, "#pb_disable_shown_btn")
    t = await tiles(b, "return document.querySelector(%s).value === 'PCharacter (0/3 active)';" % json.dumps(CAT))
    check(off_names(t) == ["rin", "saber", "sakura"], "B9 Disable shown: every shown tile dimmed", off_names(t))
    check(await cat_label(b) == "PCharacter (0/3 active)" and sorted(t) == ["rin", "saber", "sakura"],
          "B9b label recounted, filter value unchanged", [await cat_label(b), sorted(t)])
    await press(b, "#pb_enable_shown_btn")
    t = await tiles(b, "return document.querySelector(%s).value === 'PCharacter (3)';" % json.dumps(CAT))
    check(off_names(t) == [] and await cat_label(b) == "PCharacter (3)", "B10 Enable shown again", off_names(t))

    # 7. Save: saber inactive + new text -> dimmed tile (still the clear loaded frame), new title, label.
    await tile(b, "saber")
    await b.click("#pb_pick_settings .label-wrap")
    await wait_for(b, "return document.querySelector('#pb_active input').offsetParent !== null;", 10)
    await b.click("#pb_active input")
    await settle(b)
    await type_into(b, "#pb_text textarea", ", EDITX")
    await ctrl_s(b)
    t = await tiles(b, title_cond("saber", "EDITX"))
    sb = t.get("saber", {})
    check(sb.get("off") is True and sb.get("loaded") is True and sb.get("bop") == 1,
          "B11 Save inactive: saber dimmed, loaded frame kept, button not dimmed", sb)
    check("EDITX" in sb.get("title", "") and sb.get("title", "").startswith("saber (off)"),
          "B11b title follows Save (new text, off)", sb.get("title"))
    expect("B11c label after Save", {"label": await cat_label(b)}, label="PCharacter (2/3 active)")
    check(disk()["blocks"]["saber"].get("active") is False, "B11d saber inactive on disk")

    # 8. Back to all categories: the label counts all blocks, every tile is listed again.
    await pick_in(b, "#pb_cat_filter", "(all categories) (4/5 active)")
    t = await tiles(b)
    check(len(t) == 5 and await cat_label(b) == "(all categories) (4/5 active)", "B12 all categories again",
          [sorted(t), await cat_label(b)])

    await check_page_errors(b)


if __name__ == "__main__":
    run_part("tab", main)
    finish()
