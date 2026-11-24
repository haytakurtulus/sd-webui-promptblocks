from pb_core.suggest import category_counts, category_hint

BLOCKS = {
    "saber": {"category": "PCharacter", "text": "a"},
    "rin":   {"category": "PCharacter", "text": "b"},
    "run":   {"category": "PPose",      "text": "c"},
}


def test_counts():
    assert category_counts(BLOCKS) == {"PCharacter": 2, "PPose": 1}


def test_existing():
    assert category_hint("PCharacter", BLOCKS) == "Existing category (2 blocks)."


def test_typo_suggests():
    assert "Did you mean: `PCharacter`" in category_hint("PCharcter", BLOCKS)


def test_wrong_case_suggests():
    assert "Did you mean: `PCharacter`" in category_hint("pcharacter", BLOCKS)


def test_really_new():
    assert category_hint("Background", BLOCKS) == "New category `Background`."


def test_empty():
    assert category_hint("", BLOCKS) == ""
    assert category_hint(None, BLOCKS) == ""