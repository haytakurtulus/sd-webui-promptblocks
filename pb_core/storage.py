import datetime
import json
import os
import re

EXT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(EXT_ROOT, "data", "blocks.json")
THUMB_DIR = os.path.join(EXT_ROOT, "data", "thumbs")
# Tracked example blocks copied to DATA_FILE on the very first start (design notes section 41).
STARTER_FILE = os.path.join(EXT_ROOT, "examples", "starter_blocks.json")
THUMB_SIZE = 128
MAX_BACKUPS = 20

# Clock used for backup file names; tests replace it (monkeypatch storage._now).
_now = datetime.datetime.now

_BACKUP_RE = re.compile(r"^blocks-(\d{8})-(\d{6})(?:-(\d+))?\.json$")


def load_blocks():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Hand-edited data: a top level or "blocks" value that is not an object counts as "no blocks"
    # (one console line) instead of crashing every caller. Broken single entries are skipped by the
    # callers themselves. A missing "blocks" key is the old empty shape and stays silent.
    blocks = data.get("blocks", {}) if isinstance(data, dict) else None
    if not isinstance(blocks, dict):
        what = "top level" if not isinstance(data, dict) else "'blocks' value"
        print(f"[PromptBlocks] blocks.json ignored: its {what} is not a JSON object.")
        return {}
    return blocks


def _starter_label():
    # "examples/starter_blocks.json" for the real file, else the bare file name (ASCII-safe).
    try:
        rel = os.path.relpath(STARTER_FILE, EXT_ROOT)
    except ValueError:  # another drive on Windows
        rel = ".."
    if rel.startswith(".."):
        rel = os.path.basename(STARTER_FILE)
    return rel.replace(os.sep, "/").encode("ascii", "backslashreplace").decode("ascii")


def seed_starter_blocks():
    """First start (design notes section 41): when DATA_FILE does not exist, copy STARTER_FILE there
    byte for byte (atomic write, no backup) and print one console line. An existing DATA_FILE (even an
    empty or broken one) is never touched. A missing or invalid starter file prints one line and writes
    nothing. Returns True only when the file was written. Never raises."""
    try:
        if os.path.exists(DATA_FILE):
            return False
        label = _starter_label()
        try:
            with open(STARTER_FILE, "rb") as f:
                raw = f.read()
            data = json.loads(raw.decode("utf-8"))
        except Exception as e:
            print(f"[PromptBlocks] starter blocks not added: cannot read {label} ({type(e).__name__})")
            return False
        blocks = data.get("blocks") if isinstance(data, dict) else None
        if (not isinstance(blocks, dict) or not blocks
                or not all(isinstance(b, dict) and isinstance(b.get("text"), str) for b in blocks.values())):
            print(f"[PromptBlocks] starter blocks not added: {label} is not valid block data")
            return False
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        _atomic_write_bytes(DATA_FILE, raw)
        n = len(blocks)
        print(f"[PromptBlocks] first start: added {n} example block{'' if n == 1 else 's'} from {label}")
        return True
    except Exception as e:
        print(f"[PromptBlocks] starter blocks not added: {type(e).__name__}")
        return False


def _atomic_write_bytes(path, data):
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _keep_broken_copy():
    # load_blocks() treats a blocks.json whose top level / "blocks" value is not an object as empty, so
    # the next save would replace the user's (hand-edited, broken) file. Keep a copy that is never
    # pruned, next to it: blocks.broken-YYYYmmdd-HHMMSS.json. Never raises.
    try:
        if not os.path.exists(DATA_FILE):
            return None
        with open(DATA_FILE, "rb") as f:
            raw = f.read()
        try:
            data = json.loads(raw.decode("utf-8"))
            ok = isinstance(data, dict) and isinstance(data.get("blocks", {}), dict)
        except Exception:
            ok = False
        if ok:
            return None
        path = os.path.join(os.path.dirname(DATA_FILE), "blocks.broken-" + _now().strftime("%Y%m%d-%H%M%S") + ".json")
        _atomic_write_bytes(path, raw)
        print("[PromptBlocks] blocks.json was not valid block data; kept a copy as " + os.path.basename(path))
        return path
    except Exception:
        return None


def save_blocks(blocks):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    _keep_broken_copy()
    try:
        backup_current()
    except Exception as e:  # a failing backup must never block the save
        msg = f"[PromptBlocks] backup of blocks.json failed, saving anyway: {type(e).__name__}: {e}"
        print(msg.encode("ascii", "backslashreplace").decode("ascii"))
    payload = {"version": 1, "blocks": blocks}
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, DATA_FILE)


# ---- Backups (design notes section 12) ----

def backup_dir():
    # Derived from DATA_FILE at call time, so code that points DATA_FILE elsewhere (tests) moves it too.
    return os.path.join(os.path.dirname(DATA_FILE), "backups")


def _backup_key(file_name):
    # Sort key (date, time, same-second counter) or None for files that are not backups.
    m = _BACKUP_RE.match(file_name)
    if not m:
        return None
    return m.group(1), m.group(2), int(m.group(3) or 1)


def _backup_files():
    # Backup file names, newest first. Missing / unreadable folder -> [].
    try:
        names = os.listdir(backup_dir())
    except OSError:
        return []
    names = [n for n in names if _backup_key(n) is not None and os.path.isfile(os.path.join(backup_dir(), n))]
    return sorted(names, key=_backup_key, reverse=True)


def backup_current():
    """Copy the current blocks.json into backup_dir() as blocks-YYYYmmdd-HHMMSS[-N].json.

    Returns the new backup's path, or None when there is no current file or it is byte-identical to the
    newest backup. Keeps the newest MAX_BACKUPS backups. Errors are raised (save_blocks catches them)."""
    if not os.path.exists(DATA_FILE):
        return None
    with open(DATA_FILE, "rb") as f:
        data = f.read()
    folder = backup_dir()
    existing = _backup_files()
    if existing:
        with open(os.path.join(folder, existing[0]), "rb") as f:
            if f.read() == data:
                return None
    os.makedirs(folder, exist_ok=True)
    stamp = _now().strftime("%Y%m%d-%H%M%S")
    file_name, n = f"blocks-{stamp}.json", 1
    while os.path.exists(os.path.join(folder, file_name)):
        n += 1
        file_name = f"blocks-{stamp}-{n}.json"
    path = os.path.join(folder, file_name)
    _atomic_write_bytes(path, data)
    for old in _backup_files()[MAX_BACKUPS:]:
        os.remove(os.path.join(folder, old))
    return path


def _read_backup_blocks(file_name):
    # Parsed "blocks" dict of a backup file; raises on unreadable / malformed files.
    with open(os.path.join(backup_dir(), file_name), "r", encoding="utf-8") as f:
        blocks = json.load(f).get("blocks", {})
    if not isinstance(blocks, dict):
        raise ValueError("'blocks' is not an object")
    return blocks


def list_backups():
    """Backups, newest first: [{"file": name, "time": "YYYY-mm-dd HH:MM:SS", "count": int or None}].
    count is None for files that cannot be read or parsed. Never raises."""
    result = []
    for file_name in _backup_files():
        date, time, _ = _backup_key(file_name)
        try:
            count = len(_read_backup_blocks(file_name))
        except Exception:
            count = None
        result.append({"file": file_name,
                       "time": f"{date[:4]}-{date[4:6]}-{date[6:]} {time[:2]}:{time[2:4]}:{time[4:]}",
                       "count": count})
    return result


def backup_label(entry):
    # "2026-11-15 14:28:30 - 37 blocks" (dropdown label of one list_backups() entry).
    count = entry["count"]
    if count is None:
        return f"{entry['time']} - unreadable"
    return f"{entry['time']} - {count} block{'' if count == 1 else 's'}"


def backup_choices():
    # (label, file name) pairs for a dropdown, newest first.
    return [(backup_label(e), e["file"]) for e in list_backups()]


def restore_backup(file_name):
    """Replace blocks.json with the backup `file_name` (a name from list_backups(), not a path).

    The current file is backed up first (a failure here aborts the restore); then the backup's bytes
    replace blocks.json atomically. Returns the restored blocks dict. Raises ValueError for unknown names
    and unreadable backups."""
    if file_name not in _backup_files():
        raise ValueError(f"Unknown backup: {file_name!r}")
    try:
        blocks = _read_backup_blocks(file_name)
        with open(os.path.join(backup_dir(), file_name), "rb") as f:
            data = f.read()
    except Exception as e:
        raise ValueError(f"Backup {file_name} cannot be read: {e}") from e
    try:
        backup_current()
    except Exception as e:
        raise ValueError(f"Could not back up the current blocks.json, nothing restored: {e}") from e
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    _atomic_write_bytes(DATA_FILE, data)
    return blocks


def thumb_path(name):
    return os.path.join(THUMB_DIR, name + ".webp")


def tile_cache_dir():
    # Generated placeholder tiles of the block browser (pb_core.browser). Derived from THUMB_DIR at
    # call time, so code that points THUMB_DIR elsewhere (tests) moves this folder too.
    return os.path.join(os.path.dirname(THUMB_DIR), "tile_cache")


def thumb_mtime(name):
    path = thumb_path(name)
    return int(os.path.getmtime(path)) if os.path.exists(path) else None


def save_thumb(name, image):
    os.makedirs(THUMB_DIR, exist_ok=True)
    img = image.convert("RGB")
    img.thumbnail((THUMB_SIZE, THUMB_SIZE))
    tmp = thumb_path(name) + ".tmp"
    img.save(tmp, format="WEBP", quality=85)
    os.replace(tmp, thumb_path(name))


def load_thumb(name):
    from PIL import Image

    path = thumb_path(name)
    if not os.path.exists(path):
        return None
    with Image.open(path) as im:
        return im.copy()


def rename_thumb(old, new):
    src = thumb_path(old)
    if os.path.exists(src):
        os.replace(src, thumb_path(new))


def delete_thumb(name):
    path = thumb_path(name)
    if os.path.exists(path):
        os.remove(path)