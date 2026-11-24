from pb_core.suggest import delete_warnings, last_active_category_users


def _blocks():
    return {
        "a1":   {"category": "Cat", "text": "a1"},
        "a2":   {"category": "Cat", "text": "a2"},
        "off1": {"category": "Cat", "text": "off1", "active": False},
        "user": {"category": "Scene", "text": "running, %Cat"},
        "solo": {"category": "Lonely", "text": "solo"},
    }


def _last_block_warning(warnings):
    return [w for w in warnings if "last" in w]


def test_last_active_with_inactive_remaining_warns():
    blocks = _blocks()
    del blocks["a2"]  # a1 is now the last active block; off1 (inactive) remains
    assert last_active_category_users(blocks, "a1") == ["user"]
    w = _last_block_warning(delete_warnings(blocks, "a1"))
    assert len(w) == 1
    assert "`%Cat`" in w[0] and "user" in w[0]


def test_last_block_at_all_warns():
    blocks = {
        "only": {"category": "Cat", "text": "only"},
        "user": {"category": "Scene", "text": "%Cat"},
    }
    assert last_active_category_users(blocks, "only") == ["user"]
    assert len(_last_block_warning(delete_warnings(blocks, "only"))) == 1


def test_another_active_remains_no_warning():
    blocks = _blocks()
    assert last_active_category_users(blocks, "a1") == []
    assert delete_warnings(blocks, "a1") == []


def test_deleting_inactive_block_no_last_block_warning():
    blocks = _blocks()
    del blocks["a2"]
    del blocks["a1"]  # off1 is the only block left, and it is inactive
    assert last_active_category_users(blocks, "off1") == []
    assert _last_block_warning(delete_warnings(blocks, "off1")) == []
    # Also when active blocks still exist.
    assert last_active_category_users(_blocks(), "off1") == []


def test_unreferenced_category_no_warning():
    blocks = _blocks()
    assert last_active_category_users(blocks, "solo") == []
    assert delete_warnings(blocks, "solo") == []


def test_self_reference_does_not_count():
    blocks = {"loop": {"category": "Cat", "text": "x, %Cat"}}
    assert last_active_category_users(blocks, "loop") == []


def test_block_reference_warning_kept():
    blocks = _blocks()
    blocks["fan"] = {"category": "Scene", "text": "~a1, smiling"}
    w = delete_warnings(blocks, "a1")
    assert w == ["`~a1` is used by: fan"]


def test_both_warnings():
    blocks = {
        "only": {"category": "Cat", "text": "only"},
        "off": {"category": "Cat", "text": "off", "active": False},
        "user": {"category": "Scene", "text": "%Cat, ~only"},
    }
    w = delete_warnings(blocks, "only")
    assert len(w) == 2
    assert w[0] == "`~only` is used by: user"
    assert "last active block in `%Cat`" in w[1]
