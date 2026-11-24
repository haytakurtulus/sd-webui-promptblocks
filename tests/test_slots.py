"""Slots (design notes section 4): occupied slots, Rules 1-3, block-level slot helpers, hints, row values."""
import json
import random

import pytest

from pb_core import parser, storage, subrows, subs, suggest
from pb_core.weights import category_pool

SEEDS = range(400)


def sub(name, text, mode="include", slot=None):
    return {"name": name, "text": text, "mode": mode, "slot": slot}


def make_blocks():
    return {
        "saber": {"category": "PCharacter", "text": "saber", "subs": [
            sub("armor", "ARMOR", "include", "outfit"),
            sub("dress", "DRESS", "random", "outfit"),
            sub("sword", "SWORD", "include"),
        ]},
        "rin": {"category": "PCharacter", "text": "rin", "subs": [
            sub("uniform", "UNIFORM", "include", "outfit"),
            sub("casual", "CASUAL", "include", "outfit"),
            sub("hair", "TWINTAILS", "include"),
            sub("ribbon", "RIBBON", "random"),
        ]},
        "swimsuit": {"category": "Clothes", "text": "swimsuit", "slot": "outfit"},
        "beach": {"category": "Scene", "text": "~swimsuit, beach"},
    }


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_FILE", str(tmp_path / "blocks.json"))
    monkeypatch.setattr(storage, "THUMB_DIR", str(tmp_path / "thumbs"))


def run(prompt, blocks, seed, **kw):
    trace = []
    text = parser.expand(prompt, blocks, random.Random(seed), trace=trace, **kw)
    return text, trace


def outfit_subs_added(blocks, trace):
    return [(p, s) for p, s in trace if subs.get_sub(blocks[p], s)["slot"] == "outfit"]


# --- occupied_slots ---------------------------------------------------------------------------------

def test_occupied_slots_from_block_and_sub_calls():
    blocks = make_blocks()
    assert parser.occupied_slots("~swimsuit", blocks) == {"outfit"}
    assert parser.occupied_slots("~saber.armor", blocks) == {"outfit"}
    assert parser.occupied_slots("~saber.sword, ~saber, ~rin", blocks) == set()


def test_occupied_slots_ignores_category_unknown_and_nested():
    blocks = make_blocks()
    assert parser.occupied_slots("%Clothes", blocks) == set()
    assert parser.occupied_slots("~nope, ~saber.nope, ~nope.armor", blocks) == set()
    # ~beach contains ~swimsuit only inside its text
    assert parser.occupied_slots("~beach", blocks) == set()


def test_occupied_slots_ignores_broken_slot_values():
    blocks = {"a": {"category": "C", "text": "x", "slot": "bad slot"},
              "b": {"category": "C", "text": "y", "slot": 5}}
    assert parser.occupied_slots("~a, ~b", blocks) == set()


def test_inactive_block_called_directly_still_occupies():
    blocks = make_blocks()
    blocks["swimsuit"]["active"] = False
    assert parser.occupied_slots("~swimsuit", blocks) == {"outfit"}


# --- Acceptance -------------------------------------------------------------------------------------

def test_explicit_sub_plus_category_never_adds_own_outfit():
    # ~saber.armor, %PCharacter: picked character's own outfit-slot subs are never added.
    blocks = make_blocks()
    picked = set()
    for seed in SEEDS:
        text, trace = run("~saber.armor, %PCharacter", blocks, seed)
        assert outfit_subs_added(blocks, trace) == []
        for t in ("DRESS", "UNIFORM", "CASUAL"):
            assert t not in text
        assert text.count("ARMOR") == 1  # only the explicit call
        picked.add("rin" if "rin" in text else "saber")
        if "rin" in text:
            assert "TWINTAILS" in text  # slot-less sub still there
    assert picked == {"saber", "rin"}


def test_block_with_slot_skips_saber_outfit_subs():
    blocks = make_blocks()
    for seed in SEEDS:
        text, trace = run("~swimsuit, ~saber", blocks, seed)
        assert text == "swimsuit, saber, SWORD"
        assert trace == [("saber", "sword")]


def test_occupied_slot_keeps_explicit_calls_and_category_picks():
    blocks = make_blocks()
    # two explicit calls in the same slot: both inserted
    text, _ = run("~saber.armor, ~swimsuit", blocks, 1)
    assert text == "ARMOR, swimsuit"
    text, _ = run("~saber.armor, ~saber.dress, ~rin.uniform", blocks, 1)
    assert text == "ARMOR, DRESS, UNIFORM"
    # %Clothes picks swimsuit (slot outfit) even though outfit is occupied
    for seed in range(20):
        text, _ = run("~saber.armor, %Clothes", blocks, seed)
        assert text == "ARMOR, swimsuit"


def test_slot_only_inside_block_text_does_not_occupy():
    blocks = make_blocks()
    seen = set()
    for seed in SEEDS:
        text, trace = run("~beach, ~saber", blocks, seed)
        added = outfit_subs_added(blocks, trace)
        assert len(added) == 1
        seen.add(added[0][1])
    assert seen == {"armor", "dress"}


def test_slot_in_sub_text_does_not_occupy():
    blocks = make_blocks()
    blocks["scene"] = {"category": "Scene", "text": "park", "subs": [sub("wear", "~saber.armor")]}
    for seed in range(50):
        _, trace = run("~scene, ~rin", blocks, seed)
        assert len([1 for p, s in trace if p == "rin" and s in ("uniform", "casual")]) == 1


def test_occupied_set_reaches_nested_blocks_and_sub_texts():
    # The set comes from the top-level prompt, but applies to parents expanded at any depth.
    blocks = make_blocks()
    blocks["party"] = {"category": "Scene", "text": "party, ~rin", "subs": [sub("guest", "%PCharacter")]}
    for seed in range(100):
        text, trace = run("~swimsuit, ~party", blocks, seed)
        assert outfit_subs_added(blocks, trace) == []
        assert "TWINTAILS" in text


def test_rule2_four_includes_exactly_one_each_seen():
    blocks = {"girl": {"category": "C", "text": "girl", "subs": [
        sub(n, n.upper(), "include", "outfit") for n in ("a", "b", "c", "d")]}}
    seen = set()
    for seed in SEEDS:
        text, trace = run("~girl", blocks, seed)
        assert len(trace) == 1
        name = trace[0][1]
        assert text == "girl, " + name.upper()
        seen.add(name)
    assert seen == {"a", "b", "c", "d"}


# --- Rule 2 / Rule 3 details ------------------------------------------------------------------------

def test_rule2_all_random_usually_one_sometimes_none_never_two():
    blocks = {"girl": {"category": "C", "text": "girl", "subs": [
        sub(n, n.upper(), "random", "outfit") for n in ("a", "b", "c", "d")]}}
    counts = {0: 0, 1: 0}
    seen = set()
    for seed in SEEDS:
        _, trace = run("~girl", blocks, seed)
        assert len(trace) <= 1
        counts[len(trace)] += 1
        seen.update(s for _, s in trace)
    assert counts[1] > counts[0] > 0
    assert seen == {"a", "b", "c", "d"}


def test_rule2_mixed_include_and_random():
    blocks = {"girl": {"category": "C", "text": "girl", "subs": [
        sub("inc", "INC", "include", "outfit"), sub("rnd", "RND", "random", "outfit"),
        sub("exc", "EXC", "exclude", "outfit")]}}
    seen = set()
    for seed in SEEDS:
        _, trace = run("~girl", blocks, seed)
        assert len(trace) == 1
        assert trace[0][1] != "exc"
        seen.add(trace[0][1])
    assert seen == {"inc", "rnd"}


def test_two_slots_on_one_parent_are_independent():
    blocks = {"girl": {"category": "C", "text": "girl", "subs": [
        sub("o1", "O1", "include", "outfit"), sub("h1", "H1", "include", "hair"),
        sub("o2", "O2", "include", "outfit"), sub("h2", "H2", "include", "hair")]}}
    combos = set()
    for seed in SEEDS:
        _, trace = run("~girl", blocks, seed)
        names = [s for _, s in trace]
        assert len(names) == 2
        outfit = [n for n in names if n.startswith("o")]
        hair = [n for n in names if n.startswith("h")]
        assert len(outfit) == 1 and len(hair) == 1
        combos.add((outfit[0], hair[0]))
    assert combos == {("o1", "h1"), ("o1", "h2"), ("o2", "h1"), ("o2", "h2")}
    # occupying one slot leaves the other untouched
    blocks["cap"] = {"category": "C", "text": "cap", "slot": "hair"}
    for seed in range(50):
        _, trace = run("~cap, ~girl", blocks, seed)
        names = [s for _, s in trace]
        assert len(names) == 1 and names[0] in ("o1", "o2")


def test_output_order_is_list_order():
    blocks = {"girl": {"category": "C", "text": "girl", "subs": [
        sub("first", "FIRST", "include"), sub("o1", "O1", "include", "outfit"),
        sub("last", "LAST", "include"), sub("o2", "O2", "include", "outfit")]}}
    for seed in range(50):
        text, _ = run("~girl", blocks, seed)
        assert text in ("girl, FIRST, O1, LAST", "girl, FIRST, LAST, O2")


def test_rule3_slotless_subs_unaffected_by_occupied_slot():
    blocks = make_blocks()
    ribbon = set()
    for seed in SEEDS:
        text, trace = run("~swimsuit, ~rin", blocks, seed)
        assert "TWINTAILS" in text
        assert "UNIFORM" not in text and "CASUAL" not in text
        ribbon.add("RIBBON" in text)
    assert ribbon == {True, False}


def test_category_pick_with_slot_does_not_occupy():
    blocks = make_blocks()
    for seed in range(100):
        _, trace = run("%Clothes, ~rin", blocks, seed)
        assert len([s for p, s in trace if s in ("uniform", "casual")]) == 1


def test_explicit_occupied_argument_and_nested_default():
    blocks = make_blocks()
    _, trace = run("~rin", blocks, 3, occupied={"outfit"})
    assert ("rin", "uniform") not in trace and ("rin", "casual") not in trace
    # below depth 0 without an explicit set nothing is occupied (only the top-level prompt counts)
    text = parser.expand("~swimsuit, ~saber", blocks, random.Random(0), depth=1)
    assert "ARMOR" in text or "DRESS" in text


def test_trace_lists_only_added_subs():
    blocks = make_blocks()
    for seed in range(100):
        text, trace = run("~rin", blocks, seed)
        for p, s in trace:
            assert subs.get_sub(blocks[p], s)["text"] in text
        assert ("rin", "ribbon") in trace or "RIBBON" not in text


def test_direct_call_of_slotted_excluded_sub_still_works():
    blocks = {"girl": {"category": "C", "text": "girl", "subs": [sub("x", "X", "exclude", "outfit")]}}
    assert run("~girl.x", blocks, 0)[0] == "X"
    assert run("~girl", blocks, 0)[0] == "girl"


def test_broken_slot_on_sub_is_treated_as_slotless():
    blocks = {"girl": {"category": "C", "text": "girl", "subs": [
        sub("a", "A", "include", "bad slot"), sub("b", "B", "include", 7)]}}
    assert run("~girl", blocks, 0)[0] == "girl, A, B"


# --- RNG parity -------------------------------------------------------------------------------------

def _old_expand(prompt, blocks, rng, depth=0):
    # Sub-block expansion exactly as before slots existed (section 3), for RNG parity checks.
    if depth > parser.MAX_DEPTH:
        raise parser.BlockCycleError("too deep")

    def block_text(name, block):
        parts = [_old_expand(block["text"], blocks, rng, depth + 1)]
        for s in subs.normalize_subs(block):
            if s["mode"] == "exclude":
                continue
            if s["mode"] == "random" and not rng.random() < parser.DEFAULT_CHANCE / 100:
                continue
            parts.append(_old_expand(s["text"], blocks, rng, depth + 1))
        if len(parts) == 1:
            return parts[0]
        return parser.SUB_JOINER.join(p for p in parts if p.strip())

    def repl(m):
        symbol, name, sub_name = parser._parts(m)
        if symbol == parser.BLOCK_SYMBOL:
            block = blocks.get(name)
            if block is None:
                return m.group(0)
            if sub_name is not None:
                s = subs.get_sub(block, sub_name)
                return m.group(0) if s is None else _old_expand(s["text"], blocks, rng, depth + 1)
        else:
            pool = category_pool(blocks, name)
            if not pool:
                return m.group(0)
            name = parser._pick(pool, blocks, rng)
            block = blocks[name]
        return block_text(name, block)

    return parser._TOKEN.sub(repl, prompt)


def _slotless_blocks():
    return {
        "a": {"category": "P", "text": "A %Q", "subs": [sub("r1", "R1 %Q", "random"), sub("i", "I")]},
        "b": {"category": "P", "text": "B", "subs": [sub("r", "R", "random"), sub("e", "E", "exclude")]},
        "c": {"category": "P", "text": "C", "weight": 3},
        "q1": {"category": "Q", "text": "q1"},
        "q2": {"category": "Q", "text": "q2", "subs": [sub("r", "QR", "random")]},
        "swim": {"category": "Clothes", "text": "swim", "slot": "outfit"},
    }


@pytest.mark.parametrize("prompt", [
    "%P, %P, %Q",
    "~a, ~b, %P",
    "~swim, %P, %Q, ~a",          # occupied slot, but no parent has slotted subs
    "%Clothes, ~a.r1, %P",
])
def test_rng_parity_for_parents_without_slotted_subs(prompt):
    blocks = _slotless_blocks()
    for seed in range(200):
        r_new, r_old = random.Random(seed), random.Random(seed)
        assert parser.expand(prompt, blocks, r_new) == _old_expand(prompt, blocks, r_old)
        assert r_new.random() == r_old.random()  # same amount of RNG consumed


def test_slotted_subs_with_single_include_or_occupied_slot_use_no_rng():
    # One Include candidate per slot -> no rng.choice; occupied slot -> no draw; result as if slot-less.
    blocks = {
        "girl": {"category": "P", "text": "girl", "subs": [
            sub("o", "O", "include", "outfit"), sub("r", "R", "random"),
            sub("h1", "H1", "random", "hair"), sub("h2", "H2", "random", "hair")]},
        "cap": {"category": "X", "text": "cap", "slot": "hair"},
    }
    plain = {"girl": {"category": "P", "text": "girl", "subs": [sub("o", "O"), sub("r", "R", "random")]},
             "cap": {"category": "X", "text": "cap"}}
    for seed in range(100):
        r_new, r_old = random.Random(seed), random.Random(seed)
        assert parser.expand("~cap, ~girl", blocks, r_new) == parser.expand("~cap, ~girl", plain, r_old)
        assert r_new.random() == r_old.random()


# --- block-level slot helpers -----------------------------------------------------------------------

def test_block_slot_normalisation():
    assert subs.block_slot({"text": "x"}) is None
    assert subs.block_slot({"text": "x", "slot": "outfit"}) == "outfit"
    for bad in ("", "bad slot", "1x", 5, None, ["outfit"], "out.fit"):
        assert subs.block_slot({"text": "x", "slot": bad}) is None
    assert subs.block_slot(None) is None
    assert subs.block_slot("nope") is None


def test_set_block_slot():
    b = {"category": "C", "text": "x", "slot": "old"}
    assert subs.set_block_slot(b, "outfit")["slot"] == "outfit"
    assert subs.set_block_slot(b, "  outfit ")["slot"] == "outfit"
    for empty in (None, "", "   "):
        assert "slot" not in subs.set_block_slot(b, empty)
    assert b["slot"] == "old"  # input not modified
    with pytest.raises(ValueError):
        subs.set_block_slot(b, "bad slot")


def test_validate_slot():
    assert subs.validate_slot(None) == (None, None)
    assert subs.validate_slot("  ") == (None, None)
    assert subs.validate_slot(" outfit ") == ("outfit", None)
    for bad in ("bad slot", "1x", 5):
        slot, err = subs.validate_slot(bad)
        assert slot is None and "invalid slot" in err


def test_block_slot_json_round_trip_and_old_json(tmp_path):
    blocks = {"swim": subs.set_block_slot({"category": "C", "text": "s"}, "outfit"),
              "old": {"category": "C", "text": "o"}}
    storage.save_blocks(blocks)
    loaded = storage.load_blocks()
    assert subs.block_slot(loaded["swim"]) == "outfit"
    assert subs.block_slot(loaded["old"]) is None
    assert "slot" not in loaded["old"]
    raw = json.loads((tmp_path / "blocks.json").read_text(encoding="utf-8"))
    assert raw["version"] == 1


# --- suggest ----------------------------------------------------------------------------------------

def test_slot_counts_blocks_and_subs():
    blocks = make_blocks()
    blocks["bad"] = {"category": "C", "text": "x", "slot": "bad slot",
                     "subs": [sub("s", "t", slot="look")]}
    assert suggest.slot_counts(blocks) == {"outfit": 5, "look": 1}
    assert suggest.slot_counts({}) == {}


def test_slot_hint():
    blocks = make_blocks()
    assert suggest.slot_hint("outfit", blocks) == "Existing slot (5 uses)."
    assert "Did you mean: `outfit`" in suggest.slot_hint("outfits", blocks)
    assert "Did you mean: `outfit`" in suggest.slot_hint("Outfit", blocks)
    assert suggest.slot_hint("location", blocks) == "New slot `location`."
    assert suggest.slot_hint("", blocks) == ""
    assert suggest.slot_hint(None, blocks) == ""
    assert suggest.slot_hint(" outfit ", blocks) == "Existing slot (5 uses)."
    one = {"a": {"category": "C", "text": "x", "slot": "hat"}}
    assert suggest.slot_hint("hat", one) == "Existing slot (1 use)."


def test_row_slots_hint():
    blocks = make_blocks()
    assert suggest.row_slots_hint(["outfit", None, "", "  "], blocks) == ""
    hint = suggest.row_slots_hint(["outfit", "outfits", None, "location"], blocks)
    assert "Sub-block 2: New slot `outfits`. Did you mean: `outfit`?" in hint
    assert "Sub-block 4: New slot `location`." in hint
    assert "Sub-block 1" not in hint


# --- row values (management tab) --------------------------------------------------------------------

def test_rows_values_round_trip():
    rows = subrows.rows_from_block(make_blocks()["rin"])
    values = subrows.rows_to_values(rows)
    n = subrows.ROW_COUNT
    assert len(values) == 4 * n + 1
    assert values[3 * n:4 * n] == ["outfit", "outfit", None, None] + [None] * (n - 4)
    assert values[-1] == ([{"orig": "uniform"}, {"orig": "casual"}, {"orig": "hair"}, {"orig": "ribbon"}]
                          + [{"orig": None}] * (n - 4))
    assert subrows.rows_from_values(values) == rows


def test_rows_from_values_slot_comes_from_visible_field_not_meta():
    rows = subrows.rows_from_block(make_blocks()["rin"])
    values = subrows.rows_to_values(rows)
    n = subrows.ROW_COUNT
    values[-1] = [dict(m, slot="stale") for m in values[-1]]  # old-style meta must be ignored
    values[3 * n + 0] = "  clothes "
    values[3 * n + 1] = ""
    values[3 * n + 2] = "look"
    got = subrows.rows_from_values(values)
    assert [r["slot"] for r in got] == ["clothes", None, "look", None] + [None] * (n - 4)
    assert [r["orig"] for r in got] == ["uniform", "casual", "hair", "ribbon"] + [None] * (n - 4)


def test_rows_from_values_broken_meta_and_none_values():
    n = subrows.ROW_COUNT
    values = [None] * (4 * n) + ["garbage"]
    assert subrows.rows_from_values(values) == [subrows.empty_row() for _ in range(n)]
    assert subrows.rows_from_values([None] * (4 * n)) == [subrows.empty_row() for _ in range(n)]


def test_round_trip_pick_edit_slot_reorder_save_repick():
    blocks = make_blocks()
    n = subrows.ROW_COUNT
    # pick
    values = subrows.rows_to_values(subrows.rows_from_block(blocks["saber"]))
    # edit slot of row 3 (sword) and clear the slot of row 1 (armor)
    values[3 * n + 2] = "weapon"
    values[3 * n + 0] = None
    # move row 3 up
    values = subrows.rows_to_values(subrows.move_row(subrows.rows_from_values(values), 2, -1))
    assert values[:3] == ["armor", "sword", "dress"]
    assert values[3 * n:3 * n + 3] == [None, "weapon", "outfit"]
    # rename the moved row too
    values[1] = "blade"
    plan, err = subrows.plan_save(subrows.rows_from_values(values), blocks["saber"], True)
    assert err is None
    assert plan["renames"] == {"sword": "blade"} and plan["removals"] == []
    saved = subs.set_subs(blocks["saber"], plan["subs"])
    assert [(s["name"], s["slot"]) for s in subs.normalize_subs(saved)] == [
        ("armor", None), ("blade", "weapon"), ("dress", "outfit")]
    # re-pick
    again = subrows.rows_to_values(subrows.rows_from_block(saved))
    assert again[3 * n:4 * n] == [None, "weapon", "outfit"] + [None] * (n - 3)


def test_invalid_row_slot_rejected_by_plan_save():
    n = subrows.ROW_COUNT
    values = subrows.rows_to_values(subrows.rows_from_block(make_blocks()["saber"]))
    values[3 * n] = "bad slot"
    plan, err = subrows.plan_save(subrows.rows_from_values(values), make_blocks()["saber"], True)
    assert plan is None and "invalid slot" in err


# --- API helpers ------------------------------------------------------------------------------------

def test_api_block_slots():
    blocks = make_blocks()
    assert subrows.api_block_slots(blocks["swimsuit"]) == {"slot": "outfit", "subs": []}
    got = subrows.api_block_slots(blocks["saber"])
    assert got["slot"] is None
    assert got["subs"][0] == {"name": "armor", "mode": "include", "text": "ARMOR", "slot": "outfit"}
    assert got["subs"][2]["slot"] is None
    assert subrows.api_block_slots({"text": "x", "slot": "bad slot"})["slot"] is None


def test_slot_choices_and_preview_occupied_list():
    blocks = make_blocks()
    blocks["x"] = {"category": "C", "text": "x", "subs": [sub("s", "t", slot="hair")]}
    assert subrows.slot_choices(blocks) == ["hair", "outfit"]
    assert sorted(parser.occupied_slots("~x.s, ~swimsuit, ~saber.sword", blocks)) == ["hair", "outfit"]


# --- Own-slot exception (section 4, decided 2026-11-14) ---------------------------------------------

def own_slot_blocks():
    blocks = make_blocks()
    blocks["swimsuit"]["subs"] = [
        sub("bikini", "BIKINI", "include", "outfit"),
        sub("onepiece", "ONEPIECE", "include", "outfit"),
        sub("wet", "WET", "include"),
    ]
    blocks["kimono"] = {"category": "Clothes", "text": "kimono", "slot": "outfit", "subs": [
        sub("furisode", "FURISODE", "include", "outfit"),
        sub("yukata", "YUKATA", "include", "outfit"),
    ]}
    return blocks


def test_own_call_keeps_own_slot_subs_rule2_still_one():
    blocks = own_slot_blocks()
    seen = set()
    for seed in SEEDS:
        text, trace = run("~swimsuit", blocks, seed)
        added = outfit_subs_added(blocks, trace)
        assert len(added) == 1 and added[0][0] == "swimsuit"
        assert ("swimsuit", "wet") in trace
        seen.add(added[0][1])
    assert seen == {"bikini", "onepiece"}


def test_own_call_keeps_own_subs_but_occupies_for_others():
    blocks = own_slot_blocks()
    for seed in SEEDS:
        text, trace = run("~swimsuit, ~saber", blocks, seed)
        added = outfit_subs_added(blocks, trace)
        assert len(added) == 1 and added[0][0] == "swimsuit"
        assert "ARMOR" not in text and "DRESS" not in text


def test_other_explicit_sub_occupies_own_slot():
    blocks = own_slot_blocks()
    for seed in SEEDS:
        text, trace = run("~saber.armor, ~swimsuit", blocks, seed)
        assert outfit_subs_added(blocks, trace) == []
        assert text == "ARMOR, swimsuit, WET"


def test_explicit_own_sub_call_occupies_own_slot():
    blocks = own_slot_blocks()
    for seed in SEEDS:
        text, trace = run("~swimsuit.bikini, ~swimsuit", blocks, seed)
        assert outfit_subs_added(blocks, trace) == []
        assert text == "BIKINI, swimsuit, WET"
        assert text.count("BIKINI") == 1


def test_same_block_called_twice_keeps_own_subs_in_both():
    blocks = own_slot_blocks()
    for seed in SEEDS:
        _, trace = run("~swimsuit, ~swimsuit", blocks, seed)
        added = outfit_subs_added(blocks, trace)
        assert len(added) == 2 and all(p == "swimsuit" for p, _ in added)


def test_two_slotted_blocks_in_same_slot_suppress_each_other():
    blocks = own_slot_blocks()
    for seed in SEEDS:
        text, trace = run("~swimsuit, ~kimono", blocks, seed)
        assert outfit_subs_added(blocks, trace) == []
        assert text == "swimsuit, WET, kimono"


def test_category_pick_of_own_block_decided_by_occupiers():
    # swimsuit reached via %Clothes and via ~swimsuit: only ~swimsuit occupies -> own subs stay.
    blocks = own_slot_blocks()
    del blocks["kimono"]
    for seed in range(100):
        _, trace = run("~swimsuit, %Clothes", blocks, seed)
        assert len(outfit_subs_added(blocks, trace)) == 2


def test_occupied_slots_unchanged_and_occupiers_helper():
    blocks = own_slot_blocks()
    assert parser.occupied_slots("~swimsuit", blocks) == {"outfit"}
    assert parser.slot_occupiers("~swimsuit", blocks) == {"outfit": {("swimsuit", None)}}
    assert parser.slot_occupiers("~swimsuit.bikini, ~swimsuit, ~swimsuit, %Clothes, ~nope", blocks) == {
        "outfit": {("swimsuit", "bikini"), ("swimsuit", None)}}
    assert parser.slot_occupiers("~saber.sword, ~beach", blocks) == {}


def test_explicit_set_still_suppresses_own_subs_unconditionally():
    blocks = own_slot_blocks()
    for seed in range(100):
        _, trace = run("~swimsuit", blocks, seed, occupied={"outfit"})
        assert outfit_subs_added(blocks, trace) == []
        assert ("swimsuit", "wet") in trace
