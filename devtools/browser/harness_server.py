"""Browser harness for the extension's javascript/*.js (accordion extras + autocomplete popup).

Serves a fake WebUI page plus the real javascript/*.js (one <script> each, in Forge's load order, see
devenv.extension_js_files) / style.css, and answers the PromptBlocks routes with the real pb_core logic
over an in-memory block set (mirrors scripts/promptblocks.py). Never reads or writes the extension's
data/ folder.

The page also loads Gradio 4.40's own index css, the Default theme's variables (generated with gradio when
importable, i.e. run with Forge's venv Python) and Forge's style.css, in Forge's order (Gradio css in
<head>, Forge + extension style.css before </body>). `/?dark=1` puts `dark` on <body> like Gradio does.

Usage: python harness_server.py [port]      (port default: PB_HARNESS_PORT or 8765)

Test-only routes (POST, JSON): /harness/generate {prompt, seed, tab}, /harness/set_blocks {blocks},
/harness/blocks_delay {seconds}, /harness/state, /harness/reset.
"""
import json
import os
import random
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.dont_write_bytecode = True

import devenv  # noqa: E402

EXT = str(devenv.EXT_ROOT)
FORGE_STYLE = devenv.FORGE_ROOT / "style.css"
sys.path.insert(0, EXT)

from pb_core import bans, create, parser, picks, subrows, weights  # noqa: E402

GRADIO_CSS = None
try:
    import gradio as gr  # only with Forge's venv Python
    THEME_CSS = gr.themes.Default()._get_theme_css()
    _front = os.path.join(os.path.dirname(gr.__file__), "templates", "frontend")
    with open(os.path.join(_front, "index.html"), encoding="utf-8") as _f:
        _m = re.search(r"assets/(index-[^\"'/]+\.css)", _f.read())
    if _m:
        GRADIO_CSS = os.path.join(_front, "assets", _m.group(1))
except Exception as e:  # system Python: no gradio -> no theme variables (fallbacks apply)
    THEME_CSS = "/* no gradio: %s */" % type(e).__name__
if GRADIO_CSS is None:
    sys.stderr.write("WARNING: Gradio's index css not found; the page runs without it\n")
if not FORGE_STYLE.is_file():
    sys.stderr.write("WARNING: Forge's style.css not found at %s (set PB_FORGE_ROOT)\n" % FORGE_STYLE)

LAST_PICKS = {"txt2img": [], "img2img": []}
LAST_GENERATED = {"txt2img": False, "img2img": False}

INITIAL_BLOCKS = {
    "saber": {
        "category": "PCharacter", "text": "1girl, saber (fate), blonde hair", "lora": "<lora:saber:0.8>",
        "subs": [
            {"name": "armor", "text": "silver armor", "mode": "include", "slot": "outfit"},
            {"name": "dress", "text": "blue dress", "mode": "include", "slot": "outfit"},
            {"name": "sword", "text": "holding sword", "mode": "random", "slot": None},
        ],
    },
    "rin": {"category": "PCharacter", "text": "1girl, tohsaka rin", "weight": 3},
    "sakura": {"category": "PCharacter", "text": "1girl, matou sakura", "active": False},
    "swimsuit": {"category": "Clothes", "text": "swimsuit", "slot": "outfit"},
    "ghost": {"category": "Dead", "text": "ghost", "active": False},
    "runscene": {"category": "PPose", "text": "running, motion blur"},
}
BLOCKS = json.loads(json.dumps(INITIAL_BLOCKS))
BLOCKS_DELAY = [0.0]  # seconds; lets a test keep a /promptblocks/blocks request in flight


def accordion(tab):
    # Same markup as PromptBlocksScript.ui() in scripts/promptblocks.py, inside gr.HTML's .prose div.
    return (
        f'<div class="prose">'
        f'<div class="pb-acc">'
        f'<div id="pb_preview_{tab}" class="pb-preview">Type a prompt to see an example.</div>'
        f'<button id="pb_reroll_{tab}" class="pb-reroll" type="button">Another example</button>'
        f'<button id="pb_pin_{tab}" class="pb-reroll pb-pin" type="button"'
        f' title="Replace %Category / ~name*slot in the prompt with what the last Generate picked">'
        f'Pin last picks</button>'
        f'<div id="pb_pin_msg_{tab}" class="pb-create-msg pb-pin-msg"></div>'
        f'<div id="pb_create_row_{tab}" class="pb-create">'
        f'<input id="pb_new_name_{tab}" class="pb-create-input" type="text" placeholder="New block name"'
        f' autocomplete="off" spellcheck="false">'
        f'<input id="pb_new_cat_{tab}" class="pb-create-input" type="text" placeholder="Category"'
        f' list="pb_cats_{tab}" autocomplete="off" spellcheck="false">'
        f'<datalist id="pb_cats_{tab}"></datalist>'
        f'<button id="pb_create_{tab}" class="pb-reroll pb-create-btn" type="button"'
        f' title="Save the selected prompt text as a new block and replace it with ~name">'
        f'Save selection as block</button>'
        f'</div>'
        f'<div id="pb_create_msg_{tab}" class="pb-create-msg"></div>'
        f'</div>'
        f'</div>'
    )


def _js_files():
    # Re-read on every request, like the files themselves: a new or renamed file needs no restart.
    return {p.name: str(p) for p in devenv.extension_js_files(EXT)}


def js_tags():
    # One <script src> per file in Forge's load order (devenv.extension_js_files), as Forge does.
    return "".join('<script src="/js/%s"></script>\n' % name for name in _js_files())


def page(dark):
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>PromptBlocks harness</title>
<link rel="stylesheet" href="/gradio.css">
<style id="theme">{THEME_CSS}</style>
<style>
 body {{ background: var(--body-background-fill, #111); color: var(--body-text-color, #ddd);
        font-family: sans-serif; margin: 20px; }}
 #txt2img_prompt textarea, #img2img_prompt textarea {{ width: 600px; height: 90px; font-size: 14px;
        line-height: 1.4; padding: 8px; }}
 .acc {{ width: 640px; padding: 8px; background: var(--block-background-fill, #222); }}
 .spacer {{ height: 500px; }}
</style></head><body{' class="dark"' if dark else ''}>
<div class="gradio-container gradio-container-4-40-0">
<div id="txt2img_prompt"><textarea></textarea></div>
<!-- Forge's Interrupt button: ui.js shows it (display block) while a generation runs. -->
<button id="txt2img_interrupt" type="button" style="display: none">Interrupt</button>
<div class="acc">
<div id="pb_block_seed_txt2img"><input type="number" value="-1"></div>
{accordion("txt2img")}
</div>
<div class="spacer"></div>
<div id="img2img_prompt"><textarea></textarea></div>
<button id="img2img_interrupt" type="button" style="display: none">Interrupt</button>
<div class="acc">
<div id="pb_block_seed_img2img"><input type="number" value="-1"></div>
{accordion("img2img")}
</div>
<div class="spacer"></div>
</div>
<script>
 window.__errors = [];
 window.addEventListener("error", e => window.__errors.push(String(e.message)));
 window.addEventListener("unhandledrejection", e => window.__errors.push("rejection: " + e.reason));
 window.__blockFetches = 0;
 const _fetch = window.fetch;
 window.fetch = (u, o) => {{ if (String(u).startsWith("/promptblocks/blocks")) window.__blockFetches++; return _fetch(u, o); }};
 function gradioApp() {{ return document; }}
 function onUiLoaded(fn) {{ window.addEventListener("load", () => fn()); }}
</script>
{js_tags()}
<link rel="stylesheet" href="/forge_style.css">
<link rel="stylesheet" href="/style.css">
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, body, ctype, code=200):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, ctype):
        if path is None or not os.path.isfile(path):
            return self._send("/* missing: %s */" % os.path.basename(str(path)), ctype)
        with open(path, "rb") as f:
            self._send(f.read(), ctype)

    def _json(self, obj):
        self._send(json.dumps(obj), "application/json")

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path == "/":
            self._send(page("dark=1" in query), "text/html; charset=utf-8")
        elif path.startswith("/js/") and path[4:] in _js_files():
            self._file(_js_files()[path[4:]], "application/javascript; charset=utf-8")
        elif path == "/style.css":
            self._file(os.path.join(EXT, "style.css"), "text/css; charset=utf-8")
        elif path == "/forge_style.css":
            self._file(str(FORGE_STYLE), "text/css; charset=utf-8")
        elif path == "/gradio.css":
            self._file(GRADIO_CSS, "text/css; charset=utf-8")
        elif path == "/promptblocks/blocks":
            if BLOCKS_DELAY[0]:
                import time
                time.sleep(BLOCKS_DELAY[0])
            # Same shape as scripts/promptblocks.py get_blocks (thumb_v is None: no thumbnails here).
            self._json({
                "block_symbol": parser.BLOCK_SYMBOL,
                "category_symbol": parser.CATEGORY_SYMBOL,
                "name_pattern": parser.NAME_PATTERN,
                "sub_separator": parser.SUB_SEPARATOR,
                "slot_draw_separator": parser.SLOT_DRAW_SEPARATOR,
                "blocks": {
                    n: {**b, "active": weights.is_active(b), "thumb_v": None,
                        **subrows.api_block_slots(b), **subrows.api_block_lora(b)}
                    for n, b in BLOCKS.items()
                    if isinstance(b, dict)
                },
            })
        else:
            self._send("not found", "text/plain", 404)

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/harness/generate":
            # Stand-in for Script.process(): record the first image's picks for the tab and that a
            # generation with blocks loaded happened.
            tab = req.get("tab", "txt2img")
            LAST_PICKS[tab] = []
            LAST_GENERATED[tab] = bool(BLOCKS)
            if not BLOCKS:
                return self._json({"picks": []})
            _, pk, _ = picks.expand_recorded([req.get("prompt", "")], [req.get("seed", 0)], BLOCKS)
            LAST_PICKS[tab] = pk[0]
            return self._json({"picks": pk[0]})
        if self.path == "/harness/set_blocks":
            BLOCKS.clear()
            BLOCKS.update(req.get("blocks") or {})
            return self._json({"ok": True, "n": len(BLOCKS)})
        if self.path == "/harness/blocks_delay":
            BLOCKS_DELAY[0] = float(req.get("seconds", 0))
            return self._json({"ok": True})
        if self.path == "/harness/state":
            return self._json({"blocks": BLOCKS, "picks": LAST_PICKS, "generated": LAST_GENERATED})
        if self.path == "/harness/reset":
            BLOCKS.clear()
            BLOCKS.update(json.loads(json.dumps(INITIAL_BLOCKS)))
            for t in LAST_PICKS:
                LAST_PICKS[t] = []
                LAST_GENERATED[t] = False
            BLOCKS_DELAY[0] = 0.0
            return self._json({"ok": True})
        if self.path == "/promptblocks/pin":
            tab = req.get("tab", "txt2img")
            stored = LAST_PICKS.get(tab, []) if tab in LAST_PICKS else []
            generated = LAST_GENERATED.get(tab, False) if tab in LAST_GENERATED else False
            return self._json(picks.pin_response(req.get("prompt", ""), stored, BLOCKS, generated))
        if self.path == "/promptblocks/create":
            new_blocks, err = create.build_new_block(BLOCKS, req.get("name", ""), req.get("category", ""),
                                                     req.get("text", ""))
            if err:
                return self._json({"ok": False, "error": err})
            BLOCKS.clear()
            BLOCKS.update(new_blocks)
            name = req.get("name", "").strip()
            return self._json({"ok": True, "name": name, "token": parser.BLOCK_SYMBOL + name})
        if self.path != "/promptblocks/preview":
            return self._send("not found", "text/plain", 404)
        seed_in = req.get("seed")
        from_field = seed_in is not None and seed_in >= 0
        seed = seed_in if from_field else random.randrange(2**32)
        trace, ban_events = [], []
        try:
            text = parser.expand(req.get("prompt", ""), BLOCKS, random.Random(seed), trace=trace,
                                 ban_events=ban_events)
        except parser.BlockCycleError as e:
            return self._json({"error": str(e)})
        unknown, all_inactive = parser.preview_warnings(text, BLOCKS)
        self._json({
            "text": text, "seed": seed, "from_field": from_field,
            "unknown": unknown, "all_inactive": all_inactive,
            "subs_picked": subrows.api_trace(trace),
            "occupied_slots": sorted(parser.occupied_slots(req.get("prompt", ""), BLOCKS)),
            "bans": bans.ban_lines(ban_events),
        })

    def log_message(self, *args):
        pass


class Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second server bind a port that is already in use; without it the
    # bind fails, so we never end up next to someone else's server on the same port.
    allow_reuse_address = os.name != "nt"
    daemon_threads = True


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else devenv.HARNESS_PORT
    devenv.require_free_port(port, "JS harness, PB_HARNESS_PORT", grace=0)
    server = Server(("127.0.0.1", port), Handler)
    print("harness on http://127.0.0.1:%d" % port, flush=True)
    server.serve_forever()
