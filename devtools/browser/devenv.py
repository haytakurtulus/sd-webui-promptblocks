"""Paths, ports, executables and process cleanup for the browser scenarios (standard library only).

Nothing here writes into the repository: all scratch output goes below
`tempfile.gettempdir()/promptblocks-devtools/`.

Environment variables (all optional):
  PB_FORGE_PYTHON   Forge's venv Python (needs gradio + websockets)
                    default: <forge>/venv/Scripts/python.exe (Windows) or <forge>/venv/bin/python
  PB_FORGE_ROOT     Forge folder (for its style.css and venv); default: two levels above the extension
  PB_CHROME         Chrome / Edge / Chromium executable; default: the usual install locations
  PB_TAB_PORT       standalone management tab preview (default 7999)
  PB_HARNESS_PORT   accordion / popup JS harness (default 8765)
  PB_CDP_PORT       headless Chrome remote debugging (default 9333)
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXT_ROOT = Path(__file__).resolve().parents[2]
FORGE_ROOT = Path(os.environ.get("PB_FORGE_ROOT") or EXT_ROOT.parents[1]).resolve()

SCRATCH_ROOT = Path(tempfile.gettempdir()).resolve() / "promptblocks-devtools"
PREVIEW_DATA = SCRATCH_ROOT / "preview_data"
CHROME_PROFILE = SCRATCH_ROOT / "chrome_profile"
LOG_DIR = SCRATCH_ROOT / "logs"
SHOT_DIR = SCRATCH_ROOT / "screenshots"

TAB_PORT = int(os.environ.get("PB_TAB_PORT") or 7999)
HARNESS_PORT = int(os.environ.get("PB_HARNESS_PORT") or 8765)
CDP_PORT = int(os.environ.get("PB_CDP_PORT") or 9333)


class SetupError(RuntimeError):
    """Something the scenarios need is missing or busy. The message says what to do."""


def is_inside(path, folder):
    path, folder = Path(path).resolve(), Path(folder).resolve()
    return path == folder or folder in path.parents


if is_inside(SCRATCH_ROOT, EXT_ROOT):
    raise SetupError("scratch folder %s is inside the extension folder; refusing to run" % SCRATCH_ROOT)


def scratch_dir(path):
    """Create (if needed) and return a folder below SCRATCH_ROOT."""
    path = Path(path)
    assert is_inside(path, SCRATCH_ROOT) and not is_inside(path, EXT_ROOT), path
    path.mkdir(parents=True, exist_ok=True)
    return path


def wipe_scratch_dir(path):
    """Delete a folder below SCRATCH_ROOT (never anything else) and create it empty again."""
    path = Path(path)
    assert is_inside(path, SCRATCH_ROOT) and path != SCRATCH_ROOT and not is_inside(path, EXT_ROOT), path
    for _ in range(10):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            break
        time.sleep(0.3)  # Windows: files of a just-killed process can stay locked for a moment
    return scratch_dir(path)


def log_path(name):
    return scratch_dir(LOG_DIR) / name


def extension_js_files(ext_root=None):
    """The extension's `javascript/*.js` files in the order Forge loads them (one <script> each).

    Same rule as Forge (modules/extensions.py `Extension.list_files`: `sorted(os.listdir(dirpath))`, then
    keep files whose lower-cased extension is ".js"; modules/scripts.py `list_scripts` keeps that order
    because without a metadata.ini there are no Before / After dependencies to reorder by). A metadata.ini
    could reorder the files, which this helper does not model, so it refuses."""
    ext_root = Path(ext_root or EXT_ROOT)
    if (ext_root / "metadata.ini").exists():
        raise SetupError("%s has a metadata.ini (script Before / After ordering); extension_js_files() "
                         "does not model it" % ext_root)
    folder = ext_root / "javascript"
    if not folder.is_dir():
        return []
    return [folder / name for name in sorted(os.listdir(folder))
            if os.path.splitext(name)[1].lower() == ".js" and (folder / name).is_file()]


def _has_module(python, module):
    try:
        return subprocess.run([str(python), "-c", "import " + module], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def forge_python():
    """Forge's venv Python: PB_FORGE_PYTHON, else <forge>/venv, else the current one if it has gradio."""
    env = os.environ.get("PB_FORGE_PYTHON")
    if env:
        if not Path(env).is_file():
            raise SetupError("PB_FORGE_PYTHON=%s does not exist" % env)
        return str(Path(env))
    for rel in ("venv/Scripts/python.exe", "venv/bin/python"):
        cand = FORGE_ROOT / rel
        if cand.is_file():
            return str(cand)
    try:
        import gradio  # noqa: F401
        return sys.executable
    except ImportError:
        pass
    raise SetupError("Forge's Python not found (looked in %s/venv). Set PB_FORGE_PYTHON to the python "
                     "executable of Forge's venv (it must have gradio and websockets)." % FORGE_ROOT)


def chrome_exe():
    """A Chromium browser: PB_CHROME, else the usual Chrome / Edge / Chromium locations."""
    env = os.environ.get("PB_CHROME")
    if env:
        if not Path(env).is_file():
            raise SetupError("PB_CHROME=%s does not exist" % env)
        return env
    cands = []
    for var, default in (("PROGRAMFILES", r"C:\Program Files"), ("PROGRAMFILES(X86)", r"C:\Program Files (x86)")):
        root = os.environ.get(var) or default
        cands += [os.path.join(root, "Google", "Chrome", "Application", "chrome.exe"),
                  os.path.join(root, "Microsoft", "Edge", "Application", "msedge.exe")]
    cands += ["/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    for c in cands:
        if os.path.isfile(c):
            return c
    for name in ("chrome", "msedge", "google-chrome", "chromium"):
        found = shutil.which(name)
        if found:
            return found
    raise SetupError("No Chrome / Edge found. Set PB_CHROME to a Chromium-based browser executable.")


def port_busy(port, host="127.0.0.1"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def require_free_port(port, what, grace=3.0):
    """Fail with a clear message if something already listens on `port` (a just-stopped server of ours
    gets `grace` seconds to go away)."""
    end = time.time() + grace
    while port_busy(port):
        if time.time() > end:
            raise SetupError("port %d (%s) is already in use by another program; stop it or choose another "
                             "port with the environment variable shown in devtools/browser/README.md" % (port, what))
        time.sleep(0.2)


def _norm(s):
    return s.replace("\\", "/").lower()


def processes_with(marker):
    """PIDs of processes whose command line contains `marker` (a path; case / slash insensitive)."""
    marker = _norm(str(marker))
    me = os.getpid()
    try:
        import psutil
    except ImportError:
        psutil = None
    if psutil is not None:
        pids = []
        for p in psutil.process_iter(["pid", "cmdline"]):
            try:
                cmd = " ".join(p.info["cmdline"] or [])
            except Exception:
                continue
            if p.info["pid"] != me and marker in _norm(cmd):
                pids.append(p.info["pid"])
        return pids
    if os.name == "nt":
        ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and "
              "$_.CommandLine.Replace('\\','/').ToLower().Contains('%s') } | "
              "ForEach-Object { $_.ProcessId }" % marker.replace("'", "''"))
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                             timeout=60).stdout
        # The PowerShell process itself carries the marker in its own command line.
        return [int(x) for x in out.split() if x.isdigit() and int(x) != me]
    out = subprocess.run(["ps", "-eo", "pid=,args="], capture_output=True, text=True).stdout
    return [int(line.split(None, 1)[0]) for line in out.splitlines()
            if marker in _norm(line) and int(line.split(None, 1)[0]) != me]


def kill_tree(pid):
    """Kill a process and all its children (only this tree)."""
    try:
        import psutil
    except ImportError:
        psutil = None
    if psutil is not None:
        try:
            root = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return
        procs = root.children(recursive=True) + [root]
        for p in procs:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(procs, timeout=10)
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
    else:
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def kill_marked(marker):
    """Kill every process tree whose command line contains `marker` (our scratch Chrome profile path)."""
    for pid in processes_with(marker):
        kill_tree(pid)
    return processes_with(marker)
