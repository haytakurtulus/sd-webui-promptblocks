import math
import random

import pytest

from pb_core.seeds import block_seeds, normalize_block_seed


def test_fixed_seed_gives_seed_plus_index():
    base, seeds = block_seeds(1234, 4)
    assert base == 1234
    assert seeds == [1234, 1235, 1236, 1237]


def test_fixed_seed_same_input_same_output():
    assert block_seeds(42, 3) == block_seeds(42, 3)


def test_zero_is_a_fixed_seed():
    assert block_seeds(0, 2) == (0, [0, 1])


def test_integral_float_is_fixed():
    assert block_seeds(7.0, 2) == (7, [7, 8])


def test_minus_one_resolves_to_one_random_base():
    base, seeds = block_seeds(-1, 5, rng=random.Random(99))
    expected = random.Random(99).randrange(2**32)
    assert base == expected
    assert seeds == [expected + i for i in range(5)]


def test_minus_one_same_rng_state_same_output():
    assert block_seeds(-1, 3, rng=random.Random(5)) == block_seeds(-1, 3, rng=random.Random(5))


def test_minus_one_draws_once():
    calls = []

    class FakeRng:
        def randrange(self, n):
            calls.append(n)
            return 500

    assert block_seeds(-1, 4, rng=FakeRng()) == (500, [500, 501, 502, 503])
    assert len(calls) == 1


def test_minus_one_changes_between_calls():
    rng = random.Random(1)
    bases = {block_seeds(-1, 1, rng=rng)[0] for _ in range(20)}
    assert len(bases) > 1


def test_minus_one_base_is_never_negative():
    rng = random.Random(3)
    for _ in range(200):
        base, _ = block_seeds(-1, 1, rng=rng)
        assert base >= 0


@pytest.mark.parametrize("value", [-1, -5, None, "12", "x", True, False, math.nan, math.inf, [3]])
def test_random_values(value):
    assert normalize_block_seed(value) is None
    base, seeds = block_seeds(value, 2, rng=random.Random(0))
    assert base == random.Random(0).randrange(2**32)
    assert seeds == [base, base + 1]


def test_fixed_seed_ignores_rng():
    class Boom:
        def randrange(self, n):
            raise AssertionError("must not draw for a fixed seed")

    assert block_seeds(10, 2, rng=Boom()) == (10, [10, 11])


def test_zero_images():
    assert block_seeds(3, 0) == (3, [])
