"""Block browser of the management tab (design notes section 11, round 2).

Pure Python, no gradio. ui.py only wires the result into a gr.Gallery.

- filter_names: block names for a search text + category filter (section 40: name and content search,
  quick filters like `:off`; name matches first).
- category_filter_choices: the category filter's (label, value) choices, labels with block counts.
- tile_color / tile_initials / placeholder_image: a deterministic placeholder tile for blocks
  without a thumbnail (Pillow is imported lazily, like storage.load_thumb).
- placeholder_file: writes a placeholder tile once into a cache folder and returns its path, so
  the gallery gets a file path (not a PIL image that would be re-encoded on every refresh).
- remove_placeholders: deletes a block's cached placeholder tiles (Delete / Rename).
- build_gallery: gallery items [(path, caption)], the rendered names (same order) and a note.
"""

import colorsys
import hashlib
import os
import re

from . import adetailer, bans, lora, subs, weights

MAX_TILES = 200
TILE_SIZE = 128
# Value of the category filter's "all categories" choice. "*" can never be a category name.
ALL_CATEGORIES = "*"
ALL_LABEL = "(all categories)"
INACTIVE_SUFFIX = " (off)"

_placeholders = {}  # (name, size) -> PIL image; generated once per process


# Quick filters (design notes section 40): search terms starting with ":" that select by a property
# instead of text. Aliases map to one key. A term like ":xyz" that is not listed here is plain text.
QUICK_FILTERS = {
    ":off": "off", ":inactive": "off",
    ":on": "on", ":active": "on",
    ":nothumb": "nothumb", ":thumb": "thumb",
    ":bans": "bans", ":subs": "subs", ":lora": "lora", ":ad": "ad",
}


def split_search(search):
    """(quick filter keys, text terms) of a search text: split on whitespace, lower case. Known
    QUICK_FILTERS terms become keys (aliases folded, duplicates dropped, order kept); everything else,
    an unknown ":xyz" included, is a text term. A non-string search gives ([], [])."""
    if not isinstance(search, str):
        return [], []
    keys, terms = [], []
    for t in search.lower().split():
        key = QUICK_FILTERS.get(t)
        if key is None:
            terms.append(t)
        elif key not in keys:
            keys.append(key)
    return keys, terms


def _passes(name, block, key, has_thumb):
    # One quick filter. Broken (non-dict) entries never pass a quick filter. Without `has_thumb`
    # (None) the thumbnail filters are IGNORED: they let every block through.
    if not isinstance(block, dict):
        return False
    if key == "off":
        return not weights.is_active(block)
    if key == "on":
        return weights.is_active(block)
    if key in ("thumb", "nothumb"):
        if has_thumb is None:
            return True
        return bool(has_thumb(name)) == (key == "thumb")
    if key == "bans":
        return bool(bans.block_bans(block))
    if key == "subs":
        return bool(subs.normalize_subs(block))
    if key == "lora":
        return lora.block_lora(block) is not None
    if key == "ad":
        return bool(adetailer.adetailer_texts(block))
    return True


def content_texts(block):
    """Lower-case texts the browser search looks into besides the name (section 40): the text, the
    LoRA field, the block slot, every usable sub-block's name / text / slot, the non-empty ADetailer
    texts and the ban tokens. Broken values are skipped; a non-dict entry gives []. Never raises."""
    if not isinstance(block, dict):
        return []
    found = []
    text = block.get("text")
    if isinstance(text, str):
        found.append(text)
    found += [lora.block_lora(block), subs.block_slot(block)]
    for s in subs.normalize_subs(block):
        found += [s["name"], s["text"], s["slot"]]
    found += [t for _, t in adetailer.adetailer_texts(block)]
    found += bans.block_bans(block)
    return [t.lower() for t in found if isinstance(t, str) and t]


def filter_names(blocks, search="", category=None, has_thumb=None):
    """Block names of the browser for a search text + category filter (design notes section 40).

    `category` None / "" / ALL_CATEGORIES = all. `search` is split on whitespace (case-insensitive,
    split_search): quick filter terms (QUICK_FILTERS) must all hold (AND); every text term must be
    found. Order, without duplicates, each group sorted:
    (1) every term is in the name and the name starts with the first term;
    (2) every term is in the name;
    (3) every term is in the name or in one of content_texts(block) (term by term, mixed).
    Without text terms the result is every remaining name, sorted.
    `has_thumb`: callable(name) -> bool for :thumb / :nothumb; None = those two filters are ignored.
    The autocomplete popup stays name-only; this is the management tab's browser only."""
    names = sorted(blocks)
    if category not in (None, "", ALL_CATEGORIES):
        names = [n for n in names if weights.in_category(blocks[n], category)]
    keys, terms = split_search(search)
    if keys:
        names = [n for n in names if all(_passes(n, blocks[n], k, has_thumb) for k in keys)]
    if not terms:
        return names
    starts, in_name, in_content = [], [], []
    for n in names:
        low = n.lower()
        if all(t in low for t in terms):
            (starts if low.startswith(terms[0]) else in_name).append(n)
            continue
        texts = content_texts(blocks[n])
        if all(t in low or any(t in x for x in texts) for t in terms):
            in_content.append(n)
    return starts + in_name + in_content


def category_label(label, total, active):
    """Label with block counts (section 40): "label (45)" when all are active, "label (42/45 active)"
    otherwise; the plain label when there are no blocks."""
    if not total:
        return label
    return f"{label} ({total})" if active == total else f"{label} ({active}/{total} active)"


def category_filter_choices(blocks):
    """Choices for the category filter dropdown: [(label, value), ...], "all" first, then the
    categories in sorted order. Values are ALL_CATEGORIES and the category names; the labels carry the
    block counts (category_label). Only dict entries are counted (broken hand-edited ones are no blocks)."""
    real = [b for b in blocks.values() if isinstance(b, dict)]
    cats = sorted({b.get("category") for b in real if b.get("category")})
    choices = [(category_label(ALL_LABEL, len(real), sum(1 for b in real if weights.is_active(b))),
                ALL_CATEGORIES)]
    for c in cats:
        members = [b for b in real if weights.in_category(b, c)]
        choices.append((category_label(c, len(members), sum(1 for b in members if weights.is_active(b))), c))
    return choices


def normalize_filter(value, blocks):
    """The filter value to keep after the block list changed: `value` if that category still exists,
    else ALL_CATEGORIES."""
    if value in (None, "", ALL_CATEGORIES):
        return ALL_CATEGORIES
    values = [v for _, v in category_filter_choices(blocks)]
    return value if value in values else ALL_CATEGORIES


def caption(name, block):
    """Gallery caption: the block name, with INACTIVE_SUFFIX for inactive blocks."""
    return name + (INACTIVE_SUFFIX if isinstance(block, dict) and not weights.is_active(block) else "")


def tile_color(name):
    """Deterministic RGB colour for a name (md5-based: Python's hash() changes between runs).
    Medium saturation / brightness so white text stays readable."""
    h = int(hashlib.md5(name.encode("utf-8")).hexdigest()[:8], 16)
    r, g, b = colorsys.hsv_to_rgb((h % 360) / 360.0, 0.45, 0.60)
    return int(round(r * 255)), int(round(g * 255)), int(round(b * 255))


def tile_initials(name):
    """One or two letters for a placeholder tile: the first character (upper case), then the first
    character after an "_" or the first later upper-case letter (upper case), else the second
    character (lower case). "saber" -> "Sa", "red_cape" -> "RC", "PCharacter" -> "PC", "a" -> "A"."""
    if not name:
        return "?"
    first = name[0].upper()
    for i in range(1, len(name)):
        if name[i] == "_" and i + 1 < len(name) and name[i + 1] != "_":
            return first + name[i + 1].upper()
        if name[i].isupper():
            return first + name[i]
    second = name[1] if len(name) > 1 else ""
    return first + (second.lower() if second != "_" else "")


def _font(px):
    from PIL import ImageFont

    for face in ("arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(face, px)
        except OSError:
            continue
    return None


def _draw_centered(img, text, font, fill):
    from PIL import ImageDraw

    draw = ImageDraw.Draw(img)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    x = (img.width - (right - left)) / 2 - left
    y = (img.height - (bottom - top)) / 2 - top
    draw.text((x, y), text, font=font, fill=fill)


def placeholder_image(name, size=TILE_SIZE):
    """size x size RGB placeholder tile: tile_color(name) background, tile_initials(name) centred in
    white. Cached in memory per (name, size); the cached image is returned (do not modify it)."""
    key = (name, size)
    if key in _placeholders:
        return _placeholders[key]
    from PIL import Image, ImageFont

    color = tile_color(name)
    text = tile_initials(name)
    font = _font(max(8, int(size * 0.42)))
    if font is not None:
        img = Image.new("RGB", (size, size), color)
        _draw_centered(img, text, font, (255, 255, 255))
    else:
        # Only the small built-in bitmap font: draw at 1/4 size and scale up (blocky but readable).
        small = Image.new("RGB", (max(1, size // 4), max(1, size // 4)), color)
        _draw_centered(small, text, ImageFont.load_default(), (255, 255, 255))
        img = small.resize((size, size), Image.NEAREST)
    _placeholders[key] = img
    return img


def placeholder_file(name, folder, size=TILE_SIZE):
    """Path of `name`'s placeholder tile in `folder` (PNG). Written only when missing (atomic:
    .tmp + os.replace). `name` must be a valid block name (it becomes the file name)."""
    path = os.path.join(folder, f"{name}_{size}.png")
    if not os.path.exists(path):
        os.makedirs(folder, exist_ok=True)
        tmp = path + ".tmp"
        placeholder_image(name, size).save(tmp, format="PNG")
        os.replace(tmp, path)
    return path


def remove_placeholders(name, folder):
    """Forget `name`'s placeholder tiles (design notes section 21; for Delete / Rename): every file in
    `folder` whose name is exactly `<name>_<digits>.png` (the placeholder_file pattern, any size) is
    removed, and the in-memory images of `name` are dropped. Only direct entries of `folder` are
    touched, so nothing outside it is deleted; "sa" never matches "saber_128.png". Missing folder or a
    file that cannot be removed is skipped (never raises). Returns the removed file names, sorted."""
    for key in [k for k in _placeholders if k[0] == name]:
        del _placeholders[key]
    if not isinstance(name, str) or not name:
        return []
    pattern = re.compile(re.escape(name) + r"_\d+\.png")
    try:
        entries = os.listdir(folder)
    except OSError:
        return []
    removed = []
    for entry in sorted(entries):
        path = os.path.join(folder, entry)
        if not pattern.fullmatch(entry) or not os.path.isfile(path):
            continue
        try:
            os.remove(path)
        except OSError:
            continue
        removed.append(entry)
    return removed


def note(shown, total):
    """Line under the gallery: "Showing N of M blocks." when capped, else ""."""
    return f"Showing {shown} of {total} blocks. Refine the search to see the rest." if shown < total else ""


def thumb_checker(thumb_path):
    """has_thumb callable for filter_names: True when `thumb_path(name)` names an existing file. Every
    caller of filter_names in the tab (gallery, Enable / Disable shown, Set sub-blocks of shown
    blocks) builds it from storage.thumb_path, so their counts agree."""
    def has_thumb(name):
        path = thumb_path(name)
        return bool(path) and os.path.exists(path)
    return has_thumb


def shown_names(blocks, search, category, thumb_path):
    """Every block the browser lists for this search + category filter, uncapped (the filter value is
    normalised first, as the gallery does): what Enable / Disable shown and Set sub-blocks of shown
    blocks compare the listed tiles against (bulk.capped_more)."""
    return filter_names(blocks, search, normalize_filter(category, blocks), thumb_checker(thumb_path))


def build_gallery(blocks, search, category, thumb_path, tile_dir, limit=MAX_TILES):
    """Gallery content for the block browser.

    `thumb_path(name)` -> thumbnail file path (used when the file exists); blocks without one get
    placeholder_file(name, tile_dir). Returns {"items": [(path, caption), ...],
    "names": [name, ...] (same order as items, for mapping a clicked index back to a name),
    "total": number of matching blocks, "note": note(len(items), total)}.
    The :thumb / :nothumb filters use thumb_checker(thumb_path), the same rule as the tiles."""
    has_thumb = thumb_checker(thumb_path)
    matching = filter_names(blocks, search, category, has_thumb)
    names = matching[:limit]
    items = []
    for n in names:
        path = thumb_path(n) if has_thumb(n) else placeholder_file(n, tile_dir)
        items.append((path, caption(n, blocks[n])))
    return {"items": items, "names": names, "total": len(matching), "note": note(len(names), len(matching))}


def name_at(names, index):
    """Block name for a clicked gallery index, using the list that was rendered; None if out of range
    or not an int."""
    if isinstance(index, bool) or not isinstance(index, int) or not isinstance(names, list):
        return None
    return names[index] if 0 <= index < len(names) else None
