import random
import pytest
from pb_core.parser import expand, BlockCycleError
from pb_core.parser import BLOCK_SYMBOL as B, CATEGORY_SYMBOL as C
from pb_core.parser import is_valid_name
from pb_core.parser import find_unknown
from pb_core.parser import references, rename_token


BLOCKS = {
    "saber":    {"category": "PCharacter", "text": "1girl, saber (fate)"},
    "rin":      {"category": "PCharacter", "text": "1girl, tohsaka rin"},
    "runscene": {"category": "PPose",      "text": f"running, {B}saber"},
    "loop_a":   {"category": "X",          "text": f"{B}loop_b"},
    "loop_b":   {"category": "X",          "text": f"{B}loop_a"},
}

def rng(seed=1):
    return random.Random(seed)

def test_direct_block():
    assert expand(f"test {B}saber, red", BLOCKS, rng()) == "test 1girl, saber (fate), red"

def test_unknown_block_untouched():
    assert expand(f"{B}nobody", BLOCKS, rng()) == f"{B}nobody"

def test_category_picks_member():
    assert expand(f"{C}PCharacter", BLOCKS, rng()) in ("1girl, saber (fate)", "1girl, tohsaka rin")

def test_same_seed_same_result():
    assert expand(f"{C}PCharacter", BLOCKS, rng(42)) == expand(f"{C}PCharacter", BLOCKS, rng(42))

def test_empty_category_untouched():
    assert expand(f"{C}Nothing", BLOCKS, rng()) == f"{C}Nothing"

def test_nested_block():
    assert expand(f"{B}runscene", BLOCKS, rng()) == "running, 1girl, saber (fate)"

def test_cycle_raises():
    with pytest.raises(BlockCycleError):
        expand(f"{B}loop_a", BLOCKS, rng())

def test_symbol_without_name_untouched():
    assert expand(f"{B}_{B}, smile", BLOCKS, rng()) == f"{B}_{B}, smile"

def test_is_valid_name():
    assert is_valid_name("saber")
    assert is_valid_name("PCharacter_2")
    assert not is_valid_name("1abc")
    assert not is_valid_name("saber!")
    assert not is_valid_name("")

def test_different_seeds_can_pick_different_blocks():
    results = {expand(f"{C}PCharacter", BLOCKS, rng(s)) for s in range(50)}
    assert results == {"1girl, saber (fate)", "1girl, tohsaka rin"}

def test_find_unknown_top_level():
    out = expand(f"{B}saber, {B}sabr, {C}Nope", BLOCKS, rng())
    assert find_unknown(out) == [f"{B}sabr", f"{C}Nope"]

def test_find_unknown_nested():
    blocks = dict(BLOCKS, broken={"category": "X", "text": f"ok, {B}missing"})
    out = expand(f"{B}broken", blocks, rng())
    assert find_unknown(out) == [f"{B}missing"]

def test_find_unknown_none():
    assert find_unknown(expand(f"{B}runscene", BLOCKS, rng())) == []

def test_references_exact_token_only():
    assert references(f"x, {B}saber, y", B, "saber")
    assert not references(f"{B}saber_fate", B, "saber")
    assert not references(f"{C}saber", B, "saber")

def test_rename_token():
    text = f"{B}saber, {B}saber_fate, {C}saber, {B}saber"
    assert rename_token(text, B, "saber", "arturia") == f"{B}arturia, {B}saber_fate, {C}saber, {B}arturia"


# --- E2a: block weights ---

def _cat_blocks(weights_by_name):
    # Text equals the name, so the expansion result is the picked name. Insertion order is deliberately
    # unsorted to check that the pool is sorted by name.
    blocks = {}
    for n, w in weights_by_name.items():
        blocks[n] = {"category": "Cat", "text": n}
        if w is not None:
            blocks[n]["weight"] = w
    return blocks

_NAMES = ["delta", "alpha", "charlie", "bravo"]

def test_unweighted_picks_match_old_choice():
    blocks = _cat_blocks({n: None for n in _NAMES})
    pool = sorted(_NAMES)
    for s in range(1000):
        assert expand(f"{C}Cat", blocks, rng(s)) == random.Random(s).choice(pool)

def test_same_non_one_weight_matches_unweighted():
    blocks = _cat_blocks({n: 3 for n in _NAMES})
    pool = sorted(_NAMES)
    for s in range(1000):
        assert expand(f"{C}Cat", blocks, rng(s)) == random.Random(s).choice(pool)

def test_mixed_missing_and_explicit_one_matches_unweighted():
    blocks = _cat_blocks({"delta": 1, "alpha": None, "charlie": 1.0, "bravo": None})
    pool = sorted(_NAMES)
    for s in range(1000):
        assert expand(f"{C}Cat", blocks, rng(s)) == random.Random(s).choice(pool)

def test_weight_3_vs_1_share():
    blocks = _cat_blocks({"light": 1, "heavy": 3})
    picks = [expand(f"{C}Cat", blocks, rng(s)) for s in range(4000)]
    share = picks.count("heavy") / len(picks)
    assert 0.70 <= share <= 0.80

@pytest.mark.parametrize("bad", [0, -1, "x", None, True, float("nan"), float("inf"), 1000])
def test_invalid_stored_weight_behaves_as_one(bad):
    blocks = _cat_blocks({n: None for n in _NAMES})
    blocks["alpha"]["weight"] = bad  # explicit key, even for None
    pool = sorted(_NAMES)
    for s in range(1000):
        assert expand(f"{C}Cat", blocks, rng(s)) == random.Random(s).choice(pool)

def test_direct_block_ignores_weight():
    for w in (None, 0.5, 3, 100, 0, "x"):
        blocks = dict(BLOCKS)
        blocks["saber"] = dict(BLOCKS["saber"])
        if w is not None:
            blocks["saber"]["weight"] = w
        for s in range(20):
            assert expand(f"test {B}saber, {B}runscene", blocks, rng(s)) == \
                "test 1girl, saber (fate), running, 1girl, saber (fate)"