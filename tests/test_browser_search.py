"""Design notes section 40: block browser improvements - full-content search, quick filters, block counts
in the category filter labels, the inactive-tile suffix shared with the tab JS, MAX_TILES 200."""

import ast
import os
import re

import pytest

from pb_core import browser, bulk, storage

EXT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BLOCKS = {
    "saber": {
        "category": "PCharacter", "text": "1girl, blonde hair", "lora": "<lora:goldknight:0.8>",
        "subs": [
            {"name": "armor", "text": "silver armor", "mode": "include", "slot": "outfit"},
            {"name": "1bad", "text": "hiddenword", "mode": "include"},  # invalid name: not usable
        ],
        "adetailer": ["", "green eyes", 7],
        "bans": ["~happy", "nope"],  # "nope" is no valid ban token
    },
    "rin": {"category": "PCharacter", "text": "twintails, red sweater", "active": False},
    "sabertooth": {"category": "Animal", "text": "tiger"},
    "lightsaber": {"category": "Prop", "text": "laser sword", "slot": "weapon"},
    "happy": {"category": "PEmotion", "text": "smile, a :xyz tag"},
    "beach": {"category": "Scene", "text": "sand, saber statue"},
}
ALL = sorted(BLOCKS)


def f(search, category=None, has_thumb=None, blocks=BLOCKS):
    return browser.filter_names(blocks, search, category, has_thumb)


# ---------- groups and ordering ----------

def test_groups_name_prefix_then_name_then_content():
    # (1) name starts with the term: saber, sabertooth (sorted); (2) name contains it: lightsaber;
    # (3) only the content has it: beach ("saber statue").
    assert f("saber") == ["saber", "sabertooth", "lightsaber", "beach"]
    assert f("SABER") == f("saber")


def test_no_duplicates_and_each_group_sorted():
    blocks = {"bx": {"category": "C", "text": "a"}, "ab": {"category": "C", "text": "b b"},
              "ba": {"category": "C", "text": "b"}, "zz": {"category": "C", "text": "b"},
              "aa": {"category": "C", "text": "b"}}
    got = f("b", blocks=blocks)
    assert got == ["ba", "bx", "ab", "aa", "zz"]
    assert len(got) == len(set(got))


def test_empty_search_gives_all_sorted():
    assert f("") == ALL
    assert f("   ") == ALL
    assert f(None) == ALL


# ---------- multi-term AND ----------

def test_multi_term_and():
    assert f("saber blonde") == ["saber"]           # name + text
    assert f("light sword") == ["lightsaber"]       # name + text, group 3
    assert f("tooth saber") == ["sabertooth"]       # all in the name, not starting with "tooth": group 2
    assert f("saber tooth") == ["sabertooth"]       # group 1
    assert f("blonde tiger") == []                  # never one block


def test_multi_term_group_order():
    # "saber" + "s": group 1 = names starting with "saber" containing "s"; group 2 = lightsaber; group 3 =
    # beach ("sand, saber statue").
    assert f("saber s") == ["saber", "sabertooth", "lightsaber", "beach"]
    # Whitespace of any kind splits terms.
    assert f(" saber\tblonde \n") == ["saber"]


# ---------- every content field ----------

@pytest.mark.parametrize("term,expected", [
    ("blonde", ["saber"]),            # text
    ("goldknight", ["saber"]),        # LoRA field
    ("weapon", ["lightsaber"]),       # block slot
    ("armor", ["saber"]),             # sub-block name (and text)
    ("silver", ["saber"]),            # sub-block text
    ("outfit", ["saber"]),            # sub-block slot
    ("green", ["saber"]),             # ADetailer text
    ("~happy", ["saber"]),            # ban token
])
def test_every_content_field(term, expected):
    assert f(term) == expected


def test_content_ignores_unusable_entries_and_category():
    assert f("hiddenword") == []      # sub-block with an invalid name is not usable
    assert f("nope") == []            # invalid ban token
    assert f("7") == []               # non-string ADetailer entry
    assert f("pemotion") == []        # the category is the filter's job, not searched
    assert f("happy") == ["happy", "saber"]   # name first, then the ban token ~happy


def test_content_texts_shape():
    assert browser.content_texts("broken") == []
    texts = browser.content_texts(BLOCKS["saber"])
    assert "1girl, blonde hair" in texts and "<lora:goldknight:0.8>" in texts
    assert {"armor", "silver armor", "outfit", "green eyes", "~happy"} <= set(texts)


# ---------- quick filters ----------

THUMBS = {"saber", "beach"}


def has_thumb(name):
    return name in THUMBS


@pytest.mark.parametrize("term,expected", [
    (":off", ["rin"]),
    (":inactive", ["rin"]),
    (":on", [n for n in ALL if n != "rin"]),
    (":active", [n for n in ALL if n != "rin"]),
    (":thumb", ["beach", "saber"]),
    (":nothumb", [n for n in ALL if n not in THUMBS]),
    (":bans", ["saber"]),
    (":subs", ["saber"]),
    (":lora", ["saber"]),
    (":ad", ["saber"]),
])
def test_every_quick_filter(term, expected):
    assert f(term, has_thumb=has_thumb) == expected
    assert f(term.upper(), has_thumb=has_thumb) == expected


def test_quick_filters_and_with_each_other_text_and_category():
    assert f(":on :off") == []
    assert f(":lora :subs :bans") == ["saber"]
    assert f(":on saber") == ["saber", "sabertooth", "lightsaber", "beach"]
    assert f(":off saber") == []
    assert f(":off twintails") == ["rin"]
    assert f(":nothumb saber", has_thumb=has_thumb) == ["sabertooth", "lightsaber"]
    assert f(":on", "PCharacter") == ["saber"]
    assert f(":off :off") == ["rin"]           # repeated filter
    assert f(":off :inactive") == ["rin"]      # alias of the same filter


def test_quick_filter_bans_subs_ad_on_broken_fields():
    blocks = {"a": {"category": "C", "text": "t", "bans": ["nope"], "subs": "x", "adetailer": ["", " "],
                    "lora": "  "},
              "b": {"category": "C", "text": "t"}}
    for term in (":bans", ":subs", ":ad", ":lora"):
        assert f(term, blocks=blocks) == []


def test_unknown_colon_term_is_plain_text():
    assert f(":xyz") == ["happy"]      # found in "smile, a :xyz tag"
    assert f(":nothing") == []         # unknown, no block has it: empty, no error
    assert f(":") == ["happy", "saber"]   # plain text ":" (":xyz", "<lora:...>")
    assert browser.split_search(":xyz :OFF word") == (["off"], [":xyz", "word"])


def test_has_thumb_none_ignores_thumb_filters():
    # Documented choice (section 40): without has_thumb, :thumb / :nothumb let every block through.
    assert f(":thumb") == ALL
    assert f(":nothumb") == ALL
    assert f(":thumb :nothumb") == ALL
    assert f(":thumb twintails") == ["rin"]
    # With has_thumb they are real filters, and both together give nothing.
    assert f(":thumb :nothumb", has_thumb=has_thumb) == []


def test_broken_entries_never_pass_a_quick_filter():
    blocks = dict(BLOCKS, junk="not a block", nums=[1, 2])
    for term in (":on", ":off", ":thumb", ":nothumb"):
        assert "junk" not in f(term, blocks=blocks, has_thumb=lambda n: True)
    assert f("junk", blocks=blocks) == ["junk"]  # a name match still lists it (as before)


def test_shown_names_normalises_filter_and_uses_thumb_path(tmp_path):
    d = tmp_path / "thumbs"
    d.mkdir()
    (d / "saber.webp").write_bytes(b"x")
    thumb = lambda n: str(d / f"{n}.webp")  # noqa: E731
    assert browser.shown_names(BLOCKS, ":thumb", "Gone", thumb) == ["saber"]
    assert browser.shown_names(BLOCKS, ":nothumb", "PCharacter", thumb) == ["rin"]


def test_gallery_and_shown_names_agree_on_thumb_filters(tmp_path):
    pytest.importorskip("PIL.Image")
    d = tmp_path / "thumbs"
    d.mkdir()
    (d / "beach.webp").write_bytes(b"x")
    thumb = lambda n: str(d / f"{n}.webp")  # noqa: E731
    tiles = str(tmp_path / "tiles")
    for q in (":thumb", ":nothumb", ":nothumb saber"):
        g = browser.build_gallery(BLOCKS, q, browser.ALL_CATEGORIES, thumb, tiles)
        assert g["names"] == browser.shown_names(BLOCKS, q, browser.ALL_CATEGORIES, thumb)
    g = browser.build_gallery(BLOCKS, ":thumb", None, thumb, tiles)
    assert g["items"] == [(thumb("beach"), "beach")]


# ---------- category filter labels ----------

def labels(blocks):
    return browser.category_filter_choices(blocks)


def test_category_labels_with_counts_values_unchanged():
    choices = labels(BLOCKS)
    assert choices == [
        ("(all categories) (5/6 active)", browser.ALL_CATEGORIES),
        ("Animal (1)", "Animal"),
        ("PCharacter (1/2 active)", "PCharacter"),
        ("PEmotion (1)", "PEmotion"),
        ("Prop (1)", "Prop"),
        ("Scene (1)", "Scene"),
    ]


def test_category_label_rules():
    assert browser.category_label("PCharacter", 45, 45) == "PCharacter (45)"
    assert browser.category_label("PCharacter", 45, 42) == "PCharacter (42/45 active)"
    assert browser.category_label("X", 5, 0) == "X (0/5 active)"
    assert browser.category_label(browser.ALL_LABEL, 0, 0) == browser.ALL_LABEL
    assert labels({}) == [(browser.ALL_LABEL, browser.ALL_CATEGORIES)]
    assert labels({"a": {"category": "C", "text": "t"}})[0] == ("(all categories) (1)", "*")
    # Broken entries are not counted; a block without category counts only under "all".
    assert labels({"a": {"category": "C", "text": "t"}, "j": "junk", "n": {"text": "t"}}) == [
        ("(all categories) (2)", "*"), ("C (1)", "C")]


def test_normalize_filter_unaffected_by_labels():
    assert browser.normalize_filter("PCharacter", BLOCKS) == "PCharacter"
    assert browser.normalize_filter("Gone", BLOCKS) == browser.ALL_CATEGORIES


def test_labels_follow_every_kind_of_data_change():
    # The choices are computed from the data each time (common.browser_values); every data change the tab
    # makes gives new labels with the same values.
    blocks = dict(BLOCKS)
    before = labels(blocks)
    after_disable, _ = bulk.set_active(blocks, ["saber", "sabertooth"], False)
    assert dict((v, l) for l, v in labels(after_disable))["PCharacter"] == "PCharacter (0/2 active)"
    assert labels(after_disable)[0][0] == "(all categories) (3/6 active)"
    enabled, _ = bulk.set_active(after_disable, ["rin", "saber", "sabertooth"], True)
    assert labels(enabled)[0][0] == "(all categories) (6)"
    renamed, _, _ = bulk.rename_category(blocks, "Animal", "Prop")
    assert dict((v, l) for l, v in labels(renamed))["Prop"] == "Prop (2)"
    assert "Animal" not in [v for _, v in labels(renamed)]
    saved = dict(blocks, newone={"category": "Scene", "text": "x", "active": False})  # Save of a new block
    assert dict((v, l) for l, v in labels(saved))["Scene"] == "Scene (1/2 active)"
    deleted = {n: b for n, b in blocks.items() if n != "rin"}                       # Delete
    assert dict((v, l) for l, v in labels(deleted))["PCharacter"] == "PCharacter (1)"
    assert [v for _, v in before] == [v for _, v in labels(enabled)]


def test_every_data_changing_listener_refreshes_the_category_filter():
    # Structural check of wiring.py / groups.py / refresh.py (they import gradio, so they are read as text):
    # the follow-up chain always runs sidebar.on_browser with BROWSER_OUTPUTS (which include cat_filter),
    # every data-changing handler is wired through it, and a block switch's auto-save uses data_refresh,
    # which also returns the cat_filter update of common.browser_values.
    ui = os.path.join(EXT, "pb_core", "ui")
    src = open(os.path.join(ui, "wiring.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    chain = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_after_data_change")
    top = [ast.unparse(s) for s in chain.body]
    assert any("sidebar.on_browser" in s and "BROWSER_OUTPUTS" in s and not s.startswith("if ") for s in top)
    groups = ast.parse(open(os.path.join(ui, "groups.py"), encoding="utf-8").read())
    lists = {t.id: n.value for n in groups.body if isinstance(n, ast.Assign) for t in n.targets
             if isinstance(t, ast.Name)}
    assert "cat_filter" in ast.literal_eval(lists["BROWSER_OUTPUTS"])
    assert "cat_filter" in ast.literal_eval(lists["REFRESH_OUTPUTS"])
    wired = " ".join(ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.Call)
                     and ast.unparse(n.func) == "_after_data_change")
    deps = src  # Enable / Disable shown pass their click via `dep`
    for handler in ("form.on_save", "tools.on_delete", "tools.on_rename", "refresh.on_refresh",
                    "tools.on_restore", "tools.on_lora_all", "tools.on_cat_rename", "tools.on_sub_modes"):
        assert handler in wired, handler
    assert re.search(r"dep = btn\.click\(sidebar\.make_bulk_active\(value\)[\s\S]*?_after_data_change\(c, dep",
                     deps)
    refresh_src = open(os.path.join(ui, "refresh.py"), encoding="utf-8").read()
    assert "browser_values(blocks, search_text, cat)" in refresh_src
    common_src = open(os.path.join(ui, "common.py"), encoding="utf-8").read()
    assert "choices = browser.category_filter_choices(blocks)" in common_src


# ---------- tiles: suffix shared with the tab JS, MAX_TILES ----------

def test_js_inactive_suffix_matches_server():
    js = open(os.path.join(EXT, "javascript", "promptblocks_30_tab.js"), encoding="utf-8").read()
    m = re.search(r'const INACTIVE_SUFFIX = "([^"]*)";', js)
    assert m and m.group(1) == browser.INACTIVE_SUFFIX
    assert "pb-tile-off" in js
    css = open(os.path.join(EXT, "style.css"), encoding="utf-8").read()
    assert ".thumbnail-item.pb-tile-off img" in css


def test_caption_off_only_for_inactive():
    assert browser.caption("rin", BLOCKS["rin"]).endswith(browser.INACTIVE_SUFFIX)
    for n in ALL:
        if n != "rin":
            assert not browser.caption(n, BLOCKS[n]).endswith(browser.INACTIVE_SUFFIX)


def test_max_tiles_200_and_capped_note(tmp_path):
    pytest.importorskip("PIL.Image")
    assert browser.MAX_TILES == 200
    blocks = {f"b{i:03d}": {"category": "C", "text": "t"} for i in range(205)}
    tiles = str(tmp_path / "tiles")
    thumb = lambda n: str(tmp_path / "none" / f"{n}.webp")  # noqa: E731
    g = browser.build_gallery(blocks, "", None, thumb, tiles)
    assert len(g["items"]) == len(g["names"]) == 200
    assert g["total"] == 205
    assert g["note"] == "Showing 200 of 205 blocks. Refine the search to see the rest."
    assert bulk.capped_more(len(g["names"]), g["total"], browser.MAX_TILES) == 5
    g = browser.build_gallery(dict(list(blocks.items())[:200]), "", None, thumb, tiles)
    assert g["note"] == "" and g["total"] == 200
    assert bulk.capped_more(200, 200, browser.MAX_TILES) == 0


def test_tests_do_not_touch_real_data(monkeypatch, tmp_path):
    # Sanity: storage paths in this module are only used through tmp_path-based callables.
    monkeypatch.setattr(storage, "THUMB_DIR", str(tmp_path / "thumbs"))
    assert browser.shown_names(BLOCKS, ":thumb", None, storage.thumb_path) == []
