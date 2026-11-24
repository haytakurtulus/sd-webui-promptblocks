"""Save prompt selection as a block (design notes section 16)."""

import copy

from pb_core import create

BLOCKS = {
    "saber": {"category": "PCharacter", "text": "saber", "weight": 2},
    "loopa": {"category": "Loop", "text": "~loopb"},
    "loopb": {"category": "Loop", "text": "~loopa"},
}


def test_accepts_valid_new_block():
    new, err = create.build_new_block(BLOCKS, "rin", "PCharacter", "rin, red eyes")
    assert err is None
    assert new["rin"] == {"category": "PCharacter", "text": "rin, red eyes"}
    assert new["saber"] == BLOCKS["saber"]
    assert set(new) == {"saber", "loopa", "loopb", "rin"}


def test_stored_shape_is_plain_category_and_text():
    new, _ = create.build_new_block(BLOCKS, "rin", "NewCat", "x")
    assert list(new["rin"].keys()) == ["category", "text"]


def test_inputs_are_stripped():
    new, err = create.build_new_block(BLOCKS, "  rin ", "\tPCharacter \n", "  rin, red eyes \n")
    assert err is None
    assert new["rin"] == {"category": "PCharacter", "text": "rin, red eyes"}


def test_input_dict_not_mutated():
    before = copy.deepcopy(BLOCKS)
    new, err = create.build_new_block(BLOCKS, "rin", "PCharacter", "rin")
    assert err is None
    assert BLOCKS == before
    assert new is not BLOCKS


def test_reference_to_existing_block_is_fine():
    new, err = create.build_new_block(BLOCKS, "scene", "Scene", "running, ~saber")
    assert err is None
    assert new["scene"]["text"] == "running, ~saber"


def test_rejects_invalid_name():
    for bad in ("", "  ", "1abc", "_x", "a-b", "a b", None):
        new, err = create.build_new_block(BLOCKS, bad, "Cat", "text")
        assert new is None
        assert err.startswith("Invalid name")


def test_rejects_invalid_category():
    for bad in ("9Cat", "Ca t", "%Cat"):
        new, err = create.build_new_block(BLOCKS, "rin", bad, "text")
        assert new is None
        assert err == f"Invalid category: `{bad}` (must start with a letter; letters, digits, _)"


def test_rejects_empty_category():
    # Design notes 33 D: an empty Category says so instead of "Invalid category: ``".
    for bad in ("", "   ", None):
        new, err = create.build_new_block(BLOCKS, "rin", bad, "text")
        assert new is None
        assert err == "Category is empty."


def test_rejects_empty_text():
    for bad in ("", "   \n\t", None):
        new, err = create.build_new_block(BLOCKS, "rin", "Cat", bad)
        assert new is None
        assert err == "Text cannot be empty."


def test_rejects_existing_name():
    new, err = create.build_new_block(BLOCKS, " saber ", "PCharacter", "other text")
    assert new is None
    assert "`saber` already exists" in err
    assert "PromptBlocks tab" in err


def test_rejects_text_referencing_a_cycle():
    new, err = create.build_new_block(BLOCKS, "bad", "Cat", "foo, ~loopa")
    assert new is None
    assert err.startswith("Not saved:")


def test_self_reference_is_rejected():
    new, err = create.build_new_block({}, "me", "Cat", "x, ~me")
    assert new is None
    assert err.startswith("Not saved:")
