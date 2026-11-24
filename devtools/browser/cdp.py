"""Tiny Chrome DevTools Protocol driver for the headless browser scenarios.

Run with Forge's venv Python (it ships the `websockets` package). Starts a headless Chrome / Edge with a
throw-away profile below the system temp folder; never touches the user's own browser or profile. The
started browser is identified by that profile path (`--user-data-dir`), never by image name, and is
always killed at the end (also any leftover of an earlier, crashed run with the same profile).
"""
import asyncio
import base64
import json
import subprocess
import time
import urllib.request

import websockets

import devenv


class Browser:
    def __init__(self, width=1400, height=900):
        self.profile = devenv.CHROME_PROFILE
        self.port = devenv.CDP_PORT
        chrome = devenv.chrome_exe()
        devenv.kill_marked(self.profile)  # leftovers of an earlier crashed run (our profile only)
        devenv.require_free_port(self.port, "Chrome remote debugging, PB_CDP_PORT")
        devenv.wipe_scratch_dir(self.profile)
        self.proc = subprocess.Popen([
            chrome, "--headless=new", f"--remote-debugging-port={self.port}",
            "--remote-allow-origins=*",
            f"--user-data-dir={self.profile}",
            f"--window-size={width},{height}", "--no-first-run", "--no-default-browser-check",
            "--disable-gpu", "--hide-scrollbars", "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.ws = None
        self.n = 0

    async def connect(self):
        page = None
        for _ in range(75):
            if self.proc.poll() is not None:
                raise RuntimeError("headless browser exited at start (code %s)" % self.proc.returncode)
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json", timeout=2))
                page = next(t for t in tabs if t["type"] == "page")
                break
            except Exception:
                time.sleep(0.2)
        if page is None:
            raise RuntimeError("headless browser did not start")
        self.ws = await websockets.connect(page["webSocketDebuggerUrl"], max_size=None)
        await self.cmd("Page.enable")
        await self.cmd("Runtime.enable")

    async def cmd(self, method, **params):
        self.n += 1
        mid = self.n
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result", {})

    async def goto(self, url, wait_for=None, timeout=40):
        await self.cmd("Page.navigate", url=url)
        if wait_for:
            end = time.time() + timeout
            while time.time() < end:
                if await self.js(f"!!document.querySelector({json.dumps(wait_for)})"):
                    return True
                await asyncio.sleep(0.3)
            raise RuntimeError("timeout waiting for " + wait_for)

    async def js(self, code):
        """Evaluate an expression or the body of an async function (use `return`)."""
        if "return" in code:
            code = "(async () => {" + code + "})()"
        r = await self.cmd("Runtime.evaluate", expression=code, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in r:
            raise RuntimeError(json.dumps(r["exceptionDetails"])[:800])
        return r["result"].get("value")

    async def shot(self, name, full=False):
        """Screenshot into the scratch screenshots folder; returns the path."""
        params = {"format": "png"}
        if full:
            params["captureBeyondViewport"] = True
            m = await self.cmd("Page.getLayoutMetrics")
            s = m["cssContentSize"]
            params["clip"] = {"x": 0, "y": 0, "width": s["width"], "height": s["height"], "scale": 1}
        r = await self.cmd("Page.captureScreenshot", **params)
        path = devenv.scratch_dir(devenv.SHOT_DIR) / name
        with open(path, "wb") as f:
            f.write(base64.b64decode(r["data"]))
        return str(path)

    async def key(self, key, code, ctrl=False):
        mods = 2 if ctrl else 0
        for t in ("keyDown", "keyUp"):
            await self.cmd("Input.dispatchKeyEvent", type=t, key=key, code=code, modifiers=mods,
                           windowsVirtualKeyCode=ord(key.upper()) if len(key) == 1 else 13)

    async def click(self, selector):
        box = await self.js(
            f"const e = document.querySelector({json.dumps(selector)}); if (!e) return null;"
            "e.scrollIntoView({block: 'center'}); const r = e.getBoundingClientRect();"
            "return [r.left + r.width / 2, r.top + r.height / 2];")
        if not box:
            raise RuntimeError("no element " + selector)
        for t in ("mousePressed", "mouseReleased"):
            await self.cmd("Input.dispatchMouseEvent", type=t, x=box[0], y=box[1], button="left",
                           clickCount=1)

    async def close(self):
        """Ask the browser to quit, then kill whatever is left of it (its tree, and anything else
        started with our scratch profile)."""
        if self.ws is not None:
            try:
                await asyncio.wait_for(self.cmd("Browser.close"), timeout=5)
            except Exception:
                pass
            try:
                await asyncio.wait_for(self.ws.close(), timeout=3)
            except Exception:
                pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        self.shutdown()

    def shutdown(self):
        """Synchronous hard stop; safe to call more than once."""
        if self.proc.poll() is None:
            devenv.kill_tree(self.proc.pid)
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        left = devenv.kill_marked(self.profile)
        if left:
            print("WARNING: headless browser processes still running: %s" % left, flush=True)


def run(main, width=1400, height=900):
    """Start a headless browser, run `await main(browser)`, always stop the browser."""
    async def wrapper(b):
        try:
            await b.connect()
            await main(b)
        finally:
            await b.close()

    b = Browser(width, height)
    try:
        asyncio.run(wrapper(b))
    finally:
        b.shutdown()  # also on KeyboardInterrupt / a broken event loop
