import math
import random

import pytest

from pb_core.parser import expand, find_all_inactive, preview_warnings
from pb_core.parser import BLOCK_SYMBOL as B, CATEGORY_SYMBOL as C
from pb_core.weights import is_active, category_pool, chances, chance_line


def rng(seed=1):
    return random.Random(seed)


def _blocks():
    # Text equals the name, so the expansion result is the picked name.
    return {
        "delta":   {"category": "Cat", "text": "delta"},
        "alpha":   {"category": "Cat", "text": "alpha", "active": False},
        "charlie": {"category": "Cat", "text": "charlie", "weight": 2},
        "bravo":   {"category": "Cat", "text": "bravo", "active": True},
        "ghost1":  {"category": "Dead", "text": "ghost1", "active": False},
        "ghost2":  {"category": "Dead", "text": "ghost2", "active": False},
    }


# --- is_active ---

def test_missing_active_is_active():
    assert is_active({"category": "C", "text": "t"})


def test_explicit_true_and_false():
    assert is_active({"category": "C", "text": "t", "active": True})
    assert not is_active({"category": "C", "text": "t", "active": False})


@pytest.mark.parametrize("value", ["no", "false", 0, None, 1, "", [], {}, 0.0])
def test_broken_active_values_behave_as_active(value):
    assert is_active({"category": "C", "text": "t", "active": value})


def test_is_active_non_dict_never_raises():
    assert is_active(None)
    assert is_active("x")


# --- chances ---

def test_chances_omit_inactive_and_sum_to_one():
    ch = chances(_blocks(), "Cat")
    assert "alpha" not in ch
    assert set(ch) == {"bravo", "charlie", "delta"}
    assert math.isclose(sum(ch.values()), 1.0)
    assert ch == {"bravo": 0.25, "charlie": 0.5, "delta": 0.25}


def test_chances_all_inactive_is_empty():
    assert chances(_blocks(), "Dead") == {}


def test_category_pool_sorted_active_only():
    assert category_pool(_blocks(), "Cat") == ["bravo", "charlie", "delta"]
    assert category_pool(_blocks(), "Dead") == []


def test_chance_line_inactive():
    assert chance_line(_blocks(), "alpha", "Cat") == f"Inactive: not in `{C}Cat` picks"
    assert chance_line(_blocks(), "ghost1", "Dead") == f"Inactive: not in `{C}Dead` picks"


def test_chance_line_active_excludes_inactive_from_total():
    assert chance_line(_blocks(), "charlie", "Cat") == f"Chance in `{C}Cat`: 50% (weight 2 of 4)"
    assert chance_line(_blocks(), "alpha", "Other") == ""


# --- expand ---

def test_category_never_picks_inactive_over_1000_seeds():
    blocks = _blocks()
    picks = {expand(f"{C}Cat", blocks, rng(s)) for s in range(1000)}
    assert "alpha" not in picks
    assert picks == {"bravo", "charlie", "delta"}


def test_equal_weight_active_pool_uses_choice():
    # Equal-weights rule applies to the remaining active pool.
    blocks = {n: {"category": "Cat", "text": n} for n in ["delta", "alpha", "charlie", "bravo"]}
    blocks["alpha"]["active"] = False
    pool = ["bravo", "charlie", "delta"]
    for s in range(1000):
        assert expand(f"{C}Cat", blocks, rng(s)) == random.Random(s).choice(pool)


def test_direct_call_of_inactive_block_still_expands():
    blocks = _blocks()
    assert expand(f"x, {B}alpha, y", blocks, rng()) == "x, alpha, y"
    assert expand(f"{B}ghost1", blocks, rng()) == "ghost1"


def test_nested_direct_call_of_inactive_block_expands():
    blocks = dict(_blocks(), wrap={"category": "W", "text": f"w, {B}alpha"})
    assert expand(f"{B}wrap", blocks, rng()) == "w, alpha"


def test_old_json_without_active_all_blocks_active():
    names = ["delta", "alpha", "charlie", "bravo"]
    blocks = {n: {"category": "Cat", "text": n} for n in names}
    pool = sorted(names)
    assert chances(blocks, "Cat") == {n: 0.25 for n in pool}
    for s in range(1000):
        assert expand(f"{C}Cat", blocks, rng(s)) == random.Random(s).choice(pool)
    assert find_all_inactive(f"{C}Cat", blocks) == []


def test_broken_active_value_stays_in_pool():
    names = ["delta", "alpha", "charlie", "bravo"]
    blocks = {n: {"category": "Cat", "text": n} for n in names}
    blocks["alpha"]["active"] = "no"
    pool = sorted(names)
    for s in range(200):
        assert expand(f"{C}Cat", blocks, rng(s)) == random.Random(s).choice(pool)


# --- all inactive category ---

def test_all_inactive_category_left_unchanged_and_reported():
    blocks = _blocks()
    for s in range(50):
        out = expand(f"a, {C}Dead, b", blocks, rng(s))
        assert out == f"a, {C}Dead, b"
    assert find_all_inactive(out, blocks) == ["Dead"]


def test_empty_category_is_unknown_not_all_inactive():
    blocks = _blocks()
    out = expand(f"{C}Nope, {C}Dead, {B}nobody", blocks, rng())
    assert find_all_inactive(out, blocks) == ["Dead"]
    unknown, all_inactive = preview_warnings(out, blocks)
    assert all_inactive == ["Dead"]
    assert unknown == [f"{C}Nope", f"{B}nobody"]


def test_all_inactive_found_inside_nested_block():
    blocks = dict(_blocks(), wrap={"category": "W", "text": f"w, {C}Dead"})
    out = expand(f"{B}wrap, {C}Dead", blocks, rng())
    assert out == f"w, {C}Dead, {C}Dead"
    assert preview_warnings(out, blocks) == ([], ["Dead"])


def test_block_token_with_category_name_not_all_inactive():
    # ~Dead is a block call (no block named Dead), not the category.
    blocks = _blocks()
    out = expand(f"{B}Dead", blocks, rng())
    assert preview_warnings(out, blocks) == ([f"{B}Dead"], [])
