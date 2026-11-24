"""Adjustable chance for Random sub-blocks (design notes section 14, E2b)."""

import json
import random

import pytest

from pb_core import parser, storage, subrows, subs

N = subrows.ROW_COUNT


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_FILE", str(tmp_path / "blocks.json"))
    monkeypatch.setattr(storage, "THUMB_DIR", str(tmp_path / "thumbs"))


def parent(chance=None, slot=None, mode="random", extra_subs=()):
    entry = {"name": "hat", "text": "HAT", "mode": mode, "slot": slot}
    if chance is not None:
        entry["chance"] = chance
    return {"blocks": {"saber": {"category": "P", "text": "saber", "subs": [entry, *extra_subs]}}}


def share(blocks, token="~saber", needle="HAT", seeds=4000):
    hits = sum(needle in parser.expand(token, blocks, random.Random(s)) for s in range(seeds))
    return hits / seeds


# --- expansion ------------------------------------------------------------------------------------

def mixed_blocks(chance_value):
    # Slot-less and slotted Random subs, an Include sub, nested picks; chance_value is written into every
    # Random sub (None = key missing).
    def r(name, text, slot=None):
        e = {"name": name, "text": text, "mode": "random", "slot": slot}
        if chance_value is not None:
            e["chance"] = chance_value
        return e
    return {
        "saber": {"category": "P", "text": "saber, %Hair", "subs": [
            r("hat", "HAT"), {"name": "armor", "text": "ARMOR", "mode": "include", "slot": "outfit"},
            r("dress", "DRESS", "outfit"), r("cape", "CAPE, %Hair")]},
        "rin": {"category": "P", "text": "rin", "subs": [r("ribbon", "RIBBON"), r("bow", "BOW")]},
        "blond": {"category": "Hair", "text": "blond"},
        "black": {"category": "Hair", "text": "black"},
    }


@pytest.mark.parametrize("variant", [50, 50.0, "abc", True, 0, 101, -5, float("nan"), float("inf"), 30.5,
                                     None, [50]])
def test_default_and_broken_chance_parity_over_seeds(variant):
    # Chance 50 (and every broken value, which behaves as 50) gives exactly the result of the old data
    # without the key, seed by seed, and leaves the RNG in the same state.
    old, new = mixed_blocks(None), mixed_blocks(variant)
    for seed in range(300):
        for prompt in ("~saber", "%P, ~rin", "~saber, ~saber*outfit"):
            r_old, r_new = random.Random(seed), random.Random(seed)
            t_old, t_new = [], []
            assert (parser.expand(prompt, new, r_new, trace=t_new)
                    == parser.expand(prompt, old, r_old, trace=t_old))
            assert t_new == t_old
            assert r_new.getstate() == r_old.getstate()


def test_default_matches_plain_half_draw():
    # Independent reference: a slot-less Random sub is added iff Random(seed).random() < 0.5.
    blocks = parent()["blocks"]
    for seed in range(500):
        expected = "saber, HAT" if random.Random(seed).random() < 0.5 else "saber"
        assert parser.expand("~saber", blocks, random.Random(seed)) == expected


def test_chance_100_always_and_1_almost_never():
    assert share(parent(100)["blocks"], seeds=2000) == 1.0
    assert share(parent(1)["blocks"], seeds=2000) < 0.03


def test_share_for_25_within_bounds():
    assert 0.21 <= share(parent(25)["blocks"]) <= 0.29


def test_chance_ignored_for_include_and_exclude():
    assert share(parent(1, mode="include")["blocks"], seeds=200) == 1.0
    assert share(parent(100, mode="exclude")["blocks"], seeds=200) == 0.0


def test_non_default_chance_still_one_draw_per_random_sub():
    # Same RNG consumption as chance 50: rin's subs are slot-less and their texts use no RNG, so the RNG
    # state afterwards (and the following %Hair pick) must not depend on the chance.
    for chance in (1, 25, 100):
        for seed in range(100):
            r50, rc = random.Random(seed), random.Random(seed)
            out50 = parser.expand("~rin, %Hair", mixed_blocks(50), r50)
            outc = parser.expand("~rin, %Hair", mixed_blocks(chance), rc)
            assert r50.getstate() == rc.getstate()
            assert out50.split(", ")[-1] == outc.split(", ")[-1]


def test_slotted_random_sub_chance_100_always_candidate():
    # Alone in its slot: chance 100 -> always added; chance 1 -> almost never.
    assert share(parent(100, slot="outfit")["blocks"], seeds=2000) == 1.0
    assert share(parent(1, slot="outfit")["blocks"], seeds=2000) < 0.03
    assert 0.21 <= share(parent(25, slot="outfit")["blocks"]) <= 0.29


def test_slotted_random_sub_competes_with_include():
    # Include + Random(100) in one slot: both always candidates -> rng.choice, each about half.
    inc = {"name": "armor", "text": "ARMOR", "mode": "include", "slot": "outfit"}
    blocks = parent(100, slot="outfit", extra_subs=[inc])["blocks"]
    outs = [parser.expand("~saber", blocks, random.Random(s)) for s in range(2000)]
    assert all(("HAT" in o) != ("ARMOR" in o) for o in outs)
    assert 0.4 < sum("HAT" in o for o in outs) / len(outs) < 0.6
    # Random(1) + Include: the Include sub wins almost every time.
    blocks = parent(1, slot="outfit", extra_subs=[inc])["blocks"]
    outs = [parser.expand("~saber", blocks, random.Random(s)) for s in range(2000)]
    assert sum("HAT" in o for o in outs) / len(outs) < 0.03


def test_slotted_random_sub_in_occupied_slot_is_still_skipped():
    blocks = parent(100, slot="outfit")["blocks"]
    blocks["swimsuit"] = {"category": "O", "text": "swimsuit", "slot": "outfit"}
    for s in range(50):
        assert "HAT" not in parser.expand("~swimsuit, ~saber", blocks, random.Random(s))


def test_direct_sub_call_ignores_chance():
    blocks = parent(1)["blocks"]
    assert parser.expand("~saber.hat", blocks, random.Random(0)) == "HAT"


# --- normalisation / storage ----------------------------------------------------------------------

def test_sub_chance_values():
    assert subs.sub_chance({"chance": 30}) == 30
    assert subs.sub_chance({"chance": 30.0}) == 30
    assert subs.sub_chance({"chance": 1}) == 1 and subs.sub_chance({"chance": 100}) == 100
    for broken in ("30", "abc", True, False, 0, 101, -1, 30.5, float("nan"), float("inf"), None, [30], {}):
        assert subs.sub_chance({"chance": broken}) == subs.DEFAULT_CHANCE
    assert subs.sub_chance({}) == 50
    assert subs.sub_chance(None) == 50 and subs.sub_chance("junk") == 50


def test_normalize_adds_chance_only_when_not_default():
    block = {"text": "t", "subs": [
        {"name": "a", "text": "A", "mode": "random", "chance": 30},
        {"name": "b", "text": "B", "mode": "random", "chance": 50},
        {"name": "c", "text": "C", "mode": "random", "chance": "junk"},
        {"name": "d", "text": "D", "mode": "include", "chance": 70.0},
    ]}
    got = subs.normalize_subs(block)
    assert got[0] == {"name": "a", "text": "A", "mode": "random", "slot": None, "chance": 30}
    assert "chance" not in got[1] and "chance" not in got[2]
    assert got[3]["chance"] == 70 and isinstance(got[3]["chance"], int)


def test_old_json_without_chance_loads_and_round_trips(tmp_path):
    raw = {"version": 1, "blocks": {"saber": {"category": "P", "text": "s",
                                              "subs": [{"name": "hat", "text": "H", "mode": "random"}]}}}
    (tmp_path / "blocks.json").write_text(json.dumps(raw), encoding="utf-8")
    blocks = storage.load_blocks()
    assert subs.sub_chance(blocks["saber"]["subs"][0]) == 50
    rows = subrows.rows_from_block(blocks["saber"])
    plan, err = subrows.plan_save(rows, blocks["saber"], True)
    assert err is None
    storage.save_blocks({"saber": subs.set_subs(blocks["saber"], plan["subs"])})
    stored = json.loads((tmp_path / "blocks.json").read_text(encoding="utf-8"))
    assert "chance" not in stored["blocks"]["saber"]["subs"][0]


# --- validation -----------------------------------------------------------------------------------

def vrow(chance, mode="random"):
    return {"name": "hat", "text": "HAT", "mode": mode, "slot": None, "chance": chance}


@pytest.mark.parametrize("value,expected", [(30, 30), (30.0, 30), (1, 1), (100, 100), (1.0, 1), (100.0, 100)])
def test_validate_accepts_whole_numbers(value, expected):
    cleaned, err = subs.validate_subs([vrow(value)])
    assert err is None
    assert cleaned[0]["chance"] == expected and isinstance(cleaned[0]["chance"], int)


@pytest.mark.parametrize("value", [None, "", "  ", 50, 50.0])
def test_validate_default_omits_key(value):
    cleaned, err = subs.validate_subs([vrow(value)])
    assert err is None
    assert cleaned == [{"name": "hat", "text": "HAT", "mode": "random", "slot": None}]


def test_validate_row_without_chance_key_is_default():
    cleaned, err = subs.validate_subs([{"name": "hat", "text": "HAT", "mode": "random"}])
    assert err is None and "chance" not in cleaned[0]


@pytest.mark.parametrize("value", [0, 101, -1, 0.0, 101.0, 30.5, "abc", "30", True, False,
                                   float("nan"), float("inf"), [30], {"x": 1}])
def test_validate_rejects_bad_chance(value):
    cleaned, err = subs.validate_subs([vrow(value)])
    assert cleaned is None
    assert "Sub-block `hat`" in err and "invalid chance" in err and "1..100" in err


def test_validate_chance_kept_for_non_random_modes():
    # The value is kept (not used) when the mode is Include / Exclude, so switching back keeps it.
    cleaned, err = subs.validate_subs([vrow(30, "include")])
    assert err is None and cleaned[0]["chance"] == 30
    cleaned, err = subs.validate_subs([vrow(0, "exclude")])
    assert cleaned is None and "invalid chance" in err


def test_validate_chance_helper():
    assert subs.validate_chance(None) == (50, None)
    assert subs.validate_chance(42.0) == (42, None)
    c, err = subs.validate_chance(0)
    assert c is None and "invalid chance `0`" in err


def test_key_omitted_at_50_in_stored_json(tmp_path):
    cleaned, _ = subs.validate_subs([vrow(50), dict(vrow(30), name="cap")])
    storage.save_blocks({"saber": subs.set_subs({"category": "P", "text": "s"}, cleaned)})
    stored = json.loads((tmp_path / "blocks.json").read_text(encoding="utf-8"))["blocks"]["saber"]["subs"]
    assert "chance" not in stored[0]
    assert stored[1]["chance"] == 30


# --- row helpers ----------------------------------------------------------------------------------

def stored_block():
    return {"category": "P", "text": "saber", "subs": [
        {"name": "armor", "text": "ARMOR", "mode": "include", "slot": "outfit"},
        {"name": "hat", "text": "HAT", "mode": "random", "chance": 30},
        {"name": "cape", "text": "CAPE", "mode": "random"},
    ]}


def test_empty_and_blank_rows_have_default_chance():
    assert subrows.empty_row()["chance"] == 50
    assert all(r["chance"] == 50 for r in subrows.blank_form()["rows"])


def test_rows_from_block_carries_chance():
    rows = subrows.rows_from_block(stored_block())
    assert [r["chance"] for r in rows] == [50, 30, 50] + [50] * (N - 3)


def test_rows_to_values_with_chance_layout_and_round_trip():
    rows = subrows.rows_from_block(stored_block())
    values = subrows.rows_to_values(rows, with_chance=True)
    assert len(values) == 5 * N + 1
    assert values[4 * N] == [{"orig": "armor"}, {"orig": "hat"}, {"orig": "cape"}] + [{"orig": None}] * (N - 3)
    assert values[4 * N + 1:] == [50, 30, 50] + [50] * (N - 3)
    assert subrows.rows_from_values(values) == rows
    # The default layout (no chance group) is unchanged; reading it gives the default chance.
    assert subrows.rows_to_values(rows) == values[:4 * N + 1]


def test_rows_from_values_chance_none_or_blank_is_default():
    values = subrows.rows_to_values(subrows.rows_from_block(stored_block()), with_chance=True)
    values[4 * N + 1] = None
    values[4 * N + 2] = ""
    values[4 * N + 3] = 70.0
    got = subrows.rows_from_values(values)
    assert [r["chance"] for r in got] == [50, 50, 70.0] + [50] * (N - 3)


def test_form_values_with_chance_layout():
    nf = len(subrows.FORM_FIELDS)
    values = subrows.form_values(subrows.blank_form(), with_chance=True)
    assert len(values) == nf + 5 * N + 1
    assert values[nf + 4 * N + 1:] == [50] * N
    f = subrows.block_form({"saber": stored_block()}, "saber")
    values = subrows.form_values(f, with_chance=True)
    assert subrows.rows_from_values(values[nf:]) == f["rows"]


def test_move_carries_chance():
    rows = subrows.rows_from_block(stored_block())
    up = subrows.move_row(rows, 1, -1)
    assert [(r["name"], r["chance"]) for r in up[:2]] == [("hat", 30), ("armor", 50)]
    down = subrows.move_row(rows, 1, 1)
    assert [(r["name"], r["chance"]) for r in down[1:3]] == [("cape", 50), ("hat", 30)]


def test_plan_save_carries_chance_and_rejects_invalid():
    rows = subrows.rows_from_block(stored_block())
    rows[2]["chance"] = 80.0
    plan, err = subrows.plan_save(rows, stored_block(), True)
    assert err is None
    assert [s.get("chance") for s in plan["subs"]] == [None, 30, 80]
    rows[0]["chance"] = 0
    plan, err = subrows.plan_save(rows, stored_block(), True)
    assert plan is None and "invalid chance" in err


def test_round_trip_pick_edit_move_save_repick(tmp_path):
    storage.save_blocks({"saber": stored_block()})
    blocks = storage.load_blocks()
    # pick
    values = subrows.rows_to_values(subrows.rows_from_block(blocks["saber"]), with_chance=True)
    # set cape (row 3) to 25, then move it up to row 2
    values[4 * N + 1 + 2] = 25.0
    values = subrows.rows_to_values(subrows.move_row(subrows.rows_from_values(values), 2, -1),
                                    with_chance=True)
    assert values[:3] == ["armor", "cape", "hat"]
    assert values[4 * N + 1:4 * N + 4] == [50, 25.0, 30]
    # save
    plan, err = subrows.plan_save(subrows.rows_from_values(values), blocks["saber"], True)
    assert err is None and plan["renames"] == {} and plan["removals"] == []
    storage.save_blocks({"saber": subs.set_subs(blocks["saber"], plan["subs"])})
    stored = json.loads((tmp_path / "blocks.json").read_text(encoding="utf-8"))["blocks"]["saber"]["subs"]
    assert [(s["name"], s.get("chance")) for s in stored] == [("armor", None), ("cape", 25), ("hat", 30)]
    # re-pick
    again = subrows.rows_to_values(subrows.rows_from_block(storage.load_blocks()["saber"]), with_chance=True)
    assert again[4 * N + 1:] == [50, 25, 30] + [50] * (N - 3)
    # set hat back to 50 -> key removed
    again[4 * N + 1 + 2] = 50
    plan, err = subrows.plan_save(subrows.rows_from_values(again), storage.load_blocks()["saber"], True)
    assert err is None
    storage.save_blocks({"saber": subs.set_subs(storage.load_blocks()["saber"], plan["subs"])})
    stored = json.loads((tmp_path / "blocks.json").read_text(encoding="utf-8"))["blocks"]["saber"]["subs"]
    assert "chance" not in stored[2] and stored[1]["chance"] == 25


# --- API ------------------------------------------------------------------------------------------

def test_api_block_slots_exposes_chance_only_when_not_default():
    got = subrows.api_block_slots(stored_block())["subs"]
    assert got[0] == {"name": "armor", "mode": "include", "text": "ARMOR", "slot": "outfit"}
    assert got[1] == {"name": "hat", "mode": "random", "text": "HAT", "slot": None, "chance": 30}
    assert "chance" not in got[2]
    broken = {"text": "t", "subs": [{"name": "a", "text": "A", "mode": "random", "chance": "x"}]}
    assert "chance" not in subrows.api_block_slots(broken)["subs"][0]
