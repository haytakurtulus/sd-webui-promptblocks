"""Block LoRA field (design notes section 9)."""
import copy
import random

import pytest

from pb_core import parser, subrows
from pb_core.lora import block_lora, set_block_lora

LORA = "<lora:saber_v2:0.8>"


def make_blocks(lora=LORA):
    saber = {"category": "PCharacter", "text": "1girl, saber (fate)",
             "subs": [{"name": "armor", "text": "silver armor", "mode": "include"},
                      {"name": "dress", "text": "blue dress", "mode": "exclude"}]}
    if lora is not ...:
        saber["lora"] = lora
    return {
        "saber": saber,
        "scene": {"category": "PPose", "text": "running, ~saber"},
        "rin": {"category": "Other", "text": "rin tohsaka"},
    }


def run(prompt, blocks, seed=0, **kw):
    return parser.expand(prompt, blocks, random.Random(seed), **kw)


# ---- helpers ----

@pytest.mark.parametrize("value", [None, "", "   ", 5, 0.8, [], {}, True])
def test_block_lora_none(value):
    assert block_lora({"text": "x", "lora": value}) is None


def test_block_lora_missing_and_non_dict():
    assert block_lora({"text": "x"}) is None
    assert block_lora(None) is None
    assert block_lora("x") is None


def test_block_lora_strips():
    assert block_lora({"lora": "  <lora:a:1>\n"}) == "<lora:a:1>"


def test_set_block_lora():
    b = {"text": "x"}
    s = set_block_lora(b, "  <lora:a:1> ")
    assert s == {"text": "x", "lora": "<lora:a:1>"}
    assert b == {"text": "x"}  # input not modified
    for empty in (None, "", "  ", 3):
        assert set_block_lora(s, empty) == {"text": "x"}
    assert set_block_lora({"text": "x"}, "") == {"text": "x"}


# ---- acceptance ----

def test_block_call_text_subs_lora_once():
    out = run("~saber", make_blocks())
    assert out == "1girl, saber (fate), silver armor, " + LORA
    assert out.count(LORA) == 1


def test_direct_sub_call_gets_parent_lora():
    assert run("~saber.armor", make_blocks()) == "silver armor, " + LORA
    # Exclude-mode sub called directly also gets it.
    assert run("~saber.dress", make_blocks()) == "blue dress, " + LORA


def test_sub_then_block_lora_once():
    out = run("~saber.armor, ~saber", make_blocks())
    assert out == "silver armor, " + LORA + ", 1girl, saber (fate), silver armor"
    assert out.count(LORA) == 1


def test_block_twice_lora_once():
    out = run("~saber, ~saber", make_blocks())
    assert out.count(LORA) == 1
    assert out == "1girl, saber (fate), silver armor, " + LORA + ", 1girl, saber (fate), silver armor"


def test_category_pick_includes_lora():
    assert run("%PCharacter", make_blocks()) == "1girl, saber (fate), silver armor, " + LORA


def test_nested_block_includes_lora():
    assert run("~scene", make_blocks()) == "running, 1girl, saber (fate), silver armor, " + LORA


def test_nested_and_direct_lora_once():
    out = run("~scene, ~saber.armor", make_blocks())
    assert out.count(LORA) == 1
    assert out == "running, 1girl, saber (fate), silver armor, " + LORA + ", silver armor"


def test_two_blocks_with_lora_both_appear():
    blocks = make_blocks()
    blocks["rin"]["lora"] = "<lora:rin:0.6>"
    out = run("~saber, ~rin, ~rin", blocks)
    assert out == ("1girl, saber (fate), silver armor, " + LORA + ", rin tohsaka, <lora:rin:0.6>, "
                   "rin tohsaka")


def test_once_per_call_not_per_process():
    blocks = make_blocks()
    rng = random.Random(0)
    a = parser.expand("~saber", blocks, rng)
    b = parser.expand("~saber", blocks, rng)
    assert a.count(LORA) == 1 and b.count(LORA) == 1


def test_lora_is_stripped_and_empty_text_has_no_leading_joiner():
    blocks = {"x": {"category": "C", "text": "", "lora": "  <lora:x:1>  "},
              "y": {"category": "C", "text": "  ", "lora": "<lora:y:1>"}}
    assert run("~x", blocks) == "<lora:x:1>"
    assert run("~y", blocks) == "<lora:y:1>"
    assert run("a, ~x, b", blocks) == "a, <lora:x:1>, b"


def test_empty_sub_text_direct_call_no_leading_joiner():
    blocks = {"x": {"category": "C", "text": "t", "lora": "L", "subs": [{"name": "s", "text": ""}]}}
    assert run("~x.s", blocks) == "L"


def test_inactive_block_direct_call_still_gets_lora():
    blocks = make_blocks()
    blocks["saber"]["active"] = False
    assert run("~saber.armor", blocks) == "silver armor, " + LORA
    assert run("%PCharacter", blocks) == "%PCharacter"  # no pick -> no lora


def test_unknown_sub_no_lora():
    assert run("~saber.nosuch", make_blocks()) == "~saber.nosuch"


@pytest.mark.parametrize("lora", [..., None, "", "   ", 5, [], {"a": 1}])
def test_no_lora_identical_and_rng_parity(lora):
    blocks = make_blocks(lora)
    blocks["saber"]["subs"].append({"name": "hat", "text": "hat", "mode": "random"})
    blocks["saber2"] = {"category": "PCharacter", "text": "%PCharacter b"}
    plain = copy.deepcopy(blocks)
    plain["saber"].pop("lora", None)
    prompt = "%PCharacter, ~saber, ~saber.armor, ~scene, %PCharacter"
    for seed in range(30):
        r1, r2 = random.Random(seed), random.Random(seed)
        try:
            a = parser.expand(prompt, blocks, r1)
        except parser.BlockCycleError:
            a = "cycle"
        try:
            b = parser.expand(prompt, plain, r2)
        except parser.BlockCycleError:
            b = "cycle"
        assert a == b
        assert r1.random() == r2.random()


def test_lora_rng_parity_with_lora_set():
    # Same picks with and without a lora: the lora consumes no RNG.
    with_l, without = make_blocks(), make_blocks(...)
    with_l["saber"]["subs"].append({"name": "hat", "text": "hat", "mode": "random"})
    without["saber"]["subs"].append({"name": "hat", "text": "hat", "mode": "random"})
    for seed in range(30):
        r1, r2 = random.Random(seed), random.Random(seed)
        a = parser.expand("~saber, %PCharacter, ~scene", with_l, r1)
        b = parser.expand("~saber, %PCharacter, ~scene", without, r2)
        assert a.replace(", " + LORA, "") == b
        assert r1.random() == r2.random()


def test_token_like_lora_inserted_literally():
    blocks = make_blocks("<lora:x:1>, ~rin, %Other, ~saber.armor")
    out = run("~saber.dress", blocks)
    assert out == "blue dress, <lora:x:1>, ~rin, %Other, ~saber.armor"
    assert "rin tohsaka" not in out


def test_token_like_lora_not_reported_unknown_in_preview():
    blocks = make_blocks("<lora:x:1> ~nosuch %NoCat")
    out = run("~saber.dress, ~missing", blocks)
    unknown, inactive = parser.preview_warnings(out, blocks)
    assert unknown == ["~missing"]
    assert inactive == []
    # find_unknown itself works on raw text and still sees them (no blocks given).
    assert "~nosuch" in parser.find_unknown(out)


def test_preview_lora_matching_all_inactive_category_not_reported():
    blocks = make_blocks("%Other")
    blocks["rin"]["active"] = False
    out = run("~saber.dress, %Other", blocks)
    assert out == "blue dress, %Other, %Other"
    # Plain string replace: the identical typed "%Other" is blanked too, so it is not reported as
    # all-inactive (accepted limitation of the cheap approach).
    unknown, inactive = parser.preview_warnings(out, blocks)
    assert unknown == []
    assert inactive == []


def test_references_and_rename_ignore_lora():
    blocks = make_blocks("<lora:x:1> ~rin")
    assert not parser.references(blocks["saber"]["text"], "~", "rin")
    from pb_core import subs
    new_blocks, changed = subs.rename_block_refs(blocks, "rin", "rin2")
    assert new_blocks["saber"]["lora"] == "<lora:x:1> ~rin"
    assert changed == []


# ---- API ----

def test_api_block_lora():
    assert subrows.api_block_lora({"text": "x", "lora": " <lora:a:1> "}) == {"lora": "<lora:a:1>"}
    for v in (None, "", "  ", 5):
        assert subrows.api_block_lora({"text": "x", "lora": v}) == {"lora": None}
    assert subrows.api_block_lora({"text": "x"}) == {"lora": None}
