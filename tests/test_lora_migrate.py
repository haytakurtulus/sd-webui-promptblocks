"""LoRA not in negative prompts + migration helper (design notes section 13)."""
import copy
import json
import random

import pytest

from pb_core import parser, storage
from pb_core.lora import merge_lora, migrate_all, migrate_block, split_lora_tags

LORA = "<lora:saber_v2:0.8>"


def make_blocks(with_lora=True):
    saber = {"category": "PCharacter", "text": "1girl, saber (fate)",
             "subs": [{"name": "armor", "text": "silver armor", "mode": "include"},
                      {"name": "dress", "text": "blue dress", "mode": "random"},
                      {"name": "a", "text": "outfit a", "mode": "include", "slot": "outfit"},
                      {"name": "b", "text": "outfit b", "mode": "random", "slot": "outfit"}]}
    rin = {"category": "PCharacter", "text": "rin tohsaka"}
    if with_lora:
        saber["lora"] = LORA
        rin["lora"] = "<lora:rin:1>"
    return {
        "saber": saber,
        "rin": rin,
        "scene": {"category": "PPose", "text": "running, ~saber, %PCharacter"},
    }


PROMPTS = ["~saber", "%PCharacter, %PCharacter", "~scene", "~saber.armor, ~saber", "~saber*outfit",
           "~rin, ~scene, %PCharacter"]


# ---- expand(lora=False) ----

@pytest.mark.parametrize("prompt", PROMPTS)
def test_negative_call_inserts_no_lora_and_same_rng(prompt):
    for seed in range(30):
        rng_off, rng_plain = random.Random(seed), random.Random(seed)
        out_off = parser.expand(prompt, make_blocks(), rng_off, lora=False)
        out_plain = parser.expand(prompt, make_blocks(with_lora=False), rng_plain)
        assert out_off == out_plain
        assert "<lora:" not in out_off
        # Same RNG consumption: both generators are in the same state afterwards.
        assert rng_off.random() == rng_plain.random()


def test_default_and_lora_true_still_insert():
    blocks = make_blocks()
    a = parser.expand("~saber", blocks, random.Random(1))
    b = parser.expand("~saber", blocks, random.Random(1), lora=True)
    assert a == b and a.count(LORA) == 1


def test_lora_false_with_trace_and_rng_parity_with_lora_on():
    # LoRA never consumes RNG, so on/off also leaves the RNG in the same state.
    blocks = make_blocks()
    for seed in range(20):
        r1, r2 = random.Random(seed), random.Random(seed)
        t1, t2 = [], []
        parser.expand("~scene, ~saber*outfit", blocks, r1, trace=t1, lora=False)
        parser.expand("~scene, ~saber*outfit", blocks, r2, trace=t2)
        assert t1 == t2
        assert r1.random() == r2.random()


def test_lora_is_keyword_only():
    with pytest.raises(TypeError):
        parser.expand("~saber", make_blocks(), random.Random(0), 0, None, None, False)


# ---- split_lora_tags ----

@pytest.mark.parametrize("text, clean, tags", [
    # none
    ("1girl, saber", "1girl, saber", []),
    ("", "", []),
    ("a,  b ,c", "a,  b ,c", []),  # no tag: user's formatting untouched
    # one
    ("1girl, saber, <lora:saber:0.8>", "1girl, saber", ["<lora:saber:0.8>"]),
    ("<lora:saber:0.8>, 1girl", "1girl", ["<lora:saber:0.8>"]),
    # several
    ("<lora:a:1>, x, <lyco:b:0.5>, y, <lora:c:1>", "x, y", ["<lora:a:1>", "<lyco:b:0.5>", "<lora:c:1>"]),
    ("x, <lora:a:1>, <lora:b:1>, y", "x, y", ["<lora:a:1>", "<lora:b:1>"]),
    # duplicates (first kept)
    ("<lora:a:1>, x, <lora:a:1>", "x", ["<lora:a:1>"]),
    ("<lora:a:1>, <lora:a:0.5>, x", "x", ["<lora:a:1>", "<lora:a:0.5>"]),
    # tag in the middle
    ("1girl, <lora:saber:0.8>, blonde hair", "1girl, blonde hair", ["<lora:saber:0.8>"]),
    ("1girl,<lora:saber:0.8>,blonde hair", "1girl,blonde hair", ["<lora:saber:0.8>"]),
    ("1girl <lora:saber:0.8> blonde", "1girl blonde", ["<lora:saber:0.8>"]),
    ("1girl, <lora:s:1> blonde", "1girl, blonde", ["<lora:s:1>"]),
    ("1girl <lora:s:1>, blonde", "1girl, blonde", ["<lora:s:1>"]),
    ("a, <lora:s:1>, , b", "a, b", ["<lora:s:1>"]),
    ("a<lora:s:1>b", "a b", ["<lora:s:1>"]),
    # only a tag
    ("<lora:saber:0.8>", "", ["<lora:saber:0.8>"]),
    ("  <lora:saber:0.8> , ", "", ["<lora:saber:0.8>"]),
    ("<lora:a:1>, <lyco:b:1>", "", ["<lora:a:1>", "<lyco:b:1>"]),
    # case-insensitive tag name, kept verbatim
    ("x, <LoRA:Saber:0.8>, <LYCO:b:1>", "x", ["<LoRA:Saber:0.8>", "<LYCO:b:1>"]),
    # newlines kept; a line that held only a tag disappears
    ("a, b,\n<lora:x:1>\nc", "a, b,\nc", ["<lora:x:1>"]),
    ("a, <lora:x:1>\nb, c", "a\nb, c", ["<lora:x:1>"]),
    ("a\n<lora:x:1>", "a", ["<lora:x:1>"]),
    ("<lora:x:1>\r\na", "a", ["<lora:x:1>"]),
    # spacing not next to a tag is not touched
    ("a,  b, <lora:x:1>", "a,  b", ["<lora:x:1>"]),
    # not a LoRA tag
    ("<hypernet:x:1>, <loraX:y>, lora:z", "<hypernet:x:1>, <loraX:y>, lora:z", []),
])
def test_split_lora_tags(text, clean, tags):
    assert split_lora_tags(text) == (clean, tags)


@pytest.mark.parametrize("text", ["a, , <lora:x:1>", ", <lora:x:1>, a", "a, <lora:x:1>, , <lora:y:1>, b",
                                  "<lora:x:1> , , a , <lora:y:1>"])
def test_split_leaves_no_comma_runs_or_edges(text):
    clean, _ = split_lora_tags(text)
    assert ", ," not in clean and ",," not in clean
    assert clean == clean.strip(" ,")


def test_split_non_string():
    assert split_lora_tags(None) == ("", [])


# ---- merge_lora ----

def test_merge_lora():
    assert merge_lora("", ["<lora:a:1>"]) == "<lora:a:1>"
    assert merge_lora(None, ["<lora:a:1>", "<lora:a:1>"]) == "<lora:a:1>"
    assert merge_lora("<lora:a:1>", ["<lora:a:1>", "<lora:b:1>"]) == "<lora:a:1>, <lora:b:1>"
    assert merge_lora(" <lora:a:1> ", ["<lora:b:1>"]) == "<lora:a:1>, <lora:b:1>"
    assert merge_lora("<lora:a:1>", ["<lora:a:1>"]) == "<lora:a:1>"
    assert merge_lora("<lora:a:1>", []) == "<lora:a:1>"


# ---- migrate_block / migrate_all ----

def test_migrate_block_moves_main_text_only():
    block = {"category": "C", "text": "x, <lora:a:1>", "lora": "<lora:z:1>",
             "subs": [{"name": "s", "text": "y, <lora:sub:1>", "mode": "include"}]}
    before = copy.deepcopy(block)
    new, changed = migrate_block(block)
    assert changed
    assert new["text"] == "x"
    assert new["lora"] == "<lora:z:1>, <lora:a:1>"
    assert new["subs"] == before["subs"]  # sub-block texts untouched
    assert block == before  # input not modified
    again, changed2 = migrate_block(new)
    assert not changed2 and again == new


def test_migrate_block_without_tags_unchanged():
    block = {"category": "C", "text": "x, y"}
    assert migrate_block(block) == (block, False)
    assert migrate_block({"category": "C"}) == ({"category": "C"}, False)
    assert migrate_block({"category": "C", "text": 5}) == ({"category": "C", "text": 5}, False)


def test_migrate_block_only_tag_gives_empty_text():
    new, changed = migrate_block({"category": "C", "text": "<lora:a:1>"})
    assert changed and new == {"category": "C", "text": "", "lora": "<lora:a:1>"}


def test_migrate_block_tag_already_in_lora():
    new, changed = migrate_block({"category": "C", "text": "x, <lora:a:1>", "lora": "<lora:a:1>"})
    assert changed and new == {"category": "C", "text": "x", "lora": "<lora:a:1>"}


def test_migrate_all_changes_only_blocks_with_tags_and_is_idempotent():
    blocks = {
        "saber": {"category": "P", "text": "1girl, <lora:saber:0.8>, blonde"},
        "rin": {"category": "P", "text": "rin", "lora": "<lora:rin:1>"},
        "subonly": {"category": "P", "text": "plain",
                    "subs": [{"name": "s", "text": "<lora:s:1>", "mode": "include"}]},
        "onlytag": {"category": "P", "text": "<lora:only:1>"},
        "weird": {"category": "P", "text": 3},
    }
    before = copy.deepcopy(blocks)
    new, changed, skipped = migrate_all(blocks)
    assert changed == ["saber"]
    assert skipped == ["onlytag"]
    assert blocks == before  # input not modified
    assert new["saber"] == {"category": "P", "text": "1girl, blonde", "lora": "<lora:saber:0.8>"}
    for name in ("rin", "subonly", "onlytag", "weird"):
        assert new[name] == before[name]
    again, changed2, skipped2 = migrate_all(new)
    assert again == new and changed2 == [] and skipped2 == ["onlytag"]


def test_migrate_all_one_save_one_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_FILE", str(tmp_path / "blocks.json"))
    monkeypatch.setattr(storage, "THUMB_DIR", str(tmp_path / "thumbs"))
    storage.save_blocks({"a": {"category": "C", "text": "x, <lora:a:1>"},
                         "b": {"category": "C", "text": "y, <lora:b:1>"}})
    new, changed, _ = migrate_all(storage.load_blocks())
    storage.save_blocks(new)
    assert changed == ["a", "b"]
    assert len(storage.list_backups()) == 1
    data = json.loads((tmp_path / "blocks.json").read_text(encoding="utf-8"))
    assert data["blocks"]["a"] == {"category": "C", "text": "x", "lora": "<lora:a:1>"}
    # The migrated block expands to the same tags as before (now via the LoRA field).
    assert parser.expand("~a", storage.load_blocks(), random.Random(0)) == "x, <lora:a:1>"
