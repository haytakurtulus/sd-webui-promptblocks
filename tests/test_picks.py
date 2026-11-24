"""Picks in infotext + "Pin last picks" (design notes section 15)."""
import random

import pytest

from pb_core import parser, picks, state, storage

SEEDS = range(300)


def sub(name, text, mode="include", slot=None, chance=None):
    s = {"name": name, "text": text, "mode": mode, "slot": slot}
    if chance is not None:
        s["chance"] = chance
    return s


def make_blocks():
    return {
        "saber": {"category": "PCharacter", "text": "saber", "lora": "<lora:saber:0.8>", "subs": [
            sub("armor", "ARMOR", "random", "outfit"),
            sub("dress", "DRESS", "random", "outfit"),
            sub("sword", "SWORD", "include"),
            sub("cape", "CAPE", "random", chance=30),
        ]},
        "rin": {"category": "PCharacter", "text": "rin, %Color", "subs": [
            sub("uniform", "UNIFORM", "include", "outfit"),
            sub("skirt", "SKIRT", "include", "outfit"),
        ]},
        "luvia": {"category": "PCharacter", "text": "luvia", "weight": 3},
        "red": {"category": "Color", "text": "red"},
        "blue": {"category": "Color", "text": "blue"},
        "green": {"category": "Color", "text": "green", "active": False},
        "scene": {"category": "Scene", "text": "beach, %Color, ~saber*outfit"},
    }


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_FILE", str(tmp_path / "blocks.json"))
    monkeypatch.setattr(storage, "THUMB_DIR", str(tmp_path / "thumbs"))
    monkeypatch.setattr(state, "last_picks", {"txt2img": [], "img2img": []})


def record(prompt, blocks, seed=0):
    pk, tr = [], []
    text = parser.expand(prompt, blocks, random.Random(seed), trace=tr, picks=pk)
    return text, pk, tr


def cat(c, b):
    return {"kind": "category", "category": c, "block": b}


def slot(n, s, x):
    return {"kind": "slot", "name": n, "slot": s, "sub": x}


# ---- recorder ----

def test_recorder_lists_depth0_picks_in_text_order():
    blocks = make_blocks()
    for seed in SEEDS:
        _, pk, _ = record("%Color, ~saber*outfit, %PCharacter", blocks, seed)
        assert [p["kind"] for p in pk] == ["category", "slot", "category"]
        assert pk[0]["category"] == "Color" and pk[0]["block"] in {"red", "blue"}
        assert pk[1]["name"] == "saber" and pk[1]["slot"] == "outfit" and pk[1]["sub"] in {"armor", "dress"}
        assert pk[2]["category"] == "PCharacter" and pk[2]["block"] in {"saber", "rin", "luvia"}


def test_recorder_matches_output():
    blocks = make_blocks()
    for seed in SEEDS:
        text, pk, _ = record("%Color, ~saber*outfit", blocks, seed)
        color, outfit = text.split(", ")[:2]
        assert color == pk[0]["block"]
        assert outfit == pk[1]["sub"].upper()


def test_recorder_ignores_nested_tokens():
    blocks = make_blocks()
    for seed in SEEDS:
        # ~scene contains %Color and ~saber*outfit; ~rin contains %Color.
        _, pk, _ = record("~scene, ~rin", blocks, seed)
        assert pk == []
        _, pk, _ = record("%Scene", blocks, seed)
        assert pk == [cat("Scene", "scene")]


def test_recorder_ignores_plain_sub_unknown_and_untouched_tokens():
    blocks = make_blocks()
    _, pk, _ = record("~saber, ~saber.sword, ~nobody, %Nope, ~saber*nope, ~nobody*outfit", blocks)
    assert pk == []


def test_recorder_single_candidate_is_recorded():
    blocks = make_blocks()
    blocks["solo"] = {"category": "Solo", "text": "solo"}
    _, pk, _ = record("%Solo", blocks)
    assert pk == [cat("Solo", "solo")]


def test_recorder_no_effect_on_output_or_rng():
    blocks = make_blocks()
    prompts = ["%Color, ~saber*outfit, %PCharacter, ~scene", "%PCharacter, %PCharacter, ~rin*outfit",
               "plain text", "%Scene, ~saber"]
    for prompt in prompts:
        for seed in SEEDS:
            r1, r2 = random.Random(seed), random.Random(seed)
            plain = parser.expand(prompt, blocks, r1, trace=[])
            recorded = parser.expand(prompt, blocks, r2, trace=[], picks=[])
            assert plain == recorded
            assert r1.random() == r2.random()
            for lora in (True, False):
                assert (parser.expand(prompt, blocks, random.Random(seed), lora=lora)
                        == parser.expand(prompt, blocks, random.Random(seed), lora=lora, picks=[]))


def test_expand_recorded_is_index_aligned():
    blocks = make_blocks()
    prompts = ["%Color", "~saber*outfit", "plain"]
    seeds = [5, 6, 7]
    expanded, pks, trs = picks.expand_recorded(prompts, seeds, blocks)
    assert expanded == [parser.expand(p, blocks, random.Random(s)) for p, s in zip(prompts, seeds)]
    assert [len(p) for p in pks] == [1, 1, 0]
    assert len(trs) == 3 and trs[2] == []


# ---- summary ----

def test_summary_format():
    s = picks.summary([cat("PCharacter", "saber"), slot("saber", "outfit", "dress")],
                      [("saber", "dress"), ("saber", "sword"), ("saber", "sword")])
    assert s == "PCharacter=saber, saber*outfit=dress; subs: saber.sword"


def test_summary_empty_and_parts_omitted():
    assert picks.summary([], []) == ""
    assert picks.summary(None, None) == ""
    assert picks.summary([cat("Color", "red")], []) == "Color=red"
    assert picks.summary([], [("saber", "sword"), ("rin", "uniform")]) == "subs: saber.sword, rin.uniform"


def test_summary_from_real_expansion():
    blocks = make_blocks()
    for seed in SEEDS:
        _, pk, tr = record("%Color, ~saber", blocks, seed)
        s = picks.summary(pk, tr)
        assert s.startswith("Color=" + pk[0]["block"] + "; subs: ")
        assert "saber.sword" in s


# ---- pin ----

BLOCKS = make_blocks()


def test_pin_replaces_by_kind_in_order():
    pk = [cat("Color", "red"), slot("saber", "outfit", "dress"), cat("PCharacter", "rin")]
    new, n = picks.pin_prompt("%PCharacter, ~saber*outfit, %Color", pk, BLOCKS)
    assert new == "~rin, ~saber.dress, ~red"
    assert n == 3


def test_pin_same_category_twice_in_order():
    pk = [cat("Color", "blue"), cat("Color", "red")]
    new, n = picks.pin_prompt("%Color and %Color", pk, BLOCKS)
    assert new == "~blue and ~red"
    assert n == 2


def test_pin_slot_gives_sub_call():
    new, n = picks.pin_prompt("~saber*outfit", [slot("saber", "outfit", "armor")], BLOCKS)
    assert (new, n) == ("~saber.armor", 1)
    # A pick for another (name, slot) is not used.
    new, n = picks.pin_prompt("~rin*outfit", [slot("saber", "outfit", "armor")], BLOCKS)
    assert (new, n) == ("~rin*outfit", 0)


def test_pin_extra_token_appended_after_generation_left_alone():
    pk = [cat("Color", "red")]
    new, n = picks.pin_prompt("%Color, %Color", pk, BLOCKS)
    assert (new, n) == ("~red, %Color", 1)


def test_pin_leaves_unknown_unrecorded_and_other_tokens():
    pk = [cat("Color", "red")]
    prompt = "~saber, ~saber.sword, %Nope, ~nobody*x, %Scene, ~saber*outfit, %Color, ~_~"
    new, n = picks.pin_prompt(prompt, pk, BLOCKS)
    assert new == "~saber, ~saber.sword, %Nope, ~nobody*x, %Scene, ~saber*outfit, ~red, ~_~"
    assert n == 1


def test_pin_noop_without_picks():
    prompt = "%Color, ~saber*outfit, %PCharacter"
    assert picks.pin_prompt(prompt, [], BLOCKS) == (prompt, 0)
    assert picks.pin_prompt(prompt, None, BLOCKS) == (prompt, 0)


def test_pin_skips_picks_that_no_longer_exist():
    pk = [cat("Color", "purple"), cat("Color", "red"), slot("saber", "outfit", "bikini")]
    new, n = picks.pin_prompt("%Color, %Color, ~saber*outfit", pk, BLOCKS)
    # The missing first pick is consumed and its token left alone; the second token gets the second pick.
    assert new == "%Color, ~red, ~saber*outfit"
    assert n == 1
    blocks = {k: v for k, v in BLOCKS.items() if k != "saber"}
    new, n = picks.pin_prompt("~saber*outfit", [slot("saber", "outfit", "dress")], blocks)
    assert (new, n) == ("~saber*outfit", 0)


def test_pin_ignores_malformed_picks():
    pk = [{"kind": "weird"}, {"kind": "category", "category": "Color", "block": None}, cat("Color", "red")]
    new, n = picks.pin_prompt("%Color, %Color", pk, BLOCKS)
    assert (new, n) == ("%Color, ~red", 1)


def test_pin_round_trip_reproduces_output():
    # Pinning the recorded picks of a prompt gives a prompt whose depth-0 choices are fixed.
    blocks = make_blocks()
    prompt = "%Color, ~saber*outfit, %Color"
    for seed in SEEDS:
        text, pk, _ = record(prompt, blocks, seed)
        pinned, n = picks.pin_prompt(prompt, pk, blocks)
        assert n == 3
        assert text.startswith(pk[0]["block"] + ", ") and text.endswith(", " + pk[2]["block"])
        assert pinned == f'~{pk[0]["block"]}, ~saber.{pk[1]["sub"]}, ~{pk[2]["block"]}'


def test_replace_tokens_matches_expand_tokenisation():
    seen = []

    def fn(symbol, name, sub, slot_name):
        seen.append((symbol, name, sub, slot_name))
        return None

    text = "~a.b*c ~a*b.c %Cat.x ~saber. ~_~ %1x"
    assert parser.replace_tokens(text, fn) == text
    assert seen == [("~", "a", "b", None), ("~", "a", None, "b"), ("%", "Cat", None, None),
                    ("~", "saber", None, None)]
