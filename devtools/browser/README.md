# Browser scenarios (developer tooling)

Scripted end-to-end checks that drive the **real** management tab and the **real** extension JS (`javascript/*.js`)
in a headless Chromium browser over the DevTools protocol, with real mouse clicks and trusted typing.
They are not part of the extension and not part of pytest.

## Why

A handler-level simulation (calling the Python handlers directly) is not enough: real Gradio fires
different events in a different order. Concrete findings: a gallery re-selection needed
`gr.Gallery(selected_index=None)`, because an update dict silently drops `None` values, so the same tile
fired no `select` again (§20); the "first tile click after New does nothing" bug (§24) was reproduced
only with real clicks against slowed handlers, and in §26 it came back in another form: a block switch
that has the gallery among its outputs covers it with Gradio's progress overlay, which swallowed a tile
click made while New was still running. §24 also measured that each chained Gradio step is one extra
queued round trip, which only a real browser shows.

## Contents

| File | What it is |
|---|---|
| `cdp.py` | tiny DevTools-protocol driver; starts / stops a headless Chrome or Edge |
| `preview_tab.py` | serves the real management tab (`pb_core.ui.build_tab()`) standalone with scratch data |
| `harness_server.py` | fake WebUI page for the accordion / popup JS, real `pb_core` logic, in-memory blocks |
| `devenv.py` | paths, ports, executable lookup, process cleanup (standard library only); `extension_js_files()` = the extension's `javascript/*.js` in Forge's load order |
| `scenario_lib.py` | shared boilerplate: server start / stop, page helpers, PASS / FAIL, exit code |
| `scenario_autosave.py` | auto-save + Reload on block switches (§26; proves writes on the scratch data) |
| `scenario_small_fixes.py` | gallery highlight, rename-category reload, tile cleanup (§21) |
| `scenario_tab_fixes.py` | management tab fixes with slowed saves (§23a) |
| `scenario_accordion.py` | accordion / popup JS, light and dark theme (§23b) |
| `scenario_second_round.py` | §24: tab at normal speed, tab with slowed handlers, harness |
| `scenario_sub_rows.py` | §37: new rows Include, All Include / Exclude / Random of the form, row classes by mode |
| `scenario_bans_popup.py` | §39: autocomplete popup in the Bans box (`<input>`), no sub-block list there; prompt box unchanged |
| `scenario_browser.py` | §40: dimmed inactive tiles, tile hover summaries, block counts in the category filter labels, content search / quick filters, after Enable / Disable shown and Save |
| `run_all.py` | runs every scenario, one line per scenario, summary, exit code |

## Requirements

- Forge's venv Python (it has `gradio` 4.40 and `websockets`; `psutil` is used for cleanup if present).
- A Chromium browser (Chrome or Edge).
- Nothing is installed by these scripts.

## Run

From the extension folder:

```
..\..\venv\Scripts\python.exe devtools\browser\run_all.py
..\..\venv\Scripts\python.exe devtools\browser\run_all.py --only autosave --only accordion
..\..\venv\Scripts\python.exe devtools\browser\run_all.py --keep-going
..\..\venv\Scripts\python.exe devtools\browser\scenario_autosave.py   (one scenario, full output)
```

`run_all.py` itself needs only the standard library; it runs the scenarios with Forge's Python. A full
run takes about 5-9 minutes. Exit code 0 only if everything passed.

The servers can also be started by hand for manual poking: `preview_tab.py [port] [--keep]`
(then open `http://127.0.0.1:7999/`) and `harness_server.py [port]`. `preview_tab.py` has opt-in
reproduction aids (`PB_SLOW_SAVE`, `PB_SLOW_ALL`, `PB_LOG`, `PB_NO_STALE`, `PB_FULL_PROGRESS`,
`PB_NO_GROUP`, `PB_EXT`), documented at the top of the file; the scenarios never inherit them, they set
the ones they need.

## Environment variables

| Variable | Default |
|---|---|
| `PB_FORGE_PYTHON` | `<forge>/venv/Scripts/python.exe` (or `venv/bin/python`), else the current Python if it has gradio |
| `PB_FORGE_ROOT` | two folders above the extension (for Forge's `style.css` and venv) |
| `PB_CHROME` | first existing of Chrome / Edge under Program Files (and the usual Linux / macOS paths); set it for a per-user install |
| `PB_TAB_PORT` | 7999 |
| `PB_HARNESS_PORT` | 8765 |
| `PB_CDP_PORT` | 9333 (Chrome remote debugging) |
| `PB_SLOW_SAVE` | 0.6 (only `scenario_tab_fixes.py`: seconds each save is slowed down) |

Both servers load the extension's JS through `devenv.extension_js_files()`: every `javascript/*.js`, one
`<script>` each, sorted by file name, which is the order Forge uses (`modules/extensions.py`
`Extension.list_files` sorts with `sorted(os.listdir(...))`; `modules/scripts.py` `list_scripts` keeps
that order when the extension has no `metadata.ini`). A new JS file is picked up without touching the
servers; the helper refuses to run if a `metadata.ini` appears, since that could reorder the files.

If a port is already in use the scripts stop with a message instead of talking to someone else's server.

## Where the output goes

Everything goes below `<system temp>/promptblocks-devtools/` (`tempfile.gettempdir()`):
`preview_data/` (scratch `blocks.json`, thumbnails, tile cache, backups; recreated at every tab start),
`chrome_profile/` (throw-away browser profile), `logs/` (one log per scenario and per server),
`screenshots/`. Nothing is written into the repository.

## Rules

- **Never touches the real data.** `preview_tab.py` points `storage.DATA_FILE` / `THUMB_DIR` at the
  scratch folder before `pb_core.ui` is imported and asserts that no data path lies inside the
  extension folder; the harness keeps its blocks in memory.
- **Not part of pytest.** `pytest.ini` has `testpaths = tests`; no test imports anything from here.
- Every script stops what it started (try / finally). The headless browser is found by its scratch
  `--user-data-dir`, never by image name, so your own Chrome / Edge is never touched.
- The tab scenarios wait for conditions, not fixed times: `preview_tab.py` counts the Gradio events the
  page sends (`/queue/join`) and finishes (`process_completed` on the `/queue/data` stream) in
  `window.__pb`, and `scenario_lib.idle()` waits until all have finished and nothing happened for 300 ms
  (a chained step is sent right after its predecessor). Helpers: `press`, `tile`, `pick_in`, `ctrl_s`,
  `type_into`, `settle`, `wait_for(js, timeout)`; timeouts are generous (30 s), so a busy PC makes a run
  slower instead of failing it. Fixed delays remain only where time itself is tested (the accordion
  message timeouts, the preview debounce) or where a step reproduces a timing on purpose (clicks 50-100 ms
  apart).
