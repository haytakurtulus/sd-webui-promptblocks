"""Scenario: design notes section 37 in the real management tab - new rows start as Include (A), the
"All Include | All Exclude | All Random" buttons of the open form (B) and the sub-block row classes by mode
(C: an Exclude row is dimmed, the % box is dimmed unless the row is Random).

Starts preview_tab.py and a headless browser itself (both stopped at the end). Every wait is a condition
wait (scenario_lib.idle / wait_for). Exit code 0 = all passed.
"""
from scenario_lib import (BLANK_SUBS, ROW_COUNT, S, check, check_page_errors, disk, expect, finish, idle, load_tab,
                          pick_in, press, run_part, tile, type_into, wait_for)

# Per row: the Mode dropdown's shown value (lower case), the two classes and the computed opacities.
# Focus is taken away first, so an open dropdown / focused field (row at full opacity, see style.css)
# does not hide the dimming.
ROWS = """if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
return [...document.querySelectorAll('#pb_subs .pb-subrow')].map(r => {
  const i = r.querySelector('[id^="pb_sub_mode_"] input');
  const ch = r.querySelector('[id^="pb_sub_chance_"]');
  return {mode: i ? (i.value || '').trim().toLowerCase() : null,
          ex: r.classList.contains('pb-sub-exclude'), nc: r.classList.contains('pb-sub-nochance'),
          op: getComputedStyle(r).opacity, chop: ch ? getComputedStyle(ch).opacity : null};
});"""

# True once every row's classes follow its shown mode (the JS applies them 60 ms after a hook, with the
# 500 ms poll as a safety net).
CLASSES_SETTLED = """return [...document.querySelectorAll('#pb_subs .pb-subrow')].every(r => {
  const i = r.querySelector('[id^="pb_sub_mode_"] input');
  const m = i ? (i.value || '').trim().toLowerCase() : '';
  return r.classList.contains('pb-sub-exclude') === (m === 'exclude')
      && r.classList.contains('pb-sub-nochance') === (m !== 'random');
});"""


async def rows(b, label, modes):
    """Wait until the classes follow the modes, then check modes, classes and opacities against `modes`
    (one entry per row; the rows after the given ones are expected to be blank Include rows)."""
    await idle(b)
    settled = await wait_for(b, CLASSES_SETTLED, 10)
    want = list(modes) + ["include"] * (ROW_COUNT - len(modes))
    got = await b.js(ROWS)
    ok = settled and len(got) == ROW_COUNT and all(
        g["mode"] == m and g["ex"] == (m == "exclude") and g["nc"] == (m != "random")
        and abs(float(g["op"]) - (0.55 if m == "exclude" else 1.0)) < 0.01
        and abs(float(g["chop"]) - (1.0 if m == "random" else 0.35)) < 0.01
        for g, m in zip(got, want))
    check(ok, label, {"want": want, "got": got, "settled": settled})


def sub_modes(name):
    return [s.get("mode") for s in disk()["blocks"][name].get("subs", [])]


async def main(b):
    await load_tab(b)
    # saber in the scratch data: armor include, dress include, sword random (preview_tab.py).

    await press(b, "#pb_new_btn")
    st = await S(b)
    expect("A1 New: blank form, not modified", st, name="", dirty=False)
    await rows(b, "A2 New form: every row Include, % boxes dim, nothing dimmed as Exclude", [])

    await tile(b, "saber")
    expect("C1 tile saber loads, not modified", await S(b), name="saber", dirty=False)
    await rows(b, "C2 after loading saber: classes match include, include, random", ["include", "include", "random"])

    # A hand change of one Mode dropdown (sends no Gradio event: the Mode dropdowns have no listener).
    await pick_in(b, "#pb_sub_mode_0", "Exclude", event=False)
    expect("C3 hand change marks Save dirty", await S(b), dirty=True)
    await rows(b, "C4 after a hand change: row 1 Exclude dimmed", ["exclude", "include", "random"])
    # A dimmed row stays usable: typing into its Text field works.
    await type_into(b, "#pb_sub_text_0 textarea, #pb_sub_text_0 input", " X")
    value = await b.js("const e = document.querySelector('#pb_sub_text_0 textarea, #pb_sub_text_0 input');"
                       "return e ? e.value : null;")
    check(value == "silver armor, gauntlets X", "C5 typing into a dimmed Exclude row works", value)

    await press(b, "#pb_reload_btn")
    expect("C6 Reload: saved text back, not modified", await S(b), dirty=False)
    await rows(b, "C7 after Reload: classes match the saved modes again", ["include", "include", "random"])

    before = disk()
    await press(b, "#pb_subs_all_exclude")
    expect("B1 All Exclude: status, Save dirty", await S(b), dirty=True,
           status="Set 3 sub-blocks to Exclude. Press Save to keep it.")
    after = disk()
    check(after["mtime"] == before["mtime"] and after["backups"] == before["backups"],
          "B2 All Exclude writes nothing to disk", {"modes": sub_modes("saber")})
    await rows(b, "B3 after All Exclude: the 3 filled rows Exclude, blank rows unchanged",
               ["exclude", "exclude", "exclude"])

    # The open option list of a dimmed row must lie above the dimmed rows below it (style.css :focus-within).
    await b.click("#pb_sub_mode_0 input")
    shown = await wait_for(b, "return document.querySelectorAll('#pb_sub_mode_0 ul.options li').length === 3;", 10)
    on_top = await b.js("""const lis = [...document.querySelectorAll('#pb_sub_mode_0 ul.options li')];
        return lis.map(li => { const r = li.getBoundingClientRect();
          const e = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
          return !!e && li.contains(e); });""")
    check(shown and on_top == [True, True, True], "C10 option list of a dimmed row is on top", on_top)
    await b.js("document.activeElement && document.activeElement.blur(); return 1;")
    await idle(b)

    await press(b, "#pb_subs_all_exclude")
    expect("B4 All Exclude again: nothing to change", await S(b), dirty=True,
           status="Nothing to change: all 3 filled sub-block rows are already Exclude.")

    await press(b, "#pb_subs_all_random")
    expect("B5 All Random: status", await S(b), dirty=True,
           status="Set 3 sub-blocks to Random. Press Save to keep it.")
    await rows(b, "B6 after All Random: % boxes of the filled rows full", ["random", "random", "random"])
    check(sub_modes("saber") == ["include", "include", "random"], "B7 still nothing on disk", sub_modes("saber"))

    # Auto-save on a block switch saves the new modes (section 26).
    await tile(b, "rin")
    expect("B8 switch to rin auto-saved saber", await S(b), name="rin", dirty=False)
    check(sub_modes("saber") == ["random", "random", "random"], "B9 saved modes on disk", sub_modes("saber"))
    await rows(b, "C8 rin (no sub-blocks): blank Include rows", [])

    await press(b, "#pb_subs_all_exclude")
    expect("B10 All Exclude without filled rows: message, not dirty", await S(b), dirty=False,
           status="No filled sub-block rows.")
    await rows(b, "B11 blank rows keep Include", [])

    await tile(b, "saber")
    await rows(b, "C9 saber reloaded with its saved Random modes", ["random", "random", "random"])

    # Reload restores the stored modes after an All <mode> press.
    await press(b, "#pb_subs_all_include")
    expect("B12 All Include", await S(b), dirty=True, status="Set 3 sub-blocks to Include. Press Save to keep it.")
    await rows(b, "B13 after All Include", ["include", "include", "include"])
    await press(b, "#pb_reload_btn")
    expect("B14 Reload after All Include: not modified", await S(b), dirty=False)
    await rows(b, "B15 Reload restored the saved Random modes", ["random", "random", "random"])
    check(sub_modes("saber") == ["random", "random", "random"], "B16 Reload wrote nothing", sub_modes("saber"))

    await press(b, "#pb_new_btn")
    expect("A3 New after Reload: blank, not modified", await S(b), name="", dirty=False)
    subs_now = await b.js("return [...document.querySelectorAll('[id^=\"pb_sub_name_\"]')].map(e => {"
                          "const f = e.querySelector('textarea, input'); return f ? f.value : null; });")
    check(subs_now == BLANK_SUBS, "A4 New: all rows blank", subs_now)
    await rows(b, "A5 New form again: every row Include", [])

    await check_page_errors(b)


if __name__ == "__main__":
    run_part("tab", main)
    finish()
