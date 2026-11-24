"""Shared boilerplate of the browser scenarios: server start / stop, PASS / FAIL collection, exit code,
and the page helpers (tile click, typing, dropdown pick, state probes) the scenarios have in common.

Importing this module with a Python that has no `websockets` re-runs the calling scenario with Forge's
Python (devenv.forge_python()).
"""
import os
import subprocess
import sys

sys.dont_write_bytecode = True

import devenv  # noqa: E402

try:
    import websockets  # noqa: F401
except ImportError:
    _py = devenv.forge_python()
    if os.path.normcase(os.path.abspath(_py)) != os.path.normcase(os.path.abspath(sys.executable)):
        sys.exit(subprocess.call([_py, os.path.abspath(sys.argv[0])] + sys.argv[1:],
                                 env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1")))
    raise SystemExit("The `websockets` package is missing in %s (use Forge's venv Python)" % _py)

import asyncio  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
import traceback  # noqa: E402
import urllib.request  # noqa: E402

import cdp  # noqa: E402

sys.path.insert(0, str(devenv.EXT_ROOT))
from pb_core.subrows import ROW_COUNT  # noqa: E402  (pure module, no gradio)

TAB_URL = "http://127.0.0.1:%d/" % devenv.TAB_PORT
HARNESS_URL = "http://127.0.0.1:%d" % devenv.HARNESS_PORT
DATA_FILE = str(devenv.PREVIEW_DATA / "blocks.json")
TILE_DIR = str(devenv.PREVIEW_DATA / "tile_cache")
TA = "#txt2img_prompt textarea"
# Sub-block names of a form whose rows are all empty (one entry per row, section 36 C: 6 rows).
BLANK_SUBS = [""] * ROW_COUNT

# ------------------------------------------------------------------ results

FAILS = []


def _dump(obj):
    return json.dumps(obj)  # ASCII only (Windows console)


def expect(step, st, **want):
    """Compare a state dict with expectations. `key=v`: equal; `key_has=v`: substring of st[key];
    `key_not=v`: not a substring. Prints one JSON line."""
    bad = {}
    for k, v in want.items():
        if k.endswith("_has"):
            if v not in (st.get(k[:-4]) or ""):
                bad[k] = v
        elif k.endswith("_not"):
            if v in (st.get(k[:-4]) or ""):
                bad[k] = v
        elif st.get(k) != v:
            bad[k] = v
    line = {"step": step, "ok": not bad, **({"expected": bad} if bad else {}), "state": st}
    print(_dump(line), flush=True)
    if bad:
        FAILS.append(step)


def check(cond, label, detail=None):
    """Boolean check; prints one PASS / FAIL line (with the detail, shortened on PASS)."""
    tail = ""
    if detail is not None:
        tail = "  " + _dump(detail)
        if cond and len(tail) > 300:
            tail = tail[:297] + "..."
    print(("PASS " if cond else "FAIL ") + label + tail, flush=True)
    if not cond:
        FAILS.append(label)


def fail(label):
    FAILS.append(label)


async def check_page_errors(b, label="window.__errors"):
    errors = await b.js("return window.__errors;")
    print(_dump({"step": label, "ok": errors == [], "errors": errors}), flush=True)
    if errors:
        FAILS.append(label)


def finish():
    """Print the final line and exit: 0 = all passed, 1 = something failed."""
    if FAILS:
        print("RESULT: %d FAILED: %s" % (len(FAILS), "; ".join(FAILS)), flush=True)
    else:
        print("RESULT: ALL PASS", flush=True)
    sys.exit(1 if FAILS else 0)


# ------------------------------------------------------------------ servers

SERVERS = {
    "tab": ("preview_tab.py", devenv.TAB_PORT, TAB_URL, "tab preview, PB_TAB_PORT"),
    "harness": ("harness_server.py", devenv.HARNESS_PORT, HARNESS_URL + "/", "JS harness, PB_HARNESS_PORT"),
}
# Reproduction aids of preview_tab.py that change behaviour: never inherited, only set on purpose.
_AIDS = ("PB_SLOW_SAVE", "PB_SLOW_ALL", "PB_NO_STALE", "PB_FULL_PROGRESS", "PB_NO_GROUP", "PB_EXTRA_BLOCKS")


def start_server(kind, env=None):
    """Start preview_tab.py ("tab") or harness_server.py ("harness") with Forge's Python and wait until
    it answers. `env`: extra environment variables (e.g. {"PB_SLOW_SAVE": "0.6"})."""
    script, port, url, what = SERVERS[kind]
    devenv.require_free_port(port, what)
    full_env = {k: v for k, v in os.environ.items() if k not in _AIDS}
    full_env.update(GRADIO_ANALYTICS_ENABLED="False", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    full_env.update(env or {})
    log = devenv.log_path("%s_%d.log" % (kind, port))
    fh = open(log, "w", encoding="utf-8")
    proc = subprocess.Popen([devenv.forge_python(), str(devenv.HERE / script), str(port)], env=full_env,
                            stdout=fh, stderr=subprocess.STDOUT, cwd=str(devenv.HERE))
    proc._pb_log = fh
    end = time.time() + 120
    while True:
        if proc.poll() is not None:
            fh.close()
            with open(log, encoding="utf-8", errors="replace") as f:
                tail = f.read()[-1500:]
            raise devenv.SetupError("%s exited at start (code %s); log %s:\n%s" % (script, proc.returncode, log, tail))
        try:
            urllib.request.urlopen(url, timeout=1)
            return proc
        except Exception:
            pass
        if time.time() > end:
            stop_server(proc)
            raise devenv.SetupError("%s did not answer on %s within 120 s; log: %s" % (script, url, log))
        time.sleep(0.3)


def stop_server(proc):
    if proc.poll() is None:
        devenv.kill_tree(proc.pid)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        print("WARNING: server pid %d did not stop" % proc.pid, flush=True)
    fh = getattr(proc, "_pb_log", None)
    if fh:
        fh.close()


def run_part(kind, main, env=None):
    """Fresh server + fresh headless browser, run `await main(browser)`, always stop both. A crash
    (exception) is recorded as a failure."""
    proc = None
    try:
        proc = start_server(kind, env)
        cdp.run(main)
    except Exception as e:
        traceback.print_exc()
        check(False, "%s crashed" % getattr(main, "__name__", "main"), repr(e)[:500])
    finally:
        if proc is not None:
            stop_server(proc)


# ------------------------------------------------------------------ management tab helpers

STATE = """const val = s => { const e = document.querySelector(s); return e ? e.value : null; };
const ep = document.querySelector('#pb_form_epoch');
const r = ep ? ep.getBoundingClientRect() : null;
return {name: val('#pb_name textarea, #pb_name input'), picker: val('#pb_picker input'),
        text: val('#pb_text textarea'), status: document.querySelector('#pb_status')?.innerText.trim(),
        dirty: document.querySelector('#pb_save_btn').classList.contains('pb-dirty'),
        fabDirty: document.querySelector('#pb_save_fab').classList.contains('pb-dirty'),
        epoch: ep ? ep.textContent.trim() : null, epochBox: r ? [r.width, r.height] : null};"""

FORM = """const v = s => { const e = document.querySelector(s); return e ? e.value : null; };
const t = s => { const e = document.querySelector(s); return e ? e.innerText.trim() : null; };
return {name: v('#pb_name textarea, #pb_name input'), category: v('#pb_category input'),
        text: v('#pb_text textarea'), lora: v('#pb_lora textarea, #pb_lora input'),
        subs: [...document.querySelectorAll('[id^="pb_sub_name_"]')].map(e => {
            const f = e.querySelector('textarea, input'); return f ? f.value : null; }),
        picker: v('#pb_picker input'), status: t('#pb_status'),
        hint: t('#pb_block_group .pb-hintline'), health: t('#pb_health_report')};"""


async def S(b):
    """Switch state: name, picker, text, status, Save markers, form epoch."""
    return await b.js(STATE)


async def F(b):
    """Form state: name, category, text, lora, sub names, picker, status, hint, health."""
    return await b.js(FORM)


# ---- condition waits (the tab preview counts Gradio events in window.__pb, see preview_tab.HEAD) ----
# Generous timeouts: a busy machine must make a scenario slower, not make it fail.

WAIT = 30  # seconds
QUIET_MS = 300  # no queue activity for this long = the last response is rendered, no chained step follows


async def wait_for(b, cond_js, timeout=10):
    """Poll `cond_js` (a JS function body with `return`) until it is truthy; True, or False on timeout."""
    end = time.time() + timeout
    while time.time() < end:
        if await b.js(cond_js):
            return True
        await asyncio.sleep(0.03)
    return False


async def sent(b):
    """Number of Gradio events the page has sent so far."""
    return await b.js("return window.__pb ? window.__pb.sent : 0;")


async def idle(b, timeout=WAIT):
    """Wait until every Gradio event the page sent has finished and nothing happened for QUIET_MS."""
    ok = await wait_for(b, "return !!window.__pb && window.__pb.sent === window.__pb.done && "
                           "performance.now() - window.__pb.last > %d;" % QUIET_MS, timeout)
    if not ok:
        raise RuntimeError("the tab did not become idle within %d s: %s"
                           % (timeout, await b.js("return JSON.stringify(window.__pb);")))


async def after_event(b, before, timeout=WAIT):
    """Wait until an event was sent after the count `before` (from sent()), then until idle."""
    if not await wait_for(b, "return (window.__pb ? window.__pb.sent : 0) > %d;" % before, timeout):
        raise RuntimeError("no Gradio event was sent within %d s" % timeout)
    await idle(b, timeout)


async def settle(b):
    """Wait until the tab is idle, for steps that may or may not have sent an event (e.g. typing): the
    quiet period starts NOW, so an event the step triggers a few ms later is still waited for."""
    await b.js("if (window.__pb) window.__pb.last = performance.now(); return 1;")
    await idle(b)


async def press(b, selector):
    """Real click on `selector` that sends an event; returns when the tab is idle again."""
    before = await sent(b)
    await b.click(selector)
    await after_event(b, before)


async def ctrl_s(b):
    """Ctrl+S (the JS clicks Save after 150 ms); returns when the save and its chain have finished."""
    before = await sent(b)
    await b.key("s", "KeyS", ctrl=True)
    await after_event(b, before)


async def tile_now(b, name):
    """Real click on the gallery tile of block `name`, no wait."""
    ok = await b.js("const img = [...document.querySelectorAll('#pb_gallery img')]"
                    ".find(i => new RegExp('/%s(_\\\\d+)?\\\\.(png|webp)').test(decodeURIComponent(i.src)));"
                    "if (!img) return false; document.querySelectorAll('#pbtile').forEach(e => e.removeAttribute('id'));"
                    "img.closest('button').id = 'pbtile'; return true;" % name)
    assert ok, "no tile " + name
    await b.click("#pbtile")


async def tile(b, name):
    """Real click on a tile, then wait until its event has finished."""
    before = await sent(b)
    await tile_now(b, name)
    await after_event(b, before)


async def type_into(b, selector, text):
    """Real (trusted) typing: click, caret to the end, Input.insertText, then wait until idle."""
    await b.click(selector)
    await b.js("const e = document.querySelector(%s); e.focus(); e.selectionStart = e.selectionEnd = e.value.length;"
               "return 1;" % json.dumps(selector))
    await b.cmd("Input.insertText", text=text)
    await settle(b)


async def type_real(b, selector, text, per_char=0.0):
    """Real click into the field, then trusted typing (Input.insertText), no wait afterwards."""
    await b.click(selector)
    await b.js("const e = document.querySelector(%s); e.selectionStart = e.selectionEnd = e.value.length;"
               "return 1;" % json.dumps(selector))
    if per_char:
        for ch in text:
            await b.cmd("Input.insertText", text=ch)
            await asyncio.sleep(per_char)
    else:
        await b.cmd("Input.insertText", text=text)


_OPTION = ("const li = [...document.querySelectorAll('%s ul.options li')]"
           ".find(l => l.getAttribute('data-value') === %s || l.innerText.replace(/^\\s*\\u2713/, '').trim() === %s);")


async def pick_in(b, root, name, event=True):
    """Choose `name` in the dropdown `root` (e.g. "#pb_picker") by typing it and clicking the option;
    then wait until the event it sends has finished (event=False: the pick sends none, e.g. the value
    is already selected; then only wait until idle)."""
    await b.click(root + " input")
    await b.js("const e = document.querySelector('%s input'); e.select(); return 1;" % root)
    await b.cmd("Input.insertText", text=name)
    found = await wait_for(b, (_OPTION + "return !!li;") % (root, json.dumps(name), json.dumps(name)), WAIT)
    assert found, "no option %s in %s" % (name, root)
    await b.js((_OPTION + "document.querySelectorAll('#pbopt').forEach(e => e.removeAttribute('id'));"
                "li.id = 'pbopt'; return true;") % (root, json.dumps(name), json.dumps(name)))
    before = await sent(b)
    await b.click("#pbopt")
    if event:
        await after_event(b, before)
    else:
        await settle(b)


async def dropdown_pick(b, name):
    await pick_in(b, "#pb_picker", name)


async def load_tab(b):
    """Open the tab preview and wait until the gallery is there, the promptblocks_*.js files has set up the tab
    (the Save button's tooltip) and no event is running."""
    await b.goto(TAB_URL, wait_for="#pb_gallery img")
    assert await wait_for(b, "return !!window.__pb && !!document.querySelector('#pb_save_btn').title "
                             "&& document.querySelectorAll('#pb_gallery img').length > 0;", WAIT), "tab not ready"
    await idle(b)


BACKUP_DIR = str(devenv.PREVIEW_DATA / "backups")


def disk():
    """The scratch data as it is on disk: {"mtime": blocks.json mtime_ns, "blocks": dict, "backups": set
    of backup file names}."""
    with open(DATA_FILE, encoding="utf-8") as f:
        blocks = json.load(f)["blocks"]
    try:
        backups = set(os.listdir(BACKUP_DIR))
    except OSError:
        backups = set()
    return {"mtime": os.stat(DATA_FILE).st_mtime_ns, "blocks": blocks, "backups": backups}


async def open_more(b):
    """Open the "More actions" accordion if it is closed."""
    shown = "const e = document.querySelector('#pb_cat_rename_btn'); return !!e && e.offsetParent !== null;"
    if not await b.js(shown):
        await b.click("#pb_manage .label-wrap")
        assert await wait_for(b, shown, WAIT), "More actions did not open"


# ------------------------------------------------------------------ JS harness helpers

def post(path, obj=None):
    req = urllib.request.Request(HARNESS_URL + path, data=json.dumps(obj or {}).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=5))


KEYS = {"ArrowRight": 39, "ArrowLeft": 37, "ArrowDown": 40, "ArrowUp": 38, "Home": 36, "End": 35,
        "Escape": 27, "Enter": 13, "a": 65}


async def key(b, k, shift=False, ctrl=False, times=1):
    mods = (8 if shift else 0) | (2 if ctrl else 0)
    for _ in range(times):
        for t in ("rawKeyDown", "keyUp"):
            await b.cmd("Input.dispatchKeyEvent", type=t, key=k, code=k if len(k) > 1 else "Key" + k.upper(),
                        windowsVirtualKeyCode=KEYS[k], modifiers=mods)


async def type_text(b, text):
    await b.cmd("Input.insertText", text=text)


async def click_at(b, x, y):
    await b.cmd("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
    for t in ("mousePressed", "mouseReleased"):
        await b.cmd("Input.dispatchMouseEvent", type=t, x=x, y=y, button="left", clickCount=1)


async def rect(b, sel):
    return await b.js(f"const e = document.querySelector({json.dumps(sel)}); e.scrollIntoView({{block: 'center'}});"
                      "const r = e.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom];")


async def click(b, sel):
    l, t, r, bt = await rect(b, sel)
    await click_at(b, (l + r) / 2, (t + bt) / 2)


async def clear_and_type(b, sel, text):
    """Harness inputs: click, Ctrl+A, type."""
    await click(b, sel)
    await key(b, "a", ctrl=True)
    await type_text(b, text)


async def set_prompt(b, text):
    """Real input: click into the prompt, select all, type; close any popup with Escape."""
    await click(b, TA)
    await key(b, "a", ctrl=True)
    await type_text(b, text)
    await asyncio.sleep(0.05)
    await key(b, "Escape")


async def select_range(b, start, length):
    """Real keys: Ctrl+Home, ArrowRight * start, Shift+ArrowRight * length (textarea must be focused)."""
    await key(b, "Home", ctrl=True)
    await key(b, "ArrowRight", times=start)
    await key(b, "ArrowRight", shift=True, times=length)


async def sel_of(b):
    return await b.js(f"const t = document.querySelector({json.dumps(TA)}); return [t.selectionStart, t.selectionEnd];")


async def val(b, sel, prop="value"):
    return await b.js(f"return document.querySelector({json.dumps(sel)}).{prop};")


async def text_of(b, sel):
    return await b.js(f"return document.querySelector({json.dumps(sel)}).textContent;")


async def harness_load(b, dark=True):
    """Reset the harness blocks and (re)load the fake WebUI page; wait until the popup element exists."""
    post("/harness/reset")
    await b.goto(HARNESS_URL + ("/?dark=1" if dark else "/"), wait_for=TA)
    for _ in range(50):
        if await b.js("return !!document.querySelector('.pb-popup');"):
            break
        await asyncio.sleep(0.1)
    await asyncio.sleep(0.4)
