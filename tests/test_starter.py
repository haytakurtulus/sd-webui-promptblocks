"""Starter blocks for new users (design notes section 41): examples/starter_blocks.json and
storage.seed_starter_blocks(). Seeding tests use tmp_path + monkeypatch only, never the real data/."""

import json
import os
import random

import pytest

from pb_core import formsave, health, parser, storage, subrows, subs

# The tracked starter file itself (read-only here; it lives in examples/, not data/).
REAL_STARTER = storage.STARTER_FILE


def starter_data():
    with open(REAL_STARTER, "r", encoding="utf-8") as f:
        return json.load(f)


def starter_blocks():
    return starter_data()["blocks"]


# ---- the starter file ----

def test_starter_file_path_is_in_examples():
    assert os.path.normcase(REAL_STARTER) == os.path.normcase(
        os.path.join(storage.EXT_ROOT, "examples", "starter_blocks.json"))
    assert os.path.isfile(REAL_STARTER)


def test_starter_file_shape():
    data = starter_data()
    assert data["version"] == 1
    assert set(data) == {"version", "blocks"}
    blocks = data["blocks"]
    assert len(blocks) == 4
    cats = {b["category"] for b in blocks.values()}
    assert cats == {"Outfit", "Scene"}
    assert sorted(n for n, b in blocks.items() if b["category"] == "Outfit") == ["casual", "fantasy"]
    assert sorted(n for n, b in blocks.items() if b["category"] == "Scene") == ["city", "forest"]
    total_subs = 0
    for name, b in blocks.items():
        assert parser.is_valid_name(name)
        # Nothing else: no weight / slot / lora / bans / ADetailer keys.
        assert set(b) == {"category", "text", "subs"}, name
        assert b["text"].strip()
        assert len(b["subs"]) == 3, name
        for s in b["subs"]:
            assert set(s) == {"name", "text", "mode", "slot"}
            assert parser.is_valid_name(s["name"])
            assert s["mode"] == "random"
            assert s["slot"] is None
            assert s["text"].strip()
        total_subs += len(b["subs"])
    assert total_subs == 12


def test_starter_has_no_lora_text():
    raw = open(REAL_STARTER, "r", encoding="utf-8").read()
    assert "<lora:" not in raw.lower()


@pytest.mark.parametrize("name", ["casual", "fantasy", "city", "forest"])
def test_starter_block_is_unchanged_by_normalisation_and_form_save(name):
    blocks = starter_blocks()
    block = blocks[name]
    # Load-time normalisation and save-time sub-block validation give the stored list back.
    assert subs.normalize_subs(block) == block["subs"]
    assert subs.validate_subs(block["subs"]) == (block["subs"], None)
    # The form save rule (load the block into the form, save it unchanged) keeps it byte-equal.
    values = subrows.form_values(subrows.block_form(blocks, name), with_chance=True)
    plan = formsave.plan_form_save(blocks, values, name)
    assert plan["error"] is None, plan["error"]
    assert plan["blocks"] == blocks


def test_starter_health_check_has_no_problems():
    assert health.report(starter_blocks()) == []


@pytest.mark.parametrize("token", ["~casual", "~fantasy", "~city", "~forest", "%Outfit", "%Scene"])
def test_starter_blocks_expand_without_unknown_names(token):
    blocks = starter_blocks()
    for seed in range(16):
        out = parser.expand(token, blocks, random.Random(seed))
        assert parser.find_unknown(out) == []
        assert out.strip()


# ---- seed_starter_blocks() ----

@pytest.fixture
def paths(tmp_path, monkeypatch):
    data_file = tmp_path / "data" / "blocks.json"
    monkeypatch.setattr(storage, "DATA_FILE", str(data_file))
    monkeypatch.setattr(storage, "THUMB_DIR", str(tmp_path / "data" / "thumbs"))
    return data_file


def test_missing_data_file_is_written_from_starter(paths, capsys):
    assert not paths.parent.exists()
    assert storage.seed_starter_blocks() is True
    with open(REAL_STARTER, "rb") as f:
        assert paths.read_bytes() == f.read()
    assert storage.load_blocks() == starter_blocks()
    assert not (paths.parent / "blocks.json.tmp").exists()
    assert not (paths.parent / "backups").exists()
    out = capsys.readouterr().out
    assert out.strip() == "[PromptBlocks] first start: added 4 example blocks from examples/starter_blocks.json"
    out.encode("ascii")
    # A second call is a no-op: the file exists now.
    assert storage.seed_starter_blocks() is False


@pytest.mark.parametrize("content", [
    b'{"version": 1, "blocks": {"a": {"category": "C", "text": "x"}}}',
    b'{"version": 1, "blocks": {}}',
    b'{}',
    b'{"version": 1, "blocks": {',
    b'',
])
def test_existing_data_file_is_never_touched(paths, content):
    paths.parent.mkdir(parents=True)
    paths.write_bytes(content)
    before = os.stat(paths).st_mtime_ns
    assert storage.seed_starter_blocks() is False
    assert paths.read_bytes() == content
    assert os.stat(paths).st_mtime_ns == before
    assert sorted(os.listdir(paths.parent)) == ["blocks.json"]


def test_missing_starter_writes_nothing(paths, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(storage, "STARTER_FILE", str(tmp_path / "examples" / "nope.json"))
    assert storage.seed_starter_blocks() is False
    assert not paths.exists()
    assert not paths.parent.exists()
    assert len(capsys.readouterr().out.strip().splitlines()) == 1


@pytest.mark.parametrize("content", [
    b'{"version": 1, "blocks": {',      # broken JSON
    b'\xff\xfe not utf-8',
    b'[]',                               # top level not an object
    b'{"version": 1}',                   # no blocks
    b'{"version": 1, "blocks": []}',     # blocks not an object
    b'{"version": 1, "blocks": {}}',     # no blocks to add
    b'{"version": 1, "blocks": {"a": "text"}}',
    b'{"version": 1, "blocks": {"a": {"category": "C"}}}',
])
def test_invalid_starter_writes_nothing(paths, tmp_path, monkeypatch, capsys, content):
    starter = tmp_path / "examples" / "starter_blocks.json"
    starter.parent.mkdir()
    starter.write_bytes(content)
    monkeypatch.setattr(storage, "STARTER_FILE", str(starter))
    assert storage.seed_starter_blocks() is False
    assert not paths.exists()
    assert not paths.parent.exists()
    out = capsys.readouterr().out
    assert len(out.strip().splitlines()) == 1
    out.encode("ascii")
