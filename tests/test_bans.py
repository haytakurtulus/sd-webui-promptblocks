"""Block bans, step 1 (design notes section 38): data field, form box, validation, hints, rename / delete /
health. No parser change: expansion ignores bans in this step."""
import copy
import json
import random

import pytest

from pb_core import bans, bulk, formsave, guard, health, parser, storage, subrows, subs, suggest

BLOCKS = {
    "ninja": {"category": "PChar", "text": "ninja, mask", "bans": ["~happy", "%PEmotion"]},
    "saber": {"category": "PChar", "text": "1girl, saber"},
    "happy": {"category": "PEmotion", "text": "smile"},
    "sad": {"category": "PEmotion", "text": "tears"},
    "scene": {"category": "PScene", "text": "~ninja, %PEmotion, ~happy"},
}


def form(name="ninja", blocks=BLOCKS):
    return subrows.form_values(subrows.block_form(blocks, name), with_chance=True)


def blank():
    return subrows.form_values(subrows.blank_form(), with_chance=True)


def put(values, **fields):
    values = list(values)
    for k, v in fields.items():
        values[subrows.FORM_FIELDS.index(k)] = v
    return values


def of_kind(findings, kind):
    return [f for f in findings if f["kind"] == kind]


# ---- data field ----

def test_block_bans_normalises_stored_values():
    assert bans.block_bans({"bans": ["~happy", " %PEmotion ", "~happy", "happy", 3, "~9x", "%", "~a.b"]}) == \
        ["~happy", "%PEmotion"]
    assert bans.block_bans({}) == []
    assert bans.block_bans({"bans": "~happy"}) == []
    assert bans.block_bans(None) == []


def test_parse_text_valid_order_duplicates_blank_items():
    assert bans.parse_text("~happy, %PEmotion") == (["~happy", "%PEmotion"], None)
    assert bans.parse_text(" %PEmotion ,~happy,, ~happy , ") == (["%PEmotion", "~happy"], None)
    assert bans.parse_text("") == ([], None)
    assert bans.parse_text(None) == ([], None)


@pytest.mark.parametrize("token", ["happy", "~9x", "%", "~", "~happy.sub", "~happy*slot", "~a ~b", "#x"])
def test_parse_text_invalid_token(token):
    result, err = bans.parse_text(f"~ok, {token}")
    assert result is None
    assert f"`{token}`" in err and "not a valid ban" in err
    assert "~name" in err and "%Category" in err


def test_set_block_bans_omits_empty():
    b = {"category": "C", "text": "t", "bans": ["~x"]}
    assert "bans" not in bans.set_block_bans(b, [])
    assert b["bans"] == ["~x"]  # input unchanged
    assert bans.set_block_bans({"text": "t"}, ["~a", "~a", "bad"]) == {"text": "t", "bans": ["~a"]}


# ---- acceptance 1: round trip through the form, old JSON shape kept ----

def test_form_round_trip():
    f = subrows.block_form(BLOCKS, "ninja")
    assert f["bans"] == "~happy, %PEmotion"
    assert subrows.blank_form()["bans"] == ""
    plan = formsave.plan_form_save(BLOCKS, form(), "ninja")
    assert plan["error"] is None
    assert plan["blocks"]["ninja"]["bans"] == ["~happy", "%PEmotion"]
    v = put(form(), bans=" %PEmotion,~happy, ~happy,")
    plan = formsave.plan_form_save(BLOCKS, v, "ninja")
    assert plan["blocks"]["ninja"]["bans"] == ["%PEmotion", "~happy"]  # written order, no duplicates
    assert subrows.block_form(plan["blocks"], "ninja")["bans"] == "%PEmotion, ~happy"


def test_empty_bans_removes_key_and_keeps_old_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_FILE", str(tmp_path / "data" / "blocks.json"))
    plan = formsave.plan_form_save(BLOCKS, put(form(), bans="  "), "ninja")
    assert "bans" not in plan["blocks"]["ninja"]
    # A block without bans: saving its unchanged form gives exactly the stored dict (same JSON bytes).
    plan = formsave.plan_form_save(BLOCKS, form("saber"), "saber")
    assert plan["blocks"]["saber"] == BLOCKS["saber"]
    storage.save_blocks(BLOCKS)
    before = (tmp_path / "data" / "blocks.json").read_bytes()
    storage.save_blocks(plan["blocks"])
    assert (tmp_path / "data" / "blocks.json").read_bytes() == before
    assert b'"bans"' in before and before.count(b'"bans"') == 1  # only ninja has the key


def test_old_file_loads_unchanged(tmp_path, monkeypatch):
    path = tmp_path / "blocks.json"
    data = {"version": 1, "blocks": {"saber": {"category": "PChar", "text": "1girl"}}}
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(storage, "DATA_FILE", str(path))
    blocks = storage.load_blocks()
    assert blocks == data["blocks"]
    assert bans.block_bans(blocks["saber"]) == []
    assert subrows.block_form(blocks, "saber")["bans"] == ""


def test_modified_detection():
    v = form()
    assert not guard.is_modified(BLOCKS, "ninja", v)
    assert not guard.is_modified(BLOCKS, "ninja", put(v, bans="~happy,%PEmotion, ~happy"))  # same normalised
    assert guard.is_modified(BLOCKS, "ninja", put(v, bans="%PEmotion, ~happy"))  # order is saved
    assert guard.is_modified(BLOCKS, "ninja", put(v, bans=""))
    assert guard.is_modified(BLOCKS, "ninja", put(v, bans="~happy, %PEmotion, bad"))
    assert not guard.is_modified(BLOCKS, None, blank())
    assert guard.is_modified(BLOCKS, None, put(blank(), bans="~x"))


def test_duplicate_copies_bans():
    # Duplicate keeps the form; saving it under the new name creates the copy with the same bans.
    v = put(form(), name=subrows.duplicate_name("ninja", BLOCKS))
    plan = formsave.plan_form_save(BLOCKS, v, None)
    assert plan["error"] is None
    assert plan["blocks"]["ninja_copy"]["bans"] == ["~happy", "%PEmotion"]
    assert plan["blocks"]["ninja"] == BLOCKS["ninja"]


# ---- acceptance 2: invalid token -> Save error ----

@pytest.mark.parametrize("token", ["happy", "~9x", "%"])
def test_save_error_for_invalid_token(token):
    plan = formsave.plan_form_save(BLOCKS, put(form(), bans=f"~happy, {token}"), "ninja")
    assert plan["blocks"] is None
    assert plan["error"].startswith("Not saved: Bans:")
    assert f"`{token}`" in plan["error"]
    # Auto-save (block switch) refuses with the same error.
    plan = formsave.plan_form_save(BLOCKS, put(form(), bans=token), "ninja", confirm=False)
    assert plan["error"] and "Bans" in plan["error"]


# ---- acceptance 3: hint line ----

def test_hint_unknown_name_and_category():
    h = bans.hint("ninja", "PChar", "~nobody, %Nothing, ~saber", BLOCKS)
    assert "`~nobody`: no block named `nobody`" in h
    assert "`%Nothing`: no block has category `Nothing`" in h
    assert "saber" not in h


def test_hint_mutual_ban():
    blocks = copy.deepcopy(BLOCKS)
    blocks["happy"]["bans"] = ["~ninja"]
    h = bans.hint("ninja", "PChar", "~happy", blocks)
    assert "`~happy` bans this block too" in h and "mutual" in h
    # Mutual through the category on the other side.
    blocks["happy"]["bans"] = ["%PChar"]
    assert "`~happy` bans this block too" in bans.hint("ninja", "PChar", "%PEmotion", blocks)
    # One-sided: no mutual note.
    assert "mutual" not in bans.hint("ninja", "PChar", "~happy", BLOCKS)


def test_hint_own_category_and_self():
    h = bans.hint("ninja", "PChar", "%PChar", BLOCKS)
    assert "`%PChar` is this block's own category" in h
    assert "this block itself" in bans.hint("ninja", "PChar", "~ninja", BLOCKS)


def test_hint_parse_error_and_nothing_to_say():
    assert bans.hint("ninja", "PChar", "happy", BLOCKS).startswith("⚠ Bans: `happy`")
    assert bans.hint("ninja", "PChar", "", BLOCKS) == ""
    assert bans.hint("ninja", "PChar", "~saber, %PEmotion", BLOCKS) == ""


def test_hint_leaves_empty_pool_to_health():
    assert bans.hint("x", "PChar", "~happy, ~sad", BLOCKS) == ""
    assert [k for k, _ in bans.problems(BLOCKS, "x", "PChar", ["~happy", "~sad"])] == ["empty_pool"]


# ---- acceptance 4: rename block / category rewrite bans ----

def test_rename_block_rewrites_bans():
    blocks = copy.deepcopy(BLOCKS)
    blocks["joy"] = blocks.pop("happy")
    new, updated = subs.rename_block_refs(blocks, "happy", "joy")
    assert new["ninja"]["bans"] == ["~joy", "%PEmotion"]
    assert "ninja" in updated and "scene" in updated
    assert new["scene"]["text"] == "~ninja, %PEmotion, ~joy"
    # A longer name that only starts with "happy" is another block.
    blocks["k2"] = {"category": "C", "text": "t", "bans": ["~happyish"]}
    new, _ = subs.rename_block_refs(blocks, "happy", "joy")
    assert new["k2"]["bans"] == ["~happyish"]
    assert blocks["ninja"]["bans"] == ["~happy", "%PEmotion"]  # input unchanged


def test_rename_category_rewrites_bans():
    new, moved, rewritten = bulk.rename_category(BLOCKS, "PEmotion", "PMood")
    assert new["ninja"]["bans"] == ["~happy", "%PMood"]
    assert "ninja" in rewritten
    assert sorted(moved) == ["happy", "sad"]


def test_category_merge_drops_duplicate_ban():
    blocks = copy.deepcopy(BLOCKS)
    blocks["ninja"]["bans"] = ["%PEmotion", "~saber", "%PScene"]
    new, _, _ = bulk.rename_category(blocks, "PEmotion", "PScene")
    assert new["ninja"]["bans"] == ["%PScene", "~saber"]


def test_rename_sub_refs_leaves_bans():
    new, updated = subrows.rename_sub_refs_many(BLOCKS, "happy", {"a": "b"})
    assert new["ninja"]["bans"] == ["~happy", "%PEmotion"] and updated == []


# ---- acceptance 5: delete warning ----

def test_delete_warning_mentions_bans():
    w = suggest.delete_warnings(BLOCKS, "happy")
    assert "`~happy` is used by: scene" in w[0]
    ban_lines = [x for x in w if "bans" in x]
    assert len(ban_lines) == 1 and "`~happy` is listed in the bans of: ninja" in ban_lines[0]
    assert "bans of: ninja" in suggest.delete_confirm_message(BLOCKS, "happy")


def test_delete_warning_ban_only_and_category():
    blocks = copy.deepcopy(BLOCKS)
    blocks["scene"]["text"] = "plain"
    del blocks["sad"]
    w = suggest.delete_warnings(blocks, "happy")
    assert any("`~happy` is listed in the bans of: ninja" in x for x in w)
    assert any("last block in `%PEmotion`" in x and "bans of: ninja" in x for x in w)
    assert not any("is used by" in x for x in w)
    # Not the last block of the category: no category ban line.
    assert not any("last block" in x for x in suggest.delete_warnings(BLOCKS, "sad"))
    # The deleted block's own bans are no warning.
    assert not any("bans" in x for x in suggest.delete_warnings(BLOCKS, "ninja"))


# ---- acceptance 6: health report ----

def test_health_ban_findings():
    blocks = copy.deepcopy(BLOCKS)
    blocks["ninja"]["bans"] = ["~happy", "~nobody", "%Nothing", "%PChar", "~ninja"]
    blocks["happy"]["bans"] = ["%PChar"]          # mutual with ninja
    blocks["picky"] = {"category": "PX", "text": "p", "bans": ["~happy", "~sad"]}  # empties %PEmotion
    blocks["broken"] = {"category": "PX", "text": "b", "bans": ["~ok_name", "bad", 7, "~ok_name"]}
    blocks["broken2"] = {"category": "PX", "text": "b", "bans": "~happy"}
    blocks["ok_name"] = {"category": "PX", "text": "o"}
    found = health.report(blocks)

    unknown = [f["detail"] for f in of_kind(found, "unknown_ref") if f["block"] == "ninja"]
    assert any("Bans: `~nobody`" in d for d in unknown)
    assert any("Bans: `%Nothing`" in d for d in unknown)

    own = [(f["block"], f["detail"]) for f in of_kind(found, "self_ban")]
    assert any(b == "ninja" and "`%PChar` is this block's own category" in d for b, d in own)
    assert any(b == "ninja" and "this block itself" in d for b, d in own)

    mutual = of_kind(found, "mutual_ban")
    assert [(f["block"]) for f in mutual] == ["happy"]  # once per pair, at the name that sorts first
    assert "`~happy` and `~ninja` ban each other" in mutual[0]["detail"]

    pool = of_kind(found, "ban_empty_pool")
    assert [f["block"] for f in pool] == ["picky"] and "`%PEmotion`" in pool[0]["detail"]

    ignored = [f["detail"] for f in of_kind(found, "ignored_value")]
    assert any("ban entry #2" in d and "bad" in d for d in ignored)
    assert any("ban entry #3" in d and "not text" in d for d in ignored)
    assert any("ban entry #4" in d and "duplicate" in d for d in ignored)
    assert any("bans" in d and "is not a list" in d for d in ignored)

    text = health.format_report(found, len(blocks))
    for kind in ("self_ban", "mutual_ban", "ban_empty_pool"):
        assert dict(health.KINDS)[kind] in text


def test_health_clean_bans_no_findings():
    assert health.report(BLOCKS) == []


def test_banned_category_is_not_an_emptied_pool():
    blocks = copy.deepcopy(BLOCKS)
    blocks["ninja"]["bans"] = ["~happy", "~sad", "%PEmotion"]
    assert of_kind(health.report(blocks), "ban_empty_pool") == []


# ---- step 1 acceptance 7, kept for apply_bans=False (step 2 applies bans by default: test_bans_expand.py) ----

def test_expansion_without_apply_bans_ignores_bans():
    plain = copy.deepcopy(BLOCKS)
    for b in plain.values():
        b.pop("bans", None)
    for seed in range(20):
        for prompt in ("~ninja, %PEmotion", "~scene", "%PChar, ~happy"):
            a = parser.expand(prompt, BLOCKS, random.Random(seed), apply_bans=False)
            b = parser.expand(prompt, plain, random.Random(seed))
            assert a == b
    assert "smile" in parser.expand("~ninja, ~happy", BLOCKS, random.Random(0), apply_bans=False)
    assert "smile" not in parser.expand("~ninja, ~happy", BLOCKS, random.Random(0))
