"""Design notes section 23a: self-referencing category health finding, confirm keys, stale-form check,
form hint lines."""

import copy

import pytest

from pb_core import guard, health, suggest

BASE = {
    "saber": {"category": "PCharacter", "text": "1girl, saber"},
    "rin": {"category": "PCharacter", "text": "1girl, rin"},
    "beach": {"category": "Place", "text": "beach, %PCharacter"},
}


def of_kind(findings, kind):
    return [f for f in findings if f["kind"] == kind]


# ---- fix 5: health check, self_category_ref ----

def test_self_category_ref_kind_order_and_title():
    kinds = [k for k, _ in health.KINDS]
    assert kinds.index("self_category_ref") == kinds.index("all_inactive_ref") + 1
    assert dict(health.KINDS)["self_category_ref"]


def test_self_category_ref_in_text():
    blocks = copy.deepcopy(BASE)
    blocks["saber"]["text"] = "1girl, saber, %PCharacter, %PCharacter"
    found = of_kind(health.report(blocks), "self_category_ref")
    assert [(f["block"], f["sub"]) for f in found] == [("saber", None)]  # once per text
    detail = found[0]["detail"]
    assert detail.startswith("`%PCharacter` is this block's own category")
    assert "depth limit" in detail and "choose this block again" in detail
    assert "inactive" not in detail


def test_self_category_ref_in_sub_text():
    blocks = copy.deepcopy(BASE)
    blocks["rin"]["subs"] = [{"name": "friend", "text": "with %PCharacter", "mode": "random"}]
    found = of_kind(health.report(blocks), "self_category_ref")
    assert [(f["block"], f["sub"]) for f in found] == [("rin", "friend")]


def test_self_category_ref_absent_for_other_categories_and_clean_data():
    # beach calls %PCharacter, which is not its own category; no self finding anywhere.
    assert health.report(BASE) == []
    blocks = copy.deepcopy(BASE)
    blocks["saber"]["text"] = "%PCharacterX, %Place"  # a longer name is another category
    assert of_kind(health.report(blocks), "self_category_ref") == []
    # In the LoRA field a token is literal text, never a reference.
    blocks = copy.deepcopy(BASE)
    blocks["saber"]["lora"] = "<lora:%PCharacter:1>"
    assert health.report(blocks) == []


def test_self_category_ref_inactive_block_note():
    blocks = copy.deepcopy(BASE)
    blocks["saber"].update(text="%PCharacter", active=False)
    (f,) = of_kind(health.report(blocks), "self_category_ref")
    assert f["block"] == "saber" and "inactive" in f["detail"]


def test_self_category_ref_listed_in_report_after_all_inactive():
    blocks = copy.deepcopy(BASE)
    blocks["saber"]["text"] = "%PCharacter"
    blocks["beach"]["text"] = "%Off"
    blocks["off"] = {"category": "Off", "text": "x", "active": False}
    findings = health.report(blocks)
    order = [f["kind"] for f in findings]
    assert order.index("all_inactive_ref") < order.index("self_category_ref")
    text = health.format_report(findings, len(blocks))
    assert "**Blocks that call their own category** (1)" in text
    assert "- `saber`: `%PCharacter`" in text


def test_self_category_ref_ignores_broken_category():
    blocks = {"x": {"category": 5, "text": "%Misc"}, "y": {"category": "Misc", "text": "y"}}
    assert of_kind(health.report(blocks), "self_category_ref") == []


# ---- fix 1: confirm keys hold the data they confirm ----

def test_data_key_ignores_key_order_and_sees_changes():
    a = {"x": {"category": "C", "text": "t"}, "y": {"text": "u", "category": "C"}}
    b = {"y": {"category": "C", "text": "u"}, "x": {"text": "t", "category": "C"}}
    assert guard.data_key(a) == guard.data_key(b)
    c = copy.deepcopy(a)
    c["x"]["text"] = "t2"
    assert guard.data_key(c) != guard.data_key(a)
    assert guard.data_key({}) != guard.data_key(a)


@pytest.mark.parametrize("value", [None, [], {"a": {1, 2}}, {"a": float("nan")}, "text", {1: object()}])
def test_data_key_never_raises(value):
    key = guard.data_key(value)
    assert isinstance(key, str) and len(key) == 16


# ---- fix 6: stale form check ----

@pytest.mark.parametrize("seen, current, stale", [
    ("0", "0", False), (None, "0", False), ("7", "7", False), (" 7 ", "7", False), (7, "7", False),
    ("6", "7", True), (None, "3", True), ("3", None, True),
])
def test_is_stale(seen, current, stale):
    assert guard.is_stale(seen, current) is stale


# ---- fix 2: hint lines from the form's current values ----

def test_form_hints_follow_saved_data():
    blocks = copy.deepcopy(BASE)
    cat, slot, rows = suggest.form_hints("PCharacter", None, [None, "", None, None], blocks)
    assert cat == "Existing category (2 blocks)." and slot == "" and rows == ""
    blocks["sakura"] = {"category": "PCharacter", "text": "s", "slot": "girl"}
    cat, slot, rows = suggest.form_hints("PCharacter", "girl", ["girl", "newslot", None, None], blocks)
    assert cat == "Existing category (3 blocks)."
    assert slot == "Existing slot (1 use)."
    assert rows == "Sub-block 2: New slot `newslot`."


def test_form_hints_empty_and_odd_values():
    assert suggest.form_hints(None, None, None, BASE) == ("", "", "")
    assert suggest.form_hints("", " ", [], BASE) == ("", "", "")
    cat, _, _ = suggest.form_hints("pcharacter", None, [], BASE)
    assert "Did you mean: `PCharacter`?" in cat
