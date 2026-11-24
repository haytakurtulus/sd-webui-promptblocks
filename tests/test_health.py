"""Health check (design notes section 18)."""

import random

import pytest

from pb_core import health, parser, storage

CLEAN = {
    "saber": {"category": "PCharacter", "text": "1girl, saber, %Place", "lora": "<lora:saber:0.8>",
              "weight": 2,
              "subs": [{"name": "armor", "text": "ARMOR", "mode": "include", "slot": "outfit"},
                       {"name": "dress", "text": "DRESS", "mode": "Random", "slot": "outfit", "chance": 70},
                       {"name": "hat", "text": "~rin.smile", "mode": "exclude"}]},
    "rin": {"category": "PCharacter", "text": "rin", "active": False, "slot": "girl",
            "subs": [{"name": "smile", "text": "smile"}]},
    "beach": {"category": "Place", "text": "beach, ~saber*outfit, ~saber.dress"},
    "city": {"category": "Place", "text": "city", "weight": 0.5},
}


def kinds(findings):
    return [f["kind"] for f in findings]


def of_kind(findings, kind):
    return [f for f in findings if f["kind"] == kind]


def with_block(name, **fields):
    blocks = {k: dict(v) for k, v in CLEAN.items()}
    blocks[name] = {**blocks.get(name, {"category": "Misc", "text": "x"}), **fields}
    return blocks


def test_clean_data_has_no_findings():
    assert health.report(CLEAN, ["saber", "rin"]) == []
    assert health.report({}) == []
    assert health.report({}, []) == []


def test_finding_shape():
    blocks = with_block("bad", text="~nope")
    (f,) = health.report(blocks)
    assert set(f) == {"kind", "block", "sub", "detail"}
    assert f["kind"] == "unknown_ref" and f["block"] == "bad" and f["sub"] is None
    assert "~nope" in f["detail"]


@pytest.mark.parametrize("text, needle", [
    ("~nope", "no block named"),
    ("~saber.nope", "has no sub-block `nope`"),
    ("~saber*nope", "no sub-block in slot `nope`"),
    ("%NoSuchCat", "no block has category"),
])
def test_unknown_ref_kinds(text, needle):
    findings = health.report(with_block("bad", text=text))
    assert kinds(findings) == ["unknown_ref"]
    assert needle in findings[0]["detail"]


def test_unknown_ref_in_sub_text_names_the_sub():
    blocks = with_block("bad", subs=[{"name": "s1", "text": "~ghost, ~ghost"}])
    (f,) = health.report(blocks)
    assert (f["kind"], f["block"], f["sub"]) == ("unknown_ref", "bad", "s1")


def test_unknown_ref_found_behind_random_pick_and_random_sub():
    # Static scan: a reference that expansion would only reach with some picks is still found.
    blocks = with_block("bad", text="%Place", subs=[{"name": "r", "text": "~ghost", "mode": "random",
                                                     "chance": 1}])
    blocks["city"] = {"category": "Place", "text": "~ghost2"}
    found = {(f["block"], f["sub"]) for f in of_kind(health.report(blocks), "unknown_ref")}
    assert found == {("bad", "r"), ("city", None)}


def test_token_in_lora_field_is_not_a_reference():
    blocks = with_block("bad", lora="<lora:x~ghost%Nope:1>")
    assert health.report(blocks) == []


def test_all_inactive_ref():
    blocks = with_block("bad", text="%Off")
    blocks["off1"] = {"category": "Off", "text": "a", "active": False}
    blocks["off2"] = {"category": "Off", "text": "b", "active": False}
    findings = health.report(blocks)
    assert kinds(findings) == ["all_inactive_ref"]
    assert findings[0]["block"] == "bad" and "%Off" in findings[0]["detail"]
    # Inactive blocks are still fine for ~name.
    blocks["bad"]["text"] = "~off1"
    assert health.report(blocks) == []


def test_cycle_direct_and_via_sub():
    blocks = with_block("a", text="~b")
    blocks["b"] = {"category": "Misc", "text": "~a"}
    findings = of_kind(health.report(blocks), "cycle")
    assert [f["block"] for f in findings] == ["a", "b"]
    assert "~a" in findings[0]["detail"]

    # Only reachable through an Exclude sub-block (never added automatically).
    blocks = with_block("c", subs=[{"name": "loop", "text": "~c.loop", "mode": "exclude"}])
    (f,) = of_kind(health.report(blocks), "cycle")
    assert f["block"] == "c" and "~c.loop" in f["detail"]
    assert kinds(health.report(blocks)) == ["cycle"]


def test_cycle_reported_once_per_block():
    blocks = with_block("c", text="~c", subs=[{"name": "s", "text": "~c.s", "mode": "exclude"}])
    assert len(of_kind(health.report(blocks), "cycle")) == 1


def test_random_only_cycle_is_found():
    # %Loop picks one of two blocks; give the cycle to the one Random(0) does NOT pick first, so the
    # single-seed save-time check of ~start misses it.
    first = random.Random(0).choice(["x", "y"])
    looping = "y" if first == "x" else "x"
    blocks = {
        "start": {"category": "Misc", "text": "%Loop"},
        first: {"category": "Loop", "text": "end"},
        looping: {"category": "Loop", "text": "~start"},
    }
    parser.expand("~start", blocks, random.Random(0))  # seed 0 alone does not raise
    cycles = {f["block"]: f["detail"] for f in of_kind(health.report(blocks), "cycle")}
    assert "start" in cycles
    assert "random picks" in cycles["start"]


def test_lora_in_text():
    blocks = with_block("bad", text="1girl, <lora:a:0.8>, <LYCO:b:1>")
    findings = health.report(blocks)
    assert kinds(findings) == ["lora_in_text"]
    assert "<lora:a:0.8>" in findings[0]["detail"] and "<LYCO:b:1>" in findings[0]["detail"]
    assert "Move LoRA tags" in findings[0]["detail"]
    # LoRA tags in a sub text or in the LoRA field are not this finding.
    assert health.report(with_block("ok", subs=[{"name": "s", "text": "<lora:a:1>"}])) == []


@pytest.mark.parametrize("fields", [
    {"weight": 0}, {"weight": "2"}, {"weight": True}, {"weight": 101}, {"weight": None},
    {"active": "no"}, {"active": 0}, {"active": None},
    {"slot": "1bad"}, {"slot": 3},
    {"lora": 5},
    {"subs": "outfit"},
])
def test_ignored_block_value(fields):
    findings = health.report(with_block("bad", **fields))
    assert kinds(findings) == ["ignored_value"]
    assert findings[0]["block"] == "bad" and findings[0]["sub"] is None
    key = next(iter(fields))
    assert findings[0]["detail"].startswith(key)


def test_unset_values_are_not_ignored_values():
    blocks = with_block("ok", slot="", lora="", subs=None, active=True, weight=2.0)
    blocks["ok"]["subs"] = [{"name": "s", "text": "t", "mode": None, "slot": None, "chance": None},
                            {"name": "t", "text": "t", "slot": "", "chance": 50.0}]
    assert health.report(blocks) == []


def test_ignored_sub_entries():
    subs = [
        "not a dict",
        {"name": "1bad", "text": "x"},
        {"name": "a", "text": "A"},
        {"name": "a", "text": "again"},
        {"name": "b", "text": None},
        {"name": "c"},
        {"name": "d", "text": "D", "mode": "sometimes"},
        {"name": "e", "text": "E", "slot": "9x"},
        {"name": "f", "text": "F", "mode": "random", "chance": 150},
        {"name": "h", "text": "H"},
        {"name": "i", "text": "I"},
        {"name": "g", "text": "G"},
        [1, 2],
    ]
    findings = health.report(with_block("bad", subs=subs))
    assert set(kinds(findings)) == {"ignored_value"}
    got = [(f["sub"], f["detail"]) for f in findings]
    assert len(got) == 10
    assert got[0][0] is None and "#1" in got[0][1] and "not an object" in got[0][1]
    assert got[1][0] is None and "#2" in got[1][1] and "not a valid name" in got[1][1]
    assert got[2][0] == "a" and "duplicate" in got[2][1]
    assert got[3][0] == "b" and "text is `null`" in got[3][1]
    assert got[4][0] == "c" and "text is missing" in got[4][1]
    assert got[5][0] == "d" and got[5][1].startswith("mode") and "include is used" in got[5][1]
    assert got[6][0] == "e" and got[6][1].startswith("slot")
    assert got[7][0] == "f" and got[7][1].startswith("chance") and "50 is used" in got[7][1]
    # a, d, e, f, h, i are the six usable ones (MAX_SUBS, section 36 C); g and the list are beyond the 6th.
    assert got[8][0] == "g" and "first 6" in got[8][1]
    assert got[9][0] is None and "first 6" in got[9][1]


def test_orphan_thumb():
    findings = health.report(CLEAN, ["saber", "ghost", "rin"])
    assert kinds(findings) == ["orphan_thumb"]
    assert findings[0]["block"] is None and "ghost.webp" in findings[0]["detail"]
    assert health.report(CLEAN, None) == []


@pytest.mark.parametrize("block, needles", [
    ("just a string", ["not an object"]),
    (None, ["not an object"]),
    ([1, 2], ["not an object"]),
    ({"category": "Misc"}, ["`text` is missing"]),
    ({"category": "Misc", "text": None}, ["`text` is `null`"]),
    ({"category": "Misc", "text": ["a"]}, ["`text` is"]),
    ({"text": "x"}, ["`category` is missing"]),
    ({"text": "x", "category": "1bad"}, ["not a valid name"]),
    ({"text": 1, "category": None}, ["`text` is", "`category` is"]),
])
def test_bad_block(block, needles):
    blocks = dict(CLEAN, bad=block)
    findings = health.report(blocks)
    assert set(kinds(findings)) == {"bad_block"}
    assert [f["block"] for f in findings] == ["bad"] * len(needles)
    for f, needle in zip(findings, needles):
        assert needle in f["detail"]


@pytest.mark.parametrize("blocks", [
    None, [], "x", 5, [{"text": "a"}],
    {"a": None, "b": [], "c": "~a", "d": {"text": None, "category": [], "subs": [None, {"name": []}]}},
    {"a": {"text": "~b %C", "category": "C", "subs": {"name": "x"}, "weight": [], "active": {},
           "slot": [], "lora": {}}, "b": 3},
    {"a": {"text": "~b", "category": "C"}, "b": {"text": "~a", "category": {"x": 1}},
     "c": {"text": "%C", "category": "C", "subs": [{"name": "s", "text": "~c.s", "mode": [],
                                                    "slot": {}, "chance": "x"}]}},
    {"a": {"text": "x", "category": "C", "subs": [{"name": "s", "text": "t"}] * 9}},
])
def test_report_survives_garbage(blocks):
    findings = health.report(blocks, ["a", None, 3, "zz"])
    assert isinstance(findings, list)
    for f in findings:
        assert set(f) == {"kind", "block", "sub", "detail"}
    text = health.format_report(findings, 3)
    assert isinstance(text, str)
    health.summary_line(findings)


def test_report_survives_garbage_thumb_names():
    assert health.report(CLEAN, 5) == []
    assert kinds(health.report(CLEAN, [["x"], "ghost"])) == ["orphan_thumb"]


def test_sorted_by_kind_then_block():
    blocks = dict(CLEAN)
    blocks["zz"] = {"category": "Misc", "text": "~ghost <lora:a:1>", "weight": -1}
    blocks["aa"] = {"category": "Misc", "text": "~ghost"}
    blocks["mm"] = None
    findings = health.report(blocks, ["orphan"])
    assert [(f["kind"], f["block"]) for f in findings] == [
        ("unknown_ref", "aa"), ("unknown_ref", "zz"), ("lora_in_text", "zz"),
        ("ignored_value", "zz"), ("orphan_thumb", None), ("bad_block", "mm")]


def test_format_report_empty():
    assert health.format_report([], 12) == "No problems found in 12 blocks."
    assert health.format_report([], 1) == "No problems found in 1 block."
    assert health.summary_line([]) == "Health check: no problems"


def test_format_report_groups():
    blocks = dict(CLEAN)
    blocks["aa"] = {"category": "Misc", "text": "~ghost, %Nope",
                    "subs": [{"name": "s", "text": "~ghost"}]}
    blocks["bb"] = {"category": "Misc", "text": "<lora:a:1>"}
    findings = health.report(blocks, ["orphan"])
    text = health.format_report(findings, len(blocks))
    lines = text.split("\n")
    assert lines[0] == "**Health check: 5 problems in 2 blocks** (checked 6 blocks)"
    assert "**Unknown references** (3)" in lines
    assert "**LoRA tags inside Text** (1)" in lines
    assert "**Thumbnails without a block** (1)" in lines
    assert "Cycles" not in text
    i = lines.index("**Unknown references** (3)")
    assert lines[i + 1].startswith("- `aa`: `~ghost`")
    assert lines[i + 2].startswith("- `aa`: `%Nope`")
    assert lines[i + 3].startswith("- `aa.s`: `~ghost`")
    assert lines.index("**LoRA tags inside Text** (1)") < lines.index("**Thumbnails without a block** (1)")
    assert any(ln.startswith("- `orphan.webp`") for ln in lines)
    assert health.summary_line(findings) == "Health check: 5 problems in 2 blocks"
    assert health.summary_line(findings[-1:]) == "Health check: 1 problem"


def test_report_does_not_modify_input():
    import copy
    blocks = with_block("bad", text="~nope <lora:a:1>", weight=0,
                        subs=[{"name": "s", "text": "x"}, {"name": "s", "text": "y"}])
    before = copy.deepcopy(blocks)
    health.report(blocks, ["x"])
    assert blocks == before


def test_thumb_names(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "THUMB_DIR", str(tmp_path / "thumbs"))
    assert health.thumb_names() == []
    (tmp_path / "thumbs").mkdir()
    for f in ("saber.webp", "rin.webp", "x.webp.tmp", "notes.txt"):
        (tmp_path / "thumbs" / f).write_bytes(b"")
    (tmp_path / "thumbs" / "dir.webp").mkdir()
    assert health.thumb_names() == ["rin", "saber"]
    assert health.thumb_names(str(tmp_path / "missing")) == []


def test_many_blocks_is_fast():
    import time
    # 500 blocks, nesting 3 levels, random picks everywhere, no problems.
    blocks = {f"leaf{i}": {"category": f"L{i % 10}", "text": f"leaf {i}"} for i in range(50)}
    for i in range(50):
        blocks[f"mid{i}"] = {"category": f"M{i % 10}", "text": f"mid, %L{i % 10}, ~leaf{i}",
                             "subs": [{"name": "r", "text": "%L3", "mode": "random"}]}
    for i in range(400):
        blocks[f"b{i}"] = {"category": f"C{i % 20}", "text": f"t{i}, %M{i % 10}, ~mid{i % 50}",
                           "subs": [{"name": "r", "text": "%L3", "mode": "random"},
                                    {"name": "s", "text": "x", "slot": "o"},
                                    {"name": "t", "text": "~leaf1.nope", "slot": "o"}]}
    start = time.perf_counter()
    findings = health.report(blocks)
    assert time.perf_counter() - start < 20
    assert kinds(findings) == ["unknown_ref"] * 400
