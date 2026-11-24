"""weights.in_category: the one category membership rule (design notes section 32 D), and that the
membership users (pool, chance line, all-inactive, browser filter, health references, bulk rename /
size) follow it, including for non-dict / category-less entries."""
import pytest

from pb_core import browser, bulk, health, parser, weights
from pb_core.weights import in_category


def test_member():
    assert in_category({"category": "PChar", "text": "t"}, "PChar") is True


def test_other_category():
    assert in_category({"category": "PChar", "text": "t"}, "PPose") is False


def test_case_sensitive():
    assert in_category({"category": "PChar", "text": "t"}, "pchar") is False


def test_inactive_block_is_still_a_member():
    # Membership ignores Active; the pick pool filters it separately.
    assert in_category({"category": "C", "text": "t", "active": False}, "C") is True


@pytest.mark.parametrize("block", [None, "C", 1, ["C"], True])
def test_non_dict_is_in_no_category(block):
    assert in_category(block, "C") is False


def test_missing_category_matches_only_none():
    # Same as the old inline check `b.get("category") == cat`: kept exactly.
    assert in_category({"text": "t"}, "C") is False
    assert in_category({"text": "t"}, None) is True


def test_empty_dict():
    assert in_category({}, "C") is False


BLOCKS = {
    "a": {"category": "C", "text": "a"},
    "b": {"category": "C", "text": "b", "active": False},
    "c": {"category": "D", "text": "c"},
    "broken": "not a block",
    "nocat": {"text": "x"},
}


def test_category_pool_uses_membership():
    assert weights.category_pool(BLOCKS, "C") == ["a"]
    assert weights.category_pool(BLOCKS, "D") == ["c"]


def test_chance_line_inactive_member():
    assert weights.chance_line(BLOCKS, "b", "C").startswith("Inactive")
    assert weights.chance_line(BLOCKS, "b", "D") == ""


def test_browser_filter_uses_membership():
    assert browser.filter_names(BLOCKS, "", "C") == ["a", "b"]
    assert browser.filter_names(BLOCKS, "", "D") == ["c"]


def test_bulk_size_and_rename_use_membership():
    assert bulk.category_size(BLOCKS, "C") == 2
    new_blocks, moved, _ = bulk.rename_category(BLOCKS, "C", "E")
    assert moved == ["a", "b"]
    assert new_blocks["broken"] == "not a block"
    assert new_blocks["nocat"] == {"text": "x"}


def test_all_inactive_uses_membership():
    blocks = {"x": {"category": "Off", "text": "x", "active": False}, "junk": 5}
    assert parser.find_all_inactive("%Off %None", blocks) == ["Off"]


def test_health_category_refs_use_membership():
    blocks = {
        "user": {"category": "U", "text": "%Off, %Missing"},
        "x": {"category": "Off", "text": "x", "active": False},
        "junk": 5,
    }
    kinds = {(f["kind"], f["block"]) for f in health.report(blocks, set())}
    assert ("all_inactive_ref", "user") in kinds
    assert ("unknown_ref", "user") in kinds


def test_health_self_category_ref():
    blocks = {"me": {"category": "C", "text": "%C"}, "other": {"category": "C", "text": "o"}}
    kinds = {(f["kind"], f["block"]) for f in health.report(blocks, set())}
    assert ("self_category_ref", "me") in kinds
