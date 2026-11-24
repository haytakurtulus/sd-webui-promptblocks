"""Block browser helpers (design notes section 11, round 2): filtering / order, captions, placeholder
tiles, gallery items, mapping a clicked index back to a name."""

import os

import pytest

from pb_core import browser, storage

BLOCKS = {
    "saber": {"category": "PCharacter", "text": "saber"},
    "rin": {"category": "PCharacter", "text": "rin", "active": False},
    "beach": {"category": "Scene", "text": "beach"},
    "Sabertooth": {"category": "Animal", "text": "tiger"},
    "lightsaber": {"category": "Prop", "text": "laser sword"},
    "Anna": {"category": "PCharacter", "text": "anna"},
}


@pytest.fixture(autouse=True)
def _clear_cache():
    browser._placeholders.clear()
    yield
    browser._placeholders.clear()


# ---------- filter_names ----------

def test_filter_no_search_all_sorted():
    assert browser.filter_names(BLOCKS) == sorted(BLOCKS)
    assert browser.filter_names(BLOCKS, "", browser.ALL_CATEGORIES) == sorted(BLOCKS)
    assert browser.filter_names(BLOCKS, "  ", None) == sorted(BLOCKS)


def test_filter_prefix_first_then_substring_case_insensitive():
    # sorted: Anna, Sabertooth, beach, lightsaber, rin, saber
    assert browser.filter_names(BLOCKS, "SAB") == ["Sabertooth", "saber", "lightsaber"]


def test_filter_by_category():
    assert browser.filter_names(BLOCKS, "", "PCharacter") == ["Anna", "rin", "saber"]
    assert browser.filter_names(BLOCKS, "sab", "PCharacter") == ["saber"]
    assert browser.filter_names(BLOCKS, "", "Nope") == []


def test_filter_no_match():
    assert browser.filter_names(BLOCKS, "zzz") == []


def test_filter_ignores_non_string_search_and_broken_blocks():
    blocks = dict(BLOCKS, broken="not a dict")
    assert browser.filter_names(blocks, None) == sorted(blocks)
    assert "broken" not in browser.filter_names(blocks, "", "PCharacter")


def test_category_filter_choices_and_normalize():
    choices = browser.category_filter_choices(BLOCKS)
    assert choices[0] == ("(all categories) (5/6 active)", browser.ALL_CATEGORIES)
    assert [v for _, v in choices[1:]] == ["Animal", "PCharacter", "Prop", "Scene"]
    assert browser.normalize_filter("Scene", BLOCKS) == "Scene"
    assert browser.normalize_filter("Gone", BLOCKS) == browser.ALL_CATEGORIES
    assert browser.normalize_filter(None, BLOCKS) == browser.ALL_CATEGORIES
    assert browser.normalize_filter("", BLOCKS) == browser.ALL_CATEGORIES


def test_all_value_is_not_a_valid_category_name():
    from pb_core import parser
    assert not parser.is_valid_name(browser.ALL_CATEGORIES)


# ---------- captions, colour, initials ----------

def test_caption_marks_inactive_blocks():
    assert browser.caption("saber", BLOCKS["saber"]) == "saber"
    assert browser.caption("rin", BLOCKS["rin"]) == "rin" + browser.INACTIVE_SUFFIX


def test_tile_color_deterministic_and_differs():
    c = browser.tile_color("saber")
    assert c == browser.tile_color("saber")
    assert all(isinstance(v, int) and 0 <= v <= 255 for v in c) and len(c) == 3
    assert len({browser.tile_color(n) for n in ("saber", "rin", "beach", "Anna", "x")}) > 1


@pytest.mark.parametrize("name, expected", [
    ("saber", "Sa"), ("red_cape", "RC"), ("PCharacter", "PC"), ("a", "A"), ("runScene", "RS"),
    ("x_", "X"), ("a__b", "AB"), ("b2", "B2"), ("", "?"),
])
def test_tile_initials(name, expected):
    assert browser.tile_initials(name) == expected


# ---------- placeholder image / file ----------

def test_placeholder_image_size_colour_and_cache():
    img = browser.placeholder_image("saber")
    assert img.size == (browser.TILE_SIZE, browser.TILE_SIZE) and img.mode == "RGB"
    assert img.getpixel((1, 1)) == browser.tile_color("saber")
    # some white text pixels in the middle area
    assert (255, 255, 255) in {img.getpixel((x, y)) for x in range(20, 108) for y in range(20, 108)}
    assert browser.placeholder_image("saber") is img  # cached, not regenerated


def test_placeholder_file_written_once(tmp_path):
    folder = tmp_path / "tiles"
    path = browser.placeholder_file("saber", str(folder))
    assert os.path.exists(path) and path.endswith(".png")
    mtime = os.path.getmtime(path)
    os.utime(path, (mtime - 100, mtime - 100))
    assert browser.placeholder_file("saber", str(folder)) == path
    assert os.path.getmtime(path) == mtime - 100  # not rewritten
    assert not [f for f in os.listdir(folder) if f.endswith(".tmp")]


# ---------- build_gallery ----------

def _thumbs(tmp_path, names):
    from PIL import Image
    d = tmp_path / "thumbs"
    d.mkdir()
    for n in names:
        Image.new("RGB", (8, 8)).save(d / f"{n}.webp", format="WEBP")
    return lambda n: str(d / f"{n}.webp")


def test_build_gallery_thumbs_and_placeholders(tmp_path):
    thumb = _thumbs(tmp_path, ["saber"])
    tiles = str(tmp_path / "tiles")
    g = browser.build_gallery(BLOCKS, "", None, thumb, tiles)
    assert g["names"] == sorted(BLOCKS)
    assert [c for _, c in g["items"]] == [browser.caption(n, BLOCKS[n]) for n in g["names"]]
    paths = dict(zip(g["names"], (p for p, _ in g["items"])))
    assert paths["saber"] == thumb("saber")
    assert paths["rin"].startswith(tiles) and os.path.exists(paths["rin"])
    assert g["total"] == len(BLOCKS) and g["note"] == ""


def test_build_gallery_filtered_and_capped(tmp_path):
    thumb = _thumbs(tmp_path, [])
    tiles = str(tmp_path / "tiles")
    blocks = {f"b{i:03d}": {"category": "C", "text": "t"} for i in range(browser.MAX_TILES + 15)}
    g = browser.build_gallery(blocks, "", None, thumb, tiles)
    assert len(g["items"]) == browser.MAX_TILES == len(g["names"])
    assert g["total"] == browser.MAX_TILES + 15
    assert f"{browser.MAX_TILES} of {browser.MAX_TILES + 15}" in g["note"]
    g = browser.build_gallery(BLOCKS, "sab", "PCharacter", thumb, tiles)
    assert g["names"] == ["saber"] and g["total"] == 1 and g["note"] == ""


def test_build_gallery_uses_tile_cache_dir_of_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "THUMB_DIR", str(tmp_path / "data" / "thumbs"))
    assert storage.tile_cache_dir() == str(tmp_path / "data" / "tile_cache")
    g = browser.build_gallery({"a": {"category": "C", "text": "t"}}, "", None,
                              storage.thumb_path, storage.tile_cache_dir())
    assert g["items"][0][0].startswith(str(tmp_path / "data" / "tile_cache"))


# ---------- clicked index -> name ----------

def test_name_at_uses_rendered_list():
    names = ["saber", "Sabertooth", "lightsaber"]
    assert browser.name_at(names, 0) == "saber"
    assert browser.name_at(names, 2) == "lightsaber"
    assert browser.name_at(names, 3) is None
    assert browser.name_at(names, -1) is None
    assert browser.name_at(names, None) is None
    assert browser.name_at(names, True) is None
    assert browser.name_at(None, 0) is None
