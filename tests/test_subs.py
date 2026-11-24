import json
import random
import re

import pytest

from pb_core import parser, storage, subs, suggest
from pb_core.parser import (BLOCK_SYMBOL as B, CATEGORY_SYMBOL as C, BlockCycleError, expand,
                            find_unknown, preview_warnings, references, rename_sub_tokens,
                            rename_token, sub_references)


def rng(seed=1):
    return random.Random(seed)


def sub(name, text, mode=None, slot=None, **extra):
    d = {"name": name, "text": text}
    if mode is not None:
        d["mode"] = mode
    if slot is not None:
        d["slot"] = slot
    d.update(extra)
    return d


def saber_blocks(mode="include", active=True):
    blocks = {
        "saber": {"category": "PCharacter", "text": "1girl, saber",
                  "subs": [sub("outfit", "armor", mode)]},
    }
    if not active:
        blocks["saber"]["active"] = False
    return blocks


# --- old behaviour --------------------------------------------------------------------------------

_OLD_TOKEN = re.compile("(~|%)(" + parser.NAME_PATTERN + ")")


def old_expand(prompt, blocks, r, depth=0):
    # Copy of expand() before sub-blocks existed (with weights and active), as the reference.
    if depth > parser.MAX_DEPTH:
        raise BlockCycleError("deep")

    def repl(m):
        symbol, name = m.group(1), m.group(2)
        if symbol == "~":
            block = blocks.get(name)
        else:
            pool = parser.category_pool(blocks, name)
            block = blocks[parser._pick(pool, blocks, r)] if pool else None
        if block is None:
            return m.group(0)
        return old_expand(block["text"], blocks, r, depth + 1)

    return _OLD_TOKEN.sub(repl, prompt)


OLD_BLOCKS = {
    "saber": {"category": "PChar", "text": "1girl, saber, %Hair"},
    "rin": {"category": "PChar", "text": "1girl, rin", "weight": 2},
    "sakura": {"category": "PChar", "text": "1girl, sakura"},
    "off": {"category": "PChar", "text": "off", "active": False},
    "blonde": {"category": "Hair", "text": "blonde hair"},
    "black": {"category": "Hair", "text": "black hair"},
    "red": {"category": "Hair", "text": "red hair", "weight": 0.5},
    "run": {"category": "Pose", "text": "running, %PChar, ~saber"},
    "sit": {"category": "Pose", "text": "sitting"},
}
# "~saber.x" is deliberately absent: a dot followed by a letter is now a sub-block token (see
# test_dot_letter_after_block_is_now_sub_token), the one intended difference to the old behaviour.
OLD_PROMPT = "masterpiece, %Pose, %PChar, ~run, ~saber. ~nope, %Missing, ~saber.1x, %Hair.x end"


def test_old_json_loads_and_expands_as_before(tmp_path, monkeypatch):
    path = tmp_path / "blocks.json"
    path.write_text(json.dumps({"version": 1, "blocks": OLD_BLOCKS}), encoding="utf-8")
    monkeypatch.setattr(storage, "DATA_FILE", str(path))
    blocks = storage.load_blocks()
    for s in range(1000):
        r_new, r_old = rng(s), rng(s)
        assert expand(OLD_PROMPT, blocks, r_new) == old_expand(OLD_PROMPT, blocks, r_old)
        # Same RNG consumption: the next draw is identical.
        assert r_new.random() == r_old.random()


@pytest.mark.parametrize("subs_value", [[], [sub("a", "x", "exclude"), sub("b", "y", "exclude")]])
def test_block_without_selected_random_subs_consumes_no_extra_rng(subs_value):
    blocks = {k: dict(v) for k, v in OLD_BLOCKS.items()}
    for b in blocks.values():
        b["subs"] = subs_value
    for s in range(200):
        r_new, r_old = rng(s), rng(s)
        assert expand(OLD_PROMPT, blocks, r_new) == old_expand(OLD_PROMPT, blocks, r_old)
        assert r_new.random() == r_old.random()


def test_dot_letter_after_block_is_now_sub_token():
    # Intended change: before sub-blocks, "~saber.x" expanded saber and kept ".x"; now it is the
    # (unknown) sub-block token ~saber.x and is left untouched as a whole.
    assert old_expand("~saber.x", OLD_BLOCKS, rng()).startswith("1girl, saber")
    assert expand("~saber.x", OLD_BLOCKS, rng()) == "~saber.x"


# --- modes ----------------------------------------------------------------------------------------

def test_include_always_added():
    blocks = saber_blocks("include")
    for s in range(100):
        assert expand("~saber", blocks, rng(s)) == "1girl, saber, armor"


def test_missing_mode_is_include():
    blocks = {"saber": {"category": "P", "text": "1girl", "subs": [{"name": "outfit", "text": "armor"}]}}
    assert expand("~saber", blocks, rng()) == "1girl, armor"


def test_exclude_never_added():
    blocks = saber_blocks("exclude")
    for s in range(100):
        assert expand("~saber", blocks, rng(s)) == "1girl, saber"


def test_random_sometimes_added():
    blocks = saber_blocks("random")
    results = {expand("~saber", blocks, rng(s)) for s in range(200)}
    assert results == {"1girl, saber", "1girl, saber, armor"}


def test_random_is_about_half():
    blocks = saber_blocks("random")
    hits = sum(expand("~saber", blocks, rng(s)) == "1girl, saber, armor" for s in range(2000))
    assert 0.45 <= hits / 2000 <= 0.55


def test_random_draw_is_rng_random_below_half():
    blocks = saber_blocks("random")
    for s in range(200):
        expected = "1girl, saber, armor" if random.Random(s).random() < 0.5 else "1girl, saber"
        assert expand("~saber", blocks, rng(s)) == expected


def test_independent_random_draws_all_combinations():
    blocks = {"p": {"category": "P", "text": "p", "subs": [sub("a", "A", "random"), sub("b", "B", "random")]}}
    results = {expand("~p", blocks, rng(s)) for s in range(300)}
    assert results == {"p", "p, A", "p, B", "p, A, B"}


def test_order_is_list_order():
    blocks = {"p": {"category": "P", "text": "p",
                    "subs": [sub("z", "Z"), sub("a", "A"), sub("m", "M", "exclude"), sub("k", "K")]}}
    assert expand("~p", blocks, rng()) == "p, Z, A, K"


def test_modes_apply_via_category_pick():
    blocks = {
        "saber": {"category": "PChar", "text": "saber",
                  "subs": [sub("inc", "INC"), sub("exc", "EXC", "exclude"), sub("rnd", "RND", "random")]},
        "rin": {"category": "PChar", "text": "rin"},
    }
    results = {expand("%PChar", blocks, rng(s)) for s in range(400)}
    assert results == {"rin", "saber, INC", "saber, INC, RND"}


def test_rng_order_parent_text_first_then_subs():
    # Parent text contains a %Category pick; the random sub draws after it.
    blocks = {
        "p": {"category": "P", "text": "%Hair", "subs": [sub("r", "R", "random")]},
        "h1": {"category": "Hair", "text": "h1"},
        "h2": {"category": "Hair", "text": "h2"},
    }
    for s in range(200):
        r = random.Random(s)
        hair = r.choice(["h1", "h2"])
        expected = hair + (", R" if r.random() < 0.5 else "")
        assert expand("~p", blocks, rng(s)) == expected


def test_selected_random_sub_expanded_before_next_draw():
    # Sub text with a %Category pick is expanded right after its draw, before the next sub draws.
    blocks = {
        "p": {"category": "P", "text": "p", "subs": [sub("a", "%Hair", "random"), sub("b", "B", "random")]},
        "h1": {"category": "Hair", "text": "h1"},
        "h2": {"category": "Hair", "text": "h2"},
    }
    for s in range(200):
        r = random.Random(s)
        parts = ["p"]
        if r.random() < 0.5:
            parts.append(r.choice(["h1", "h2"]))
        if r.random() < 0.5:
            parts.append("B")
        assert expand("~p", blocks, rng(s)) == ", ".join(parts)


def test_inactive_parent_not_picked_with_subs():
    blocks = {
        "saber": {"category": "PChar", "text": "saber", "active": False, "subs": [sub("o", "ARMOR")]},
        "rin": {"category": "PChar", "text": "rin"},
    }
    for s in range(200):
        assert expand("%PChar", blocks, rng(s)) == "rin"


def test_empty_parts_not_joined():
    blocks = {"p": {"category": "P", "text": "", "subs": [sub("a", "A")]}}
    assert expand("~p", blocks, rng()) == "A"


# --- direct ~parent.sub ---------------------------------------------------------------------------

@pytest.mark.parametrize("mode", ["include", "exclude", "random"])
def test_direct_sub_gives_only_sub_text(mode):
    blocks = saber_blocks(mode)
    for s in range(50):
        assert expand("x, ~saber.outfit, y", blocks, rng(s)) == "x, armor, y"


def test_direct_sub_works_when_parent_inactive():
    blocks = saber_blocks("exclude", active=False)
    assert expand("~saber.outfit", blocks, rng()) == "armor"


def test_direct_sub_consumes_no_rng():
    blocks = saber_blocks("random")
    r = rng(5)
    expand("~saber.outfit", blocks, r)
    assert r.random() == rng(5).random()


def test_direct_sub_not_traced():
    trace = []
    expand("~saber.outfit", saber_blocks("include"), rng(), trace=trace)
    assert trace == []


def test_saber_dot_is_parent_plus_period():
    blocks = saber_blocks("exclude")
    assert expand("~saber.", blocks, rng()) == "1girl, saber."
    assert expand("~saber.1x", blocks, rng()) == "1girl, saber.1x"
    assert expand("~saber._x", blocks, rng()) == "1girl, saber._x"


def test_sub_token_stops_at_second_dot():
    blocks = saber_blocks("exclude")
    assert expand("~saber.outfit.more", blocks, rng()) == "armor.more"


def test_category_has_no_sub_part():
    blocks = saber_blocks("exclude")
    assert expand("%PCharacter.outfit", blocks, rng()) == "1girl, saber.outfit"


# --- unknown --------------------------------------------------------------------------------------

def test_unknown_sub_untouched_and_reported():
    blocks = saber_blocks()
    out = expand("~saber.otfit, ~nope.outfit, ~saber.", blocks, rng())
    assert out == "~saber.otfit, ~nope.outfit, 1girl, saber, armor."
    assert find_unknown(out) == ["~saber.otfit", "~nope.outfit"]


def test_unknown_inside_sub_text_reported():
    blocks = {"p": {"category": "P", "text": "p", "subs": [sub("a", "~ghost.x, %Nope")]}}
    out = expand("~p", blocks, rng())
    assert find_unknown(out) == ["~ghost.x", "%Nope"]


def test_preview_warnings_with_dotted_tokens():
    blocks = dict(saber_blocks(), off={"category": "Off", "text": "o", "active": False})
    out = expand("~saber.otfit, %Off, %Off.x, ~saber.", blocks, rng())
    unknown, all_inactive = preview_warnings(out, blocks)
    assert unknown == ["~saber.otfit"]
    assert all_inactive == ["Off"]


# --- trace ----------------------------------------------------------------------------------------

def test_trace_records_auto_added_subs():
    blocks = {
        "saber": {"category": "PChar", "text": "saber",
                  "subs": [sub("inc", "INC"), sub("exc", "EXC", "exclude"), sub("rnd", "RND", "random")]},
        "run": {"category": "Pose", "text": "running, ~saber"},
    }
    for s in range(50):
        trace = []
        out = expand("~run", blocks, rng(s), trace=trace)
        expected = [("saber", "inc")] + ([("saber", "rnd")] if "RND" in out else [])
        assert trace == expected


def test_trace_includes_nested_parent_inside_sub_text():
    blocks = {
        "a": {"category": "X", "text": "a", "subs": [sub("s", "~b")]},
        "b": {"category": "X", "text": "b", "subs": [sub("t", "T")]},
    }
    trace = []
    assert expand("~a", blocks, rng(), trace=trace) == "a, b, T"
    assert trace == [("a", "s"), ("b", "t")]


# --- nesting / cycles -----------------------------------------------------------------------------

def test_sub_text_references_expand():
    blocks = {
        "saber": {"category": "PChar", "text": "saber", "subs": [sub("o", "~armor, %Hair")]},
        "armor": {"category": "Outfit", "text": "plate armor"},
        "blonde": {"category": "Hair", "text": "blonde hair"},
    }
    assert expand("~saber", blocks, rng()) == "saber, plate armor, blonde hair"
    assert expand("~saber.o", blocks, rng()) == "plate armor, blonde hair"


def test_cycle_through_sub_text_raises():
    blocks = {
        "a": {"category": "X", "text": "a", "subs": [sub("s", "~b")]},
        "b": {"category": "X", "text": "~a"},
    }
    with pytest.raises(BlockCycleError):
        expand("~a", blocks, rng())
    with pytest.raises(BlockCycleError):
        expand("~a.s", blocks, rng())


def test_self_referencing_sub_raises():
    blocks = {"a": {"category": "X", "text": "a", "subs": [sub("s", "~a.s", "exclude")]}}
    assert expand("~a", blocks, rng()) == "a"
    with pytest.raises(BlockCycleError):
        expand("~a.s", blocks, rng())


def test_sub_text_uses_depth_plus_one():
    # Chain of direct sub calls: 5 levels below the prompt still expand, 6 raise (MAX_DEPTH = 5).
    def chain(n):
        blocks = {}
        for i in range(n):
            nxt = f"~b{i + 1}.s" if i + 1 < n else "end"
            blocks[f"b{i}"] = {"category": "X", "text": "t", "subs": [sub("s", nxt)]}
        return blocks
    assert expand("~b0.s", chain(5), rng()) == "end"
    with pytest.raises(BlockCycleError):
        expand("~b0.s", chain(6), rng())


# --- references / renames -------------------------------------------------------------------------

def test_references_counts_dotted_token():
    assert references("x, ~saber.outfit", B, "saber")
    assert not references("x, ~saber_x.outfit", B, "saber")
    assert not references("%saber.outfit", B, "saber")
    assert references("%Cat.outfit", C, "Cat")


def test_sub_references():
    assert sub_references("a, ~saber.outfit, b", "saber", "outfit")
    assert not sub_references("~saber", "saber", "outfit")
    assert not sub_references("~saber.outfit2", "saber", "outfit")
    assert not sub_references("~rin.outfit", "saber", "outfit")
    assert not sub_references("%saber.outfit", "saber", "outfit")


def test_rename_parent_rewrites_dotted_refs():
    text = "~saber, ~saber.outfit, ~saber_x.outfit, %saber.outfit, ~saber."
    assert rename_token(text, B, "saber", "arturia") == \
        "~arturia, ~arturia.outfit, ~saber_x.outfit, %saber.outfit, ~arturia."


def test_rename_category_does_not_touch_block_tokens():
    assert rename_token("%Cat.x, ~Cat.x", C, "Cat", "Kat") == "%Kat.x, ~Cat.x"


def test_rename_sub_tokens():
    text = "~saber.outfit, ~saber.outfit2, ~rin.outfit, ~saber, ~saber."
    assert rename_sub_tokens(text, "saber", {"outfit": "armor"}) == \
        "~saber.armor, ~saber.outfit2, ~rin.outfit, ~saber, ~saber."


def test_rename_block_refs_covers_sub_texts():
    blocks = {
        "saber": {"category": "P", "text": "s", "subs": [sub("o", "armor"), sub("p", "~saber.o, x")]},
        "run": {"category": "Pose", "text": "running, ~saber.o"},
        "walk": {"category": "Pose", "text": "walk", "subs": [sub("w", "~saber")]},
        "idle": {"category": "Pose", "text": "idle"},
    }
    before = json.dumps(blocks, sort_keys=True)
    new, updated = subs.rename_block_refs(blocks, "saber", "arturia")
    assert json.dumps(blocks, sort_keys=True) == before  # input not modified
    assert updated == ["run", "saber", "walk"]
    assert new["run"]["text"] == "running, ~arturia.o"
    assert new["saber"]["subs"][1]["text"] == "~arturia.o, x"
    assert new["walk"]["subs"][0]["text"] == "~arturia"
    assert new["idle"] == blocks["idle"]


def test_rewrite_block_texts_keeps_broken_entries():
    block = {"category": "P", "text": "~a", "subs": ["junk", {"name": "1bad", "text": "~a"}, {"name": "x"}]}
    new, changed = subs.rewrite_block_texts(block, lambda t: t.replace("~a", "~b"))
    assert changed
    assert new == {"category": "P", "text": "~b", "subs": ["junk", {"name": "1bad", "text": "~b"}, {"name": "x"}]}
    assert block["text"] == "~a"


def test_rewrite_block_texts_without_subs_keeps_shape():
    block = {"category": "P", "text": "plain"}
    new, changed = subs.rewrite_block_texts(block, lambda t: t)
    assert not changed and new == block and "subs" not in new


# --- users / delete warnings ----------------------------------------------------------------------

def test_users_of_finds_dotted_and_sub_texts():
    blocks = {
        "saber": {"category": "P", "text": "s", "subs": [sub("o", "armor")]},
        "run": {"category": "Pose", "text": "~saber.o"},
        "walk": {"category": "Pose", "text": "w", "subs": [sub("x", "~saber")]},
        "cat": {"category": "Pose", "text": "c", "subs": [sub("x", "%P")]},
        "idle": {"category": "Pose", "text": "idle"},
    }
    assert suggest.users_of(blocks, B, "saber", exclude="saber") == ["run", "walk"]
    assert suggest.users_of(blocks, C, "P") == ["cat"]


def test_delete_warning_for_parent_referenced_via_sub_token():
    blocks = {
        "saber": {"category": "P", "text": "s", "subs": [sub("o", "armor"), sub("p", "~saber.o")]},
        "run": {"category": "Pose", "text": "~saber.o"},
    }
    w = suggest.delete_warnings(blocks, "saber")
    assert w == ["`~saber` is used by: run"]


def test_sub_users():
    blocks = {
        "saber": {"category": "P", "text": "s, ~saber.o",
                  "subs": [sub("o", "~saber.o is self"), sub("p", "x")]},
        "run": {"category": "Pose", "text": "~saber.o"},
        "walk": {"category": "Pose", "text": "w", "subs": [sub("x", "~saber.o")]},
        "rin": {"category": "P", "text": "~rin.o, ~saber, ~saber.oo"},
    }
    assert suggest.sub_users(blocks, "saber", "o") == ["run", "saber", "walk"]
    blocks["saber"]["text"] = "s"
    assert suggest.sub_users(blocks, "saber", "o") == ["run", "walk"]
    assert suggest.sub_users(blocks, "saber", "p") == []


def test_block_texts():
    block = {"category": "P", "text": "t", "subs": [sub("a", "A"), "junk", sub("b", "B", "exclude")]}
    assert subs.block_texts(block) == [(None, "t"), ("a", "A"), ("b", "B")]
    assert subs.block_texts({"category": "P", "text": "t"}) == [(None, "t")]


# --- normalisation --------------------------------------------------------------------------------

def test_normalize_defaults():
    block = {"text": "t", "subs": [{"name": "a", "text": "A"}]}
    assert subs.normalize_subs(block) == [{"name": "a", "text": "A", "mode": "include", "slot": None}]


def test_normalize_missing_or_broken_subs_field():
    for value in (None, "x", 3, {"name": "a"}, True):
        assert subs.normalize_subs({"text": "t", "subs": value}) == []
    assert subs.normalize_subs({"text": "t"}) == []
    assert subs.normalize_subs(None) == []
    assert subs.normalize_subs("junk") == []


def test_normalize_skips_broken_entries():
    block = {"text": "t", "subs": [
        "junk", None, 5,
        {"name": "1bad", "text": "x"},
        {"name": "a.b", "text": "x"},
        {"name": None, "text": "x"},
        {"name": "notext"},
        {"name": "numtext", "text": 3},
        {"name": "good", "text": "G", "mode": "RANDOM", "slot": "outfit"},
        {"name": "good", "text": "duplicate"},
        {"name": "badmode", "text": "B", "mode": "sometimes", "slot": "bad slot"},
        {"name": "nonstrmode", "text": "N", "mode": 1, "slot": 7},
    ]}
    assert subs.normalize_subs(block) == [
        {"name": "good", "text": "G", "mode": "random", "slot": "outfit"},
        {"name": "badmode", "text": "B", "mode": "include", "slot": None},
        {"name": "nonstrmode", "text": "N", "mode": "include", "slot": None},
    ]


def test_normalize_keeps_first_max_subs():
    assert subs.MAX_SUBS == 6  # section 36 C
    block = {"text": "t", "subs": [sub(f"s{i}", str(i)) for i in range(8)]}
    assert subs.sub_names(block) == ["s0", "s1", "s2", "s3", "s4", "s5"]


def test_broken_stored_subs_never_raise_at_expand():
    blocks = {"p": {"category": "P", "text": "p", "subs": ["junk", {"name": "ok", "text": "OK"},
                                                           {"name": "x"}, {"text": "y"}]},
              "q": {"category": "P", "text": "q", "subs": "nonsense"}}
    assert expand("~p, ~q, ~p.ok, ~p.x", blocks, rng()) == "p, OK, q, OK, ~p.x"


def test_get_sub():
    block = {"text": "t", "subs": [sub("a", "A", "exclude")]}
    assert subs.get_sub(block, "a") == {"name": "a", "text": "A", "mode": "exclude", "slot": None}
    assert subs.get_sub(block, "b") is None


# --- validation -----------------------------------------------------------------------------------

def test_validate_ok_and_cleaned():
    rows = [
        {"name": " outfit ", "text": " armor ", "mode": "Random", "slot": ""},
        {"name": "", "text": "", "mode": "include"},  # empty row = no sub-block
        {"name": "hair", "text": "blonde", "slot": "look"},
        {"name": "eyes", "text": "green", "mode": None, "slot": None},
    ]
    cleaned, err = subs.validate_subs(rows)
    assert err is None
    assert cleaned == [
        {"name": "outfit", "text": "armor", "mode": "random", "slot": None},
        {"name": "hair", "text": "blonde", "mode": "include", "slot": "look"},
        {"name": "eyes", "text": "green", "mode": "include", "slot": None},
    ]


def test_validate_empty():
    assert subs.validate_subs([]) == ([], None)
    assert subs.validate_subs(None) == ([], None)
    assert subs.validate_subs([{"name": "", "text": "  "}] * 6) == ([], None)


def test_validate_six_ok_seventh_rejected():
    six = [sub(f"s{i}", "t") for i in range(6)]
    cleaned, err = subs.validate_subs(six)
    assert err is None and len(cleaned) == 6
    cleaned, err = subs.validate_subs(six + [sub("s6", "t")])
    assert cleaned is None and err == "A block can have at most 6 sub-blocks."


@pytest.mark.parametrize("rows, fragment", [
    ([sub("1bad", "t")], "invalid name"),
    ([sub("a.b", "t")], "invalid name"),
    ([{"name": "", "text": "t"}], "invalid name"),
    ([sub("a", "t"), sub("a", "u")], "duplicate"),
    ([sub("a", "  ")], "text cannot be empty"),
    ([{"name": "a"}], "text cannot be empty"),
    ([sub("a", "t", "always")], "invalid mode"),
    ([sub("a", "t", 3)], "invalid mode"),
    ([sub("a", "t", slot="bad slot")], "invalid slot"),
    ([sub("a", "t", slot=5)], "invalid slot"),
    (["junk"], "invalid data"),
])
def test_validate_rejects(rows, fragment):
    cleaned, err = subs.validate_subs(rows)
    assert cleaned is None and fragment in err


def test_same_sub_name_in_different_parents_ok():
    blocks = {
        "saber": {"category": "P", "text": "s", "subs": [sub("outfit", "armor")]},
        "rin": {"category": "P", "text": "r", "subs": [sub("outfit", "red coat")]},
    }
    assert expand("~saber.outfit, ~rin.outfit", blocks, rng()) == "armor, red coat"


def test_set_subs_removes_empty_key():
    assert subs.set_subs({"text": "t", "subs": [sub("a", "A")]}, []) == {"text": "t"}
    assert subs.set_subs({"text": "t"}, [sub("a", "A")]) == {"text": "t", "subs": [sub("a", "A")]}


def test_subs_round_trip_through_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_FILE", str(tmp_path / "blocks.json"))
    cleaned, err = subs.validate_subs([sub("outfit", "armor", "exclude")])
    assert err is None
    storage.save_blocks({"saber": subs.set_subs({"category": "P", "text": "s"}, cleaned)})
    loaded = storage.load_blocks()
    assert loaded["saber"]["subs"] == [{"name": "outfit", "text": "armor", "mode": "exclude", "slot": None}]
    assert expand("~saber, ~saber.outfit", loaded, rng()) == "s, armor"
