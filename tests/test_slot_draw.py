"""Slot draw ~name*slot (design notes section 10)."""
import random

import pytest

from pb_core import parser, storage, subs, suggest

SEEDS = range(400)
LORA = "<lora:saber_v2:0.8>"
OUTFITS = {"ARMOR", "DRESS", "BIKINI", "GOWN"}


def sub(name, text, mode="include", slot=None):
    return {"name": name, "text": text, "mode": mode, "slot": slot}


def make_blocks(saber_active=True, lora=None):
    saber = {"category": "PCharacter", "text": "saber", "subs": [
        sub("armor", "ARMOR", "include", "outfit"),
        sub("dress", "DRESS", "exclude", "outfit"),
        sub("bikini", "BIKINI", "random", "outfit"),
        sub("gown", "GOWN", "include", "outfit"),
    ]}
    if not saber_active:
        saber["active"] = False
    if lora is not None:
        saber["lora"] = lora
    return {
        "saber": saber,
        "rin": {"category": "PCharacter", "text": "rin", "subs": [
            sub("uniform", "UNIFORM %Color", "include", "outfit"),
            sub("hair", "TWINTAILS", "include"),
        ]},
        "red": {"category": "Color", "text": "red"},
        "blue": {"category": "Color", "text": "blue"},
        "scene": {"category": "Scene", "text": "beach, ~saber*outfit"},
    }


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_FILE", str(tmp_path / "blocks.json"))
    monkeypatch.setattr(storage, "THUMB_DIR", str(tmp_path / "thumbs"))


def run(prompt, blocks, seed=0, **kw):
    return parser.expand(prompt, blocks, random.Random(seed), **kw)


# ---- token shape ----

def test_separator_constant():
    assert parser.SLOT_DRAW_SEPARATOR == "*"
    assert parser.SLOT_DRAW_SEPARATOR != parser.SUB_SEPARATOR


def test_parts_and_slot_part():
    m = parser._TOKEN.search("~saber*outfit")
    assert m.group(0) == "~saber*outfit"
    assert parser._parts(m) == ("~", "saber", None)
    assert parser._slot_part(m) == "outfit"
    m = parser._TOKEN.search("~saber.armor")
    assert parser._parts(m) == ("~", "saber", "armor")
    assert parser._slot_part(m) is None
    m = parser._TOKEN.search("%Cat*outfit")
    assert m.group(0) == "%Cat"
    assert parser._parts(m) == ("%", "Cat", None)
    assert parser._slot_part(m) is None


def test_sub_then_slot_is_sub_token_plus_literal():
    # Chosen: the first valid token wins; the rest is literal text.
    assert [m.group(0) for m in parser._TOKEN.finditer("~saber.armor*outfit")] == ["~saber.armor"]
    assert run("~saber.armor*outfit", make_blocks()) == "ARMOR*outfit"


def test_slot_then_sub_is_slot_token_plus_literal():
    assert [m.group(0) for m in parser._TOKEN.finditer("~saber*outfit.armor")] == ["~saber*outfit"]
    out = run("~saber*outfit.armor", make_blocks())
    assert out.endswith(".armor")
    assert out[:-len(".armor")] in OUTFITS


def test_category_slot_not_supported():
    blocks = make_blocks()
    assert run("%Color*outfit", blocks, seed=1) in {"red*outfit", "blue*outfit"}


# ---- expansion ----

def test_draw_exactly_one_any_mode_parent_not_inserted():
    blocks = make_blocks()
    seen = set()
    for seed in SEEDS:
        out = run("~saber*outfit", blocks, seed)
        assert out in OUTFITS, out
        assert "saber" not in out
        seen.add(out)
    assert seen == OUTFITS  # Exclude (DRESS) and Random (BIKINI) included


def test_draw_equal_chance_uses_rng_choice():
    blocks = make_blocks()
    names = ["armor", "dress", "bikini", "gown"]
    for seed in range(50):
        expected = random.Random(seed).choice(names)
        assert run("~saber*outfit", blocks, seed) == subs.get_sub(blocks["saber"], expected)["text"]


def test_single_candidate_consumes_no_rng():
    blocks = {"rin": {"category": "P", "text": "rin", "subs": [sub("uniform", "UNIFORM", "exclude", "outfit"),
                                                               sub("hair", "TWINTAILS")]}}
    rng = random.Random(7)
    before = rng.getstate()
    assert parser.expand("~rin*outfit", blocks, rng) == "UNIFORM"
    assert rng.getstate() == before


def test_drawn_sub_text_is_expanded():
    blocks = make_blocks()
    assert run("~rin*outfit", blocks, 3) in {"UNIFORM red", "UNIFORM blue"}


@pytest.mark.parametrize("prompt", ["~saber*nosuch", "~nope*outfit", "~rin*hair"])
def test_unknown_left_untouched_and_reported(prompt):
    blocks = make_blocks()
    rng = random.Random(0)
    before = rng.getstate()
    out = parser.expand("x, " + prompt + ", y", blocks, rng)
    assert out == "x, " + prompt + ", y"
    assert rng.getstate() == before
    assert parser.find_unknown(out) == [prompt]
    assert parser.preview_warnings(out, blocks) == ([prompt], [])


def test_star_without_letter_is_literal():
    blocks = make_blocks()
    for tail in ["*", "*, x", "*1", "* outfit", "*_a"]:
        out = run("~saber" + tail, blocks, 5)
        assert out.endswith(tail)
        assert out[:-len(tail)] == run("~saber", blocks, 5)
        assert out[:-len(tail)].startswith("saber")


def test_works_when_parent_inactive():
    blocks = make_blocks(saber_active=False)
    seen = {run("~saber*outfit", blocks, s) for s in SEEDS}
    assert seen == OUTFITS


def test_trace_records_drawn_sub():
    blocks = make_blocks()
    for seed in range(30):
        trace = []
        out = run("~saber*outfit", blocks, seed, trace=trace)
        assert len(trace) == 1
        parent, name = trace[0]
        assert parent == "saber"
        assert subs.get_sub(blocks["saber"], name)["text"] == out


def test_nested_slot_draw_in_block_text():
    blocks = make_blocks()
    for seed in range(30):
        out = run("~scene", blocks, seed)
        assert out.startswith("beach, ")
        assert out[len("beach, "):] in OUTFITS


# ---- slots (section 4 interaction) ----

def test_draw_occupies_slot_and_skips_own_automatic_subs():
    blocks = make_blocks()
    assert parser.occupied_slots("~saber*outfit, ~saber", blocks) == {"outfit"}
    assert parser.occupied_slots("~saber*outfit", blocks) == {"outfit"}
    for seed in SEEDS:
        out = run("~saber*outfit, ~saber", blocks, seed)
        first, second = out.split(", ")
        assert first in OUTFITS
        assert second == "saber"  # automatic outfit subs skipped


def test_draw_occupier_distinct_from_block_and_sub_calls():
    blocks = make_blocks()
    occ = parser.slot_occupiers("~saber*outfit, ~saber.armor", blocks)
    assert occ == {"outfit": {("saber", "*outfit"), ("saber", "armor")}}
    assert ("saber", None) not in occ["outfit"]


def test_draw_occupies_slot_for_other_blocks():
    blocks = make_blocks()
    for seed in range(50):
        out = run("~saber*outfit, ~rin", blocks, seed)
        assert out.endswith(", rin, TWINTAILS")


def test_unresolved_draw_occupies_nothing():
    blocks = make_blocks()
    assert parser.occupied_slots("~saber*nosuch, ~nope*outfit, ~rin*hair", blocks) == set()


def test_draw_inside_block_text_does_not_occupy():
    blocks = make_blocks()
    assert parser.occupied_slots("~scene", blocks) == set()
    outs = {run("~scene, ~rin", blocks, s) for s in range(50)}
    assert all("UNIFORM" in o for o in outs)


def test_explicit_draw_not_suppressed_by_occupied_slot():
    blocks = make_blocks()
    for seed in range(50):
        out = run("~rin.uniform, ~saber*outfit", blocks, seed)
        assert out.split(", ")[-1] in OUTFITS


# ---- LoRA (section 9 interaction) ----

def test_lora_appended_once_alone():
    blocks = make_blocks(lora=LORA)
    for seed in range(30):
        out = run("~saber*outfit", blocks, seed)
        assert out.count(LORA) == 1
        assert out.endswith(", " + LORA)
        assert out[:-len(", " + LORA)] in OUTFITS


def test_lora_appended_once_with_block_call():
    blocks = make_blocks(lora=LORA)
    for seed in range(30):
        out = run("~saber*outfit, ~saber", blocks, seed)
        assert out.count(LORA) == 1


def test_lora_not_added_for_unresolved_draw():
    blocks = make_blocks(lora=LORA)
    assert run("~saber*nosuch", blocks) == "~saber*nosuch"


# ---- references / rename / users ----

def test_references_and_users():
    blocks = make_blocks()
    assert parser.references("a, ~saber*outfit", "~", "saber")
    assert not parser.references("a, ~sabers*outfit", "~", "saber")
    assert not parser.sub_references("~saber*outfit", "saber", "outfit")
    assert suggest.users_of(blocks, "~", "saber") == ["scene"]
    assert suggest.sub_users(blocks, "saber", "armor") == []
    assert "scene" in suggest.delete_warnings(blocks, "saber")[0]


def test_rename_block_rewrites_draw_token():
    text = "~saber*outfit, ~saber.armor, ~saber, ~sabers*outfit, ~saber*"
    assert parser.rename_token(text, "~", "saber", "arturia") == (
        "~arturia*outfit, ~arturia.armor, ~arturia, ~sabers*outfit, ~arturia*")


def test_rename_block_refs_in_blocks():
    blocks = make_blocks()
    new, changed = subs.rename_block_refs(blocks, "saber", "arturia")
    assert changed == ["scene"]
    assert new["scene"]["text"] == "beach, ~arturia*outfit"


def test_rename_sub_does_not_touch_draw_token():
    text = "~saber*outfit, ~saber.outfit"
    assert parser.rename_sub_tokens(text, "saber", {"outfit": "x"}) == "~saber*outfit, ~saber.x"


def test_category_rename_ignores_draw_token():
    assert parser.rename_token("~saber*outfit, %saber", "%", "saber", "x") == "~saber*outfit, %x"


def test_slot_draw_candidates_helper():
    blocks = make_blocks()
    assert parser.slot_draw_candidates(blocks["saber"], "outfit") == ["armor", "dress", "bikini", "gown"]
    assert parser.slot_draw_candidates(blocks["rin"], "nosuch") == []
    assert parser.slot_draw_candidates({"text": "x"}, "outfit") == []
