import math

import pytest

from pb_core.weights import block_weight, validate_weight, chances, chance_line


@pytest.mark.parametrize("value", [0, -1, "x", None, True, False, math.nan, math.inf, -math.inf, 1000, [2]])
def test_invalid_stored_weight_is_one(value):
    assert block_weight({"category": "C", "text": "t", "weight": value}) == 1


def test_missing_weight_is_one():
    assert block_weight({"category": "C", "text": "t"}) == 1


@pytest.mark.parametrize("value", [0.5, 2, 100, 7.25])
def test_valid_stored_weight(value):
    assert block_weight({"category": "C", "text": "t", "weight": value}) == value


@pytest.mark.parametrize("value", [0.5, 1, 2, 100, 2.0])
def test_validate_accepts(value):
    w, err = validate_weight(value)
    assert err is None
    assert w == value


def test_validate_integral_float_becomes_int():
    assert validate_weight(2.0) == (2, None)
    assert isinstance(validate_weight(2.0)[0], int)


@pytest.mark.parametrize("value", [0, 0.0, -1, -0.5, 100.01, 1000, None, math.nan, math.inf, -math.inf,
                                   "2", "x", "", True, False])
def test_validate_rejects(value):
    w, err = validate_weight(value)
    assert w is None
    assert isinstance(err, str) and err


def test_chances_2_1_1():
    blocks = {
        "a": {"category": "C", "text": "a", "weight": 2},
        "b": {"category": "C", "text": "b"},
        "c": {"category": "C", "text": "c", "weight": 1},
        "other": {"category": "D", "text": "d", "weight": 50},
    }
    assert chances(blocks, "C") == {"a": 0.5, "b": 0.25, "c": 0.25}


def test_chances_sum_to_one_with_invalid_weights():
    blocks = {
        "a": {"category": "C", "text": "a", "weight": 0.5},
        "b": {"category": "C", "text": "b", "weight": "broken"},
        "c": {"category": "C", "text": "c", "weight": 3},
    }
    assert math.isclose(sum(chances(blocks, "C").values()), 1.0)


def test_chances_empty_category():
    assert chances({"a": {"category": "C", "text": "a"}}, "Nope") == {}
    assert chances({}, "C") == {}


def test_chance_line():
    blocks = {
        "saber": {"category": "PCharacter", "text": "a", "weight": 2},
        "rin":   {"category": "PCharacter", "text": "b"},
        "sakura": {"category": "PCharacter", "text": "c", "weight": 2},
    }
    assert chance_line(blocks, "saber", "PCharacter") == "Chance in `%PCharacter`: 40% (weight 2 of 5)"
    assert chance_line(blocks, "saber", "Nope") == ""
