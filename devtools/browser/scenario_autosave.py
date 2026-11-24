"""Scenario: auto-save + Reload instead of the unsaved-changes guard (design notes section 26), in the
real management tab.

Starts preview_tab.py and a headless browser itself (both stopped at the end). Real clicks / trusted
typing; every wait is a condition wait (scenario_lib.idle). What was or was not written is proven on the
scratch data: blocks.json content and mtime, and the backups folder. Exit code 0 = all passed.
"""
import json

from scenario_lib import (BLANK_SUBS, DATA_FILE, F, S, after_event, check, check_page_errors, ctrl_s, disk, expect,
                          finish, idle, load_tab, open_more, pick_in, press, run_part, sent, settle, tile, tile_now,
                          type_into,
                          wait_for)

TEXT = "#pb_text textarea"
NAME = "#pb_name textarea, #pb_name input"
SEARCH = "#pb_search textarea, #pb_search input"


async def clear_field(b, selector):
    """Real keys: click, select the whole value, Backspace; then wait until idle."""
    await b.click(selector)
    await b.js("const e = document.querySelector(%s); e.focus(); e.select(); return 1;" % json.dumps(selector))
    for t in ("rawKeyDown", "keyUp"):
        await b.cmd("Input.dispatchKeyEvent", type=t, key="Backspace", code="Backspace", windowsVirtualKeyCode=8)
    await settle(b)


async def replace_field(b, selector, text):
    await clear_field(b, selector)
    await type_into(b, selector, text)


def written(before, after):
    """What changed on disk between two disk() results."""
    return {"mtime_changed": before["mtime"] != after["mtime"],
            "new_backups": len(after["backups"] - before["backups"])}


def nothing_written(label, before):
    after = disk()
    w = written(before, after)
    check(not w["mtime_changed"] and w["new_backups"] == 0 and after["blocks"] == before["blocks"],
          label + ": nothing written", w)
    return after


def one_save(label, before):
    after = disk()
    w = written(before, after)
    check(w["mtime_changed"] and w["new_backups"] == 1, label + ": saved once, one backup added", w)
    return after


# Every status text the page shows, for the "never asks to pick again" check at the end.
STATUS_LOG = """window.__statuses = []; const st = document.querySelector('#pb_status');
const rec = () => { const t = (st.innerText || '').trim(); const l = window.__statuses;
  if (t && l[l.length - 1] !== t) l.push(t); };
new MutationObserver(rec).observe(st, {childList: true, subtree: true, characterData: true}); return 1;"""


async def main(b):
    await load_tab(b)
    await b.js(STATUS_LOG)
    d = disk()
    saber0 = d["blocks"]["saber"]

    # 1. Clean form: tile -> loads, nothing written.
    await tile(b, "saber")
    expect("1a tile saber on the initial blank form", await S(b), name="saber", picker="saber", dirty=False)
    await tile(b, "rin")
    expect("1b clean switch to rin", await S(b), name="rin", picker="rin", status="", dirty=False)
    d = nothing_written("1 clean switches", d)

    # 2. Modified valid form: tile -> saved, other block loaded, status says what was saved.
    await tile(b, "saber")
    await type_into(b, TEXT, ", EDIT1")
    expect("2a edit saber: marker on both Save buttons", await S(b), dirty=True, fabDirty=True)
    await tile(b, "rin")
    expect("2b tile rin: saber saved, rin loaded", await S(b), name="rin", picker="rin", dirty=False,
           fabDirty=False, status_has="Saved saber")
    d2 = one_save("2", d)
    check(d2["blocks"]["saber"]["text"] == saber0["text"] + ", EDIT1", "2 the edit is on disk",
          d2["blocks"]["saber"]["text"])
    d = d2

    # 3. Same through the dropdown.
    await type_into(b, TEXT, ", EDIT2")
    await pick_in(b, "#pb_picker", "saber")
    expect("3a dropdown saber: rin saved, saber loaded", await S(b), name="saber", picker="saber",
           status_has="Saved rin", dirty=False, text_has=", EDIT1")
    d2 = one_save("3", d)
    check(d2["blocks"]["rin"]["text"].endswith(", EDIT2"), "3 the rin edit is on disk", d2["blocks"]["rin"])
    d = d2

    # 4. Modified valid form + New -> saved, blank form.
    await type_into(b, TEXT, ", EDIT3")
    await press(b, "#pb_new_btn")
    st = await F(b)
    expect("4 New on a modified saber: saved, blank form", st, name="", text="", lora="", picker="",
           subs=BLANK_SUBS, status_has="Saved saber")
    check("New block" in (st["status"] or ""), "4 status also has the New hint", st["status"])
    d2 = one_save("4", d)
    check(d2["blocks"]["saber"]["text"].endswith(", EDIT3"), "4 the edit is on disk")
    d = d2

    # 5. Blank New form -> tile loads, nothing written.
    await tile(b, "swimsuit")
    expect("5 blank form, tile swimsuit: loaded", await S(b), name="swimsuit", picker="swimsuit", dirty=False)
    d = nothing_written("5", d)

    # 6. New form with only a Name -> tile refused, Reload -> blank, tile -> loads.
    await press(b, "#pb_new_btn")
    d = nothing_written("6a New on a clean form", d)
    await type_into(b, NAME, "zzOnly")
    await tile(b, "rin")
    expect("6b only a Name, tile rin: refused", await S(b), name="zzOnly", picker="", dirty=True,
           status_has="Category is empty.")
    expect("6b refusal says what to do", await S(b), status_has="Fix it or press Reload to discard.")
    d = nothing_written("6b", d)
    await press(b, "#pb_reload_btn")
    expect("6c Reload on the new form: blank", await F(b), name="", text="", picker="", status_has="Cleared")
    expect("6c marker cleared", await S(b), dirty=False)
    await tile(b, "rin")
    expect("6d tile rin: loaded", await S(b), name="rin", picker="rin")
    d = nothing_written("6 (whole step)", d)

    # 7. Loaded block made invalid (Text emptied) -> refused (tile and dropdown); Reload restores; loads.
    rin_text = d["blocks"]["rin"]["text"]
    await clear_field(b, TEXT)
    await tile(b, "saber")
    expect("7a empty Text, tile saber: refused", await S(b), name="rin", picker="rin", text="",
           status_has="Text cannot be empty.", dirty=True)
    await pick_in(b, "#pb_picker", "saber")
    expect("7b empty Text, dropdown saber: refused, dropdown shows rin again", await S(b), name="rin",
           picker="rin", text="", status_has="Fix it or press Reload")
    d = nothing_written("7ab", d)
    await press(b, "#pb_reload_btn")
    expect("7c Reload restores the saved text", await S(b), name="rin", picker="rin", text=rin_text,
           dirty=False, status_has="Reloaded rin")
    await tile(b, "saber")
    expect("7d tile saber: loaded", await S(b), name="saber", picker="saber")
    d = nothing_written("7", d)

    # 8. Name changed on a loaded block -> tile: new block created, original unchanged.
    saber_before = d["blocks"]["saber"]
    await replace_field(b, NAME, "saberAlt")
    await tile(b, "rin")
    expect("8 renamed Name, tile rin: new block saved", await S(b), name="rin",
           status_has="Saved as new block saberAlt")
    d2 = one_save("8", d)
    check(d2["blocks"]["saber"] == saber_before, "8 the original saber is unchanged")
    check(d2["blocks"].get("saberAlt", {}).get("text") == saber_before["text"], "8 saberAlt has saber's text",
          d2["blocks"].get("saberAlt"))
    tiles = await b.js("return [...document.querySelectorAll('#pb_gallery img')].map(i => i.alt);")
    check("saberAlt" in tiles, "8 the new block's tile is in the gallery (same response)", tiles)
    d = d2

    # 8b. Auto-save never replaces another existing block: Name of the loaded block changed to rin.
    await tile(b, "saber")
    await replace_field(b, NAME, "rin")
    await tile(b, "swimsuit")
    expect("8b loaded saber renamed to existing rin, tile swimsuit: refused", await S(b), name="rin",
           picker="saber", status_has="A block named rin already exists. Press Save to overwrite it, or Reload")
    d2 = nothing_written("8b", d)
    check(d2["blocks"]["rin"] == d["blocks"]["rin"], "8b rin unchanged on disk")
    await press(b, "#pb_reload_btn")
    expect("8b Reload: saber again", await S(b), name="saber", picker="saber", dirty=False)

    # 8c. A new form named like an existing block: refused the same way.
    await press(b, "#pb_new_btn")
    await type_into(b, NAME, "rin")
    await type_into(b, "#pb_category input", "PCharacter")
    await type_into(b, TEXT, "zz other text")
    await tile(b, "swimsuit")
    expect("8c new form named rin, tile swimsuit: refused", await S(b), name="rin", picker="",
           status_has="A block named rin already exists")
    d2 = nothing_written("8c", d)
    check(d2["blocks"]["rin"] == d["blocks"]["rin"], "8c rin unchanged on disk")
    await press(b, "#pb_reload_btn")
    expect("8c Reload: blank", await S(b), name="", picker="")

    # 9. Save button, Ctrl+S, Duplicate, Rename, Delete, Rename category, bulk, Restore still work.
    await tile(b, "saber")
    await type_into(b, TEXT, ", S1")
    await press(b, "#pb_save_btn")
    expect("9a Save button", await S(b), name="saber", status_has="Saved saber", dirty=False)
    d = one_save("9a", d)
    await type_into(b, TEXT, ", S2")
    await ctrl_s(b)
    expect("9b Ctrl+S", await S(b), status_has="Saved saber", dirty=False)
    d = one_save("9b", d)
    check(d["blocks"]["saber"]["text"].endswith(", S1, S2"), "9b both edits on disk", d["blocks"]["saber"]["text"])

    await open_more(b)
    await press(b, "#pb_duplicate_btn")
    expect("9c Duplicate: Name set, dropdown empty, marker set", await S(b), name="saber_copy", picker="",
           dirty=True)
    d = nothing_written("9c Duplicate", d)
    await tile(b, "rin")
    expect("9d tile after Duplicate: the copy is auto-saved", await S(b), name="rin", status_has="Saved saber_copy")
    d = one_save("9d", d)
    check("saber_copy" in d["blocks"], "9d saber_copy on disk")

    await tile(b, "saber_copy")
    await type_into(b, "#pb_new_name textarea, #pb_new_name input", "saberB")
    await press(b, "#pb_rename_btn")
    expect("9e Rename", await S(b), name="saberB", picker="saberB", status_has="Renamed saber_copy")
    d = one_save("9e", d)
    check("saberB" in d["blocks"] and "saber_copy" not in d["blocks"], "9e renamed on disk")
    await tile(b, "rin")
    expect("9f tile after Rename: loads", await S(b), name="rin")
    d = nothing_written("9f the rename alone does not make the form modified", d)

    await tile(b, "saberB")
    await press(b, "#pb_delete_btn")
    # Section 33 B: every delete asks twice, also for a block used nowhere.
    expect("9g Delete, first press: asks to confirm", await S(b), name="saberB", picker="saberB",
           status_has="Press Delete again to confirm.")
    d = nothing_written("9g first Delete press", d)
    await press(b, "#pb_delete_btn")
    expect("9g Delete", await S(b), name="", picker="", status_has="Deleted saberB")
    d = one_save("9g", d)
    check("saberB" not in d["blocks"], "9g deleted on disk")

    await pick_in(b, "#pb_cat_from", "Clothes", event=False)  # no listener of its own
    await type_into(b, "#pb_cat_to textarea, #pb_cat_to input", "Wear")
    await press(b, "#pb_cat_rename_btn")
    expect("9h Rename category", await F(b), status_has="Renamed category Clothes")
    d = one_save("9h", d)
    check(d["blocks"]["swimsuit"]["category"] == "Wear", "9h swimsuit moved on disk")

    await type_into(b, SEARCH, "rin")
    await press(b, "#pb_disable_shown_btn")
    expect("9i Disable shown", await F(b), status_has="Disabled")
    d = one_save("9i", d)
    check(d["blocks"]["rin"].get("active") is False, "9i rin inactive on disk")
    await clear_field(b, SEARCH)

    # Sub-block removal: the Save button asks twice; an auto-save saves and warns.
    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)
    data["blocks"]["runscene"]["text"] = "running, ~saber.dress"
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    d = disk()
    await tile(b, "saber")
    row = await b.js("return [...document.querySelectorAll('[id^=\"pb_sub_name_\"]')].findIndex(e => "
                     "e.querySelector('textarea, input').value === 'dress');")
    check(row >= 0, "9j saber has the sub-block dress", row)
    await clear_field(b, "#pb_sub_name_%d textarea, #pb_sub_name_%d input" % (row, row))
    await clear_field(b, "#pb_sub_text_%d textarea, #pb_sub_text_%d input" % (row, row))
    await press(b, "#pb_save_btn")
    expect("9j Save removing a referenced sub-block: asks first", await S(b), status_has="Press Save again")
    d = nothing_written("9j", d)
    await tile(b, "rin")
    expect("9k auto-save of the same form: saved with a warning", await S(b), name="rin",
           status_has="still referenced")
    d = one_save("9k", d)
    check("dress" not in [s["name"] for s in d["blocks"]["saber"].get("subs", [])], "9k dress removed on disk")

    # Restore: the newest backup (= the state before 9k), two presses.
    await b.click("#pb_backups input")
    listed = await wait_for(b, "return !!document.querySelector('#pb_backups ul.options li');", 30)
    first = await b.js("const li = document.querySelector('#pb_backups ul.options li'); if (!li) return null;"
                       "document.querySelectorAll('#pbopt').forEach(e => e.removeAttribute('id'));"
                       "li.id = 'pbopt'; return li.getAttribute('data-value') || li.innerText.trim();")
    check(listed and bool(first), "9l a backup is listed", first)
    await b.click("#pbopt")  # the Backups dropdown has no listener of its own
    await settle(b)
    await press(b, "#pb_restore_btn")
    expect("9l Restore, first press asks", await F(b), status_has="Press Restore backup again")
    await press(b, "#pb_restore_btn")
    expect("9m Restore, second press", await F(b), status_has="Restored the backup", name="")
    d2 = disk()
    check(d2["mtime"] != d["mtime"] and "dress" in [s["name"] for s in d2["blocks"]["saber"].get("subs", [])],
          "9m restored data on disk (dress is back)")
    d = d2

    # 10. Save then immediate New / tile (fast clicks): the expected form, no resurrected rows.
    await tile(b, "saber")
    await type_into(b, TEXT, ", F1")
    before = await sent(b)
    await b.click("#pb_save_btn")
    await b.click("#pb_new_btn")
    await after_event(b, before)
    await idle(b)
    expect("10a Save + New at once: blank form", await F(b), name="", text="", lora="", picker="",
           subs=BLANK_SUBS)
    d = disk()
    check(d["blocks"]["saber"]["text"].endswith(", F1"), "10a saved")

    await tile(b, "saber")
    await type_into(b, TEXT, ", F2")
    before = await sent(b)
    await b.click("#pb_save_btn")
    await tile_now(b, "swimsuit")
    await after_event(b, before)
    await idle(b)
    expect("10b Save + tile at once: swimsuit with its own (empty) rows", await F(b), name="swimsuit",
           lora="", picker="swimsuit", subs=BLANK_SUBS, text="swimsuit")
    d = disk()
    check(d["blocks"]["saber"]["text"].endswith(", F2"), "10b saved")

    await tile(b, "saber")
    await type_into(b, TEXT, ", F3")
    before = await sent(b)
    await b.click("#pb_new_btn")
    await tile_now(b, "swimsuit")
    await after_event(b, before)
    await idle(b)
    st = await F(b)
    expect("10c New + tile at once: swimsuit", st, name="swimsuit", picker="swimsuit", subs=BLANK_SUBS)
    d2 = disk()
    check(d2["blocks"]["saber"]["text"].endswith(", F3") and len(d2["backups"] - d["backups"]) == 1,
          "10c the edit was saved once (by New), the tile only loaded", written(d, d2))

    # 11. No status ever asked to "pick again" or reported "Unsaved changes".
    statuses = await b.js("return window.__statuses;")
    bad = [s for s in statuses if "again within" in s or "Unsaved changes" in s or "Pick " in s]
    check(not bad, "11 no 'pick again' / 'Unsaved changes' status (%d statuses seen)" % len(statuses), bad)
    await check_page_errors(b)


if __name__ == "__main__":
    run_part("tab", main)
    finish()
