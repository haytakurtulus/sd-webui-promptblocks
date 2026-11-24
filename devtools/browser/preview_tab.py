"""Standalone preview of the PromptBlocks management tab (the real `pb_core.ui.build_tab()`).

Run with Forge's venv Python (it has gradio 4.40). Does not start Forge. Uses a scratch data folder below
the system temp folder (devenv.PREVIEW_DATA), never the extension's real data/: `storage.DATA_FILE` /
`THUMB_DIR` are pointed there BEFORE `pb_core.ui` is imported, and the scratch folder is recreated with a
fixed block set on every start (unless `--keep`).

Usage: python preview_tab.py [port] [--keep]      (port default: PB_TAB_PORT or 7999)

Opt-in environment variables (investigation / reproduction aids):
  PB_EXT=<folder>       serve another copy of the extension code (e.g. an older checkout)
  PB_SLOW_SAVE=<s>      every storage.save_blocks call sleeps this long first (busy Forge / slow disk)
  PB_SLOW_ALL=<s>       every tab handler sleeps this long first (each queued round trip is slow)
  PB_LOG=1              log every handler call (inputs / outputs, duration) to stderr
  PB_NO_STALE=1         switch the stale-form check off (guard.is_stale), to show what it prevents
  PB_FULL_PROGRESS=1    undo show_progress="hidden" of the background refreshes
  PB_NO_GROUP=1         undo the shared concurrency group (one group per function, Gradio's default)
  PB_EXTRA_BLOCKS=<json> extra blocks merged into the fixed scratch block set (a JSON object name -> block)
"""
import json
import os
import sys

sys.dont_write_bytecode = True
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

import devenv  # noqa: E402

EXT = os.path.abspath(os.environ.get("PB_EXT") or str(devenv.EXT_ROOT))
SCRATCH = str(devenv.PREVIEW_DATA)
sys.path.insert(0, EXT)

KEEP = "--keep" in sys.argv
PORT = int(next((a for a in sys.argv[1:] if a.isdigit()), str(devenv.TAB_PORT)))
# Fail before importing gradio (slow) if the port is taken: never serve on top of someone else's server.
devenv.require_free_port(PORT, "tab preview, PB_TAB_PORT", grace=0)

import gradio as gr  # noqa: E402

from pb_core import storage  # noqa: E402

storage.DATA_FILE = os.path.join(SCRATCH, "blocks.json")
storage.THUMB_DIR = os.path.join(SCRATCH, "thumbs")


def _assert_scratch():
    for real in {str(devenv.EXT_ROOT), EXT}:
        for p in (storage.DATA_FILE, storage.THUMB_DIR, storage.backup_dir(), storage.tile_cache_dir()):
            assert not devenv.is_inside(p, real), "scratch path %s is inside the extension folder %s" % (p, real)
    assert devenv.is_inside(storage.DATA_FILE, devenv.SCRATCH_ROOT), storage.DATA_FILE


_assert_scratch()
if KEEP:
    devenv.scratch_dir(SCRATCH)
else:
    devenv.wipe_scratch_dir(SCRATCH)
    with open(storage.DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "blocks": {
            "saber": {
                "category": "PCharacter", "text": "1girl, saber (fate), blonde hair, green eyes",
                "lora": "<lora:saber_v2:0.8>",
                "subs": [
                    {"name": "armor", "text": "silver armor, gauntlets", "mode": "include", "slot": "outfit"},
                    {"name": "dress", "text": "blue dress", "mode": "include", "slot": "outfit"},
                    {"name": "sword", "text": "holding sword", "mode": "random", "slot": None},
                ],
            },
            "rin": {"category": "PCharacter", "text": "1girl, tohsaka rin, twintails", "weight": 3},
            "sakura": {"category": "PCharacter", "text": "1girl, matou sakura", "active": False},
            "swimsuit": {"category": "Clothes", "text": "swimsuit", "slot": "outfit"},
            "runscene": {"category": "PPose", "text": "running, motion blur, ~saber"},
            **json.loads(os.environ.get("PB_EXTRA_BLOCKS") or "{}"),
        }}, f, indent=2)

    from PIL import Image, ImageDraw
    img = Image.new("RGB", (256, 256), (40, 20, 60))
    d = ImageDraw.Draw(img)
    d.ellipse((48, 40, 208, 200), fill=(230, 190, 160))
    d.rectangle((40, 30, 216, 90), fill=(30, 20, 20))
    storage.save_thumb("rin", img)

if os.environ.get("PB_SLOW_SAVE"):
    # Reproduction aid (design notes 23a fix 6): make every save slow, like a busy Forge / slow disk.
    import time as _time
    _orig_save = storage.save_blocks

    def _slow_save(*a, **k):
        _time.sleep(float(os.environ["PB_SLOW_SAVE"]))
        return _orig_save(*a, **k)

    storage.save_blocks = _slow_save

from pb_core import ui  # noqa: E402

_assert_scratch()

with open(os.path.join(EXT, "style.css"), encoding="utf-8") as f:
    CSS = f.read()
# The extension's javascript/*.js in Forge's load order, one <script> each (as Forge does).
JS_TAGS = ""
for _path in devenv.extension_js_files(EXT):
    with open(_path, encoding="utf-8") as f:
        JS_TAGS += "<script>\n" + f.read().replace("</script>", "<\\/script>") + "\n</script>\n"

# Minimal stand-ins for the two WebUI globals the extension's JS uses, plus an event counter for the
# scenarios' condition waits (scenario_lib.idle): window.__pb.sent = Gradio events sent (POST
# /queue/join), .done = events finished ("process_completed" on the /queue/data stream, or a failed
# join), .last = time of the last queue activity. The page is idle when sent == done and nothing happened
# for a short while (a chained .then step is sent right after its predecessor finished).
HEAD = """<script>
window.__errors = [];
window.addEventListener("error", e => window.__errors.push(String(e.message)));
window.addEventListener("unhandledrejection", e => window.__errors.push("rejection: " + e.reason));
window.__pb = { sent: 0, done: 0, last: performance.now(), joining: 0, ids: {}, log: [] };
(function () {
    const pb = window.__pb, f0 = window.fetch.bind(window);
    const touch = () => { pb.last = performance.now(); };
    // An event counts as done when its event_id got "process_completed" (or its join failed). Ids are
    // matched, so a message for an unknown / repeated id cannot make the page look idle too early.
    const recount = () => { pb.done = pb.sent - pb.joining - Object.values(pb.ids).filter(v => !v).length; };
    function completed(id) {
        if (id in pb.ids) pb.ids[id] = true; else pb.early = Object.assign(pb.early || {}, { [id]: true });
        recount();
    }
    async function watchStream(body) {
        const reader = body.getReader(), dec = new TextDecoder();
        let buf = "";
        for (;;) {
            const { value, done } = await reader.read();
            if (done) return;
            buf += dec.decode(value, { stream: true });
            let i;
            while ((i = buf.indexOf("\\n")) >= 0) {
                const line = buf.slice(0, i).trim();
                buf = buf.slice(i + 1);
                if (!line.startsWith("data:")) continue;
                touch();
                try {
                    const m = JSON.parse(line.slice(5));
                    if (m.msg === "process_completed" && m.event_id) completed(m.event_id);
                } catch (e) {}
            }
        }
    }
    window.fetch = async function (input, init) {
        const url = String((input && input.url) || input);
        const method = ((init && init.method) || (input && input.method) || "GET").toUpperCase();
        const join = url.includes("/queue/join");
        if (join) { pb.sent++; pb.joining++; recount(); touch(); }
        let r;
        try { r = await f0(input, init); } catch (e) { if (join) { pb.joining--; recount(); touch(); } throw e; }
        if (join) {
            let id = null;
            try { id = (await r.clone().json()).event_id || null; } catch (e) {}
            pb.joining--;
            if (id && r.ok) pb.ids[id] = !!(pb.early && pb.early[id]);
            recount();
            touch();
        }
        if (url.includes("/queue/data") && method === "GET" && r.body) {
            const [a, b] = r.body.tee();
            watchStream(b).catch(() => {});
            return new Response(a, { status: r.status, statusText: r.statusText, headers: r.headers });
        }
        return r;
    };
})();
function gradioApp() { return document; }
function onUiLoaded(fn) {
    const t = setInterval(() => {
        if (document.querySelector("#pb_save_btn")) { clearInterval(t); fn(); }
    }, 200);
}
</script>
""" + JS_TAGS

tab = ui.build_tab()
if os.environ.get("PB_LOG"):
    # Investigation aid (design notes 24 item 2): log every handler call with a short view of its inputs
    # and outputs to stderr. Lives here (developer tooling), not in ui.py.
    import functools as _ft
    import time as _t

    def _short(v):
        s = repr(v)
        if "PIL" in s or "Image" in type(v).__name__:
            return "<img>"
        return s if len(s) < 60 else s[:57] + "..."

    def _wrap(fn):
        @_ft.wraps(fn)
        def inner(*a, **k):
            t0 = _t.time()
            out = fn(*a, **k)
            o = out if isinstance(out, tuple) else (out,)
            sys.stderr.write("%.3f %-22s %4.0fms in=%s out=%s\n" % (
                t0 % 1000, fn.__name__, (_t.time() - t0) * 1000, [_short(x) for x in a[:8]],
                [_short(x) for x in o if not (isinstance(x, dict) and x == {"__type__": "update"})][:14]))
            sys.stderr.flush()
            return out
        return inner

    for _f in tab.fns.values():
        if _f.fn is not None:
            _f.fn = _wrap(_f.fn)
if os.environ.get("PB_SLOW_ALL"):
    # Reproduction aid (design notes 24 item 2): every handler takes this many extra seconds, like a
    # busy Forge where each queued round trip is slow.
    import functools as _ft2
    import time as _t2

    def _slow(fn):
        @_ft2.wraps(fn)
        def inner(*a, **k):
            _t2.sleep(float(os.environ["PB_SLOW_ALL"]))
            return fn(*a, **k)
        return inner

    for _f in tab.fns.values():
        if _f.fn is not None:
            _f.fn = _slow(_f.fn)
if os.environ.get("PB_NO_STALE"):
    # Test aid (23a fix 6): switch the stale-form check off, to show what it prevents.
    from pb_core import guard as _guard
    _guard.is_stale = lambda seen, current: False
if os.environ.get("PB_FULL_PROGRESS"):
    # Test aid (23a fix 6): undo show_progress="hidden" of the background refreshes.
    for _f in tab.fns.values():
        _f.show_progress = "full"
if os.environ.get("PB_NO_GROUP"):
    # Test aid (23a fix 6): undo the shared concurrency group (Gradio's default: one group per
    # function), to check that the stale-Save guard alone keeps the form intact.
    for _f in tab.fns.values():
        _f.concurrency_id = str(id(_f.fn))
        _f.concurrency_limit = "default"
with gr.Blocks(css=CSS, head=HEAD, analytics_enabled=False, title="PromptBlocks tab preview") as demo:
    with gr.Tabs():
        with gr.Tab("PromptBlocks", elem_id="tab_promptblocks_tab"):
            tab.render()
        with gr.Tab("Other tab", elem_id="tab_other"):
            gr.Markdown("Another tab (to check the floating Save hides).")

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=PORT, show_api=False, inbrowser=False,
                allowed_paths=[SCRATCH, EXT], prevent_thread_lock=True)

    from pb_core import parser, subrows, weights

    @demo.app.get("/promptblocks/blocks")
    def get_blocks():
        # Same shape as scripts/promptblocks.py get_blocks.
        blocks = storage.load_blocks()
        return {
            "block_symbol": parser.BLOCK_SYMBOL, "category_symbol": parser.CATEGORY_SYMBOL,
            "name_pattern": parser.NAME_PATTERN, "sub_separator": parser.SUB_SEPARATOR,
            "slot_draw_separator": parser.SLOT_DRAW_SEPARATOR,
            "blocks": {n: {**b, "active": weights.is_active(b), "thumb_v": storage.thumb_mtime(n),
                           **subrows.api_block_slots(b), **subrows.api_block_lora(b)}
                       for n, b in blocks.items()},
        }

    print("tab preview on http://127.0.0.1:%d/ (data: %s)" % (PORT, SCRATCH), flush=True)
    import time
    while True:
        time.sleep(3600)
