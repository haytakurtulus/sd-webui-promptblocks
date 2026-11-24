"""Starter blocks for new users (design notes sections 41 / 41b): examples/starter_blocks.json,
examples/thumbs/ and storage.seed_starter_blocks(). Seeding tests use tmp_path + monkeypatch only,
never the real data/ of any install."""

import json
import os
import random

import pytest

from pb_core import formsave, health, parser, storage, subrows, subs

# The tracked starter file and thumbnails (read-only here; they live in examples/, not data/).
REAL_STARTER = storage.STARTER_FILE
REAL_STARTER_THUMBS = storage.STARTER_THUMB_DIR

STARTER_NAMES = ["Forest", "Peak", "Climb", "Night", "Morning", "Happy", "Tired",
                 "AnimeGirl", "Samurai", "RunScene", "Quality"]
STARTER_CATEGORIES = ["PBackground", "PPose", "PAmbiance", "PEmotion", "PCharacter", "PQuality"]
STARTER_THUMBS = ["AnimeGirl", "RunScene", "Samurai"]
FIRST_START_LINE = "[PromptBlocks] first start: added 11 example blocks from examples/starter_blocks.json"


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
    assert os.path.normcase(REAL_STARTER_THUMBS) == os.path.normcase(
        os.path.join(storage.EXT_ROOT, "examples", "thumbs"))


def test_starter_file_shape():
    data = starter_data()
    assert data["version"] == 1
    assert set(data) == {"version", "blocks"}
    blocks = data["blocks"]
    assert len(blocks) == 11
    assert sorted(blocks) == sorted(STARTER_NAMES)
    assert sorted({b["category"] for b in blocks.values()}) == sorted(STARTER_CATEGORIES)
    for name, b in blocks.items():
        assert parser.is_valid_name(name)
        assert b["text"].strip(), name
        for s in b.get("subs", []):
            assert parser.is_valid_name(s["name"])
            assert s["text"].strip()
    # Only AnimeGirl and Samurai carry keys beyond category / text (no weight / slot / lora anywhere).
    extra = sorted(n for n, b in blocks.items() if set(b) != {"category", "text"})
    assert extra == ["AnimeGirl", "Samurai"]


def test_starter_text_fixes_and_rename():
    blocks = starter_blocks()
    assert "stars" in blocks["Night"]["text"] and "starts" not in blocks["Night"]["text"]
    assert "sheath" in blocks["Samurai"]["text"] and "sheet" not in blocks["Samurai"]["text"]
    assert "happy" not in blocks
    assert blocks["Happy"]["category"] == "PEmotion"
    raw = open(REAL_STARTER, "r", encoding="utf-8").read()
    assert "~happy" not in raw


def test_starter_samurai_has_three_random_subs_and_ban():
    sam = starter_blocks()["Samurai"]
    assert set(sam) == {"category", "text", "subs", "bans"}
    assert sam["category"] == "PCharacter"
    assert sam["bans"] == ["~Climb"]
    assert sam["subs"] == [
        {"name": "helmet", "text": "kabuto helmet", "mode": "random", "slot": None},
        {"name": "mask", "text": "menpo mask", "mode": "random", "slot": None},
        {"name": "blossoms", "text": "cherry blossoms, falling petals", "mode": "random", "slot": None},
    ]


def test_starter_animegirl_include_subs_with_slot_and_adetailer():
    ag = starter_blocks()["AnimeGirl"]
    assert set(ag) == {"category", "text", "subs", "adetailer"}
    assert ag["category"] == "PCharacter"
    assert [(s["name"], s["mode"], s["slot"]) for s in ag["subs"]] == [
        ("climb", "include", "Outfit"), ("camp", "include", "Outfit")]
    assert all("chance" not in s for s in ag["subs"])
    assert ag["adetailer"] == ["White hair, mature, red eyes, long hair,", "", "", ""]


def test_starter_bans_point_to_existing_blocks():
    blocks = starter_blocks()
    for name, b in blocks.items():
        for ban in b.get("bans", []):
            assert ban.startswith("~") and ban[1:] in blocks, (name, ban)


def test_starter_has_no_lora_text():
    raw = open(REAL_STARTER, "r", encoding="utf-8").read()
    assert "<lora:" not in raw.lower()


@pytest.mark.parametrize("name", STARTER_NAMES)
def test_starter_block_is_unchanged_by_normalisation_and_form_save(name):
    blocks = starter_blocks()
    block = blocks[name]
    stored = block.get("subs", [])
    # Load-time normalisation and save-time sub-block validation give the stored list back.
    assert subs.normalize_subs(block) == stored
    assert subs.validate_subs(stored) == (stored, None)
    # The form save rule (load the block into the form, save it unchanged) keeps it byte-equal.
    values = subrows.form_values(subrows.block_form(blocks, name), with_chance=True)
    plan = formsave.plan_form_save(blocks, values, name)
    assert plan["error"] is None, plan["error"]
    assert plan["blocks"] == blocks


def test_starter_health_check_has_no_problems():
    assert health.report(starter_blocks()) == []


@pytest.mark.parametrize("token", ["~" + n for n in STARTER_NAMES] + ["%" + c for c in STARTER_CATEGORIES])
def test_starter_blocks_expand_without_unknown_names(token):
    blocks = starter_blocks()
    for seed in range(16):
        out = parser.expand(token, blocks, random.Random(seed))
        assert parser.find_unknown(out) == []
        assert out.strip()


def test_starter_thumbs_folder_matches_blocks():
    assert sorted(os.listdir(REAL_STARTER_THUMBS)) == sorted(n + ".webp" for n in STARTER_THUMBS)
    blocks = starter_blocks()
    assert all(n in blocks for n in STARTER_THUMBS)
    for n in STARTER_THUMBS:
        with open(os.path.join(REAL_STARTER_THUMBS, n + ".webp"), "rb") as f:
            head = f.read(12)
        assert head[:4] == b"RIFF" and head[8:12] == b"WEBP", n


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
    assert out.strip() == FIRST_START_LINE + " (3 thumbnails)"
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
    # Nothing else appears either (no thumbs/ folder).
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


# ---- starter thumbnails (section 41b) ----

def test_thumbs_copied_on_first_start(paths, tmp_path):
    assert storage.seed_starter_blocks() is True
    thumbs = tmp_path / "data" / "thumbs"
    assert sorted(os.listdir(thumbs)) == sorted(n + ".webp" for n in STARTER_THUMBS)
    for n in STARTER_THUMBS:
        with open(os.path.join(REAL_STARTER_THUMBS, n + ".webp"), "rb") as f:
            assert (thumbs / (n + ".webp")).read_bytes() == f.read()


def test_existing_thumb_is_not_overwritten(paths, tmp_path, capsys):
    thumbs = tmp_path / "data" / "thumbs"
    thumbs.mkdir(parents=True)
    (thumbs / "Samurai.webp").write_bytes(b"mine")
    assert storage.seed_starter_blocks() is True
    assert (thumbs / "Samurai.webp").read_bytes() == b"mine"
    assert (thumbs / "AnimeGirl.webp").exists() and (thumbs / "RunScene.webp").exists()
    assert capsys.readouterr().out.strip() == FIRST_START_LINE + " (2 thumbnails)"


def test_no_thumbs_copied_when_data_file_existed(paths, tmp_path):
    paths.parent.mkdir(parents=True)
    paths.write_bytes(b'{"version": 1, "blocks": {}}')
    assert storage.seed_starter_blocks() is False
    assert not (tmp_path / "data" / "thumbs").exists()


def test_missing_thumbs_folder_still_writes_blocks(paths, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(storage, "STARTER_THUMB_DIR", str(tmp_path / "examples" / "no_thumbs"))
    assert storage.seed_starter_blocks() is True
    assert storage.load_blocks() == starter_blocks()
    assert not (tmp_path / "data" / "thumbs").exists()
    assert capsys.readouterr().out.strip() == FIRST_START_LINE


def test_thumb_whose_name_is_not_a_starter_block_is_ignored(paths, tmp_path, monkeypatch):
    src = tmp_path / "examples" / "thumbs"
    src.mkdir(parents=True)
    (src / "Samurai.webp").write_bytes(b"s")
    (src / "Nobody.webp").write_bytes(b"n")     # not a starter block
    (src / "Samurai.png").write_bytes(b"p")     # not a .webp
    (src / "_x.webp").write_bytes(b"x")         # not a valid name
    monkeypatch.setattr(storage, "STARTER_THUMB_DIR", str(src))
    assert storage.seed_starter_blocks() is True
    thumbs = tmp_path / "data" / "thumbs"
    assert sorted(os.listdir(thumbs)) == ["Samurai.webp"]
    assert (thumbs / "Samurai.webp").read_bytes() == b"s"


def test_thumb_copy_failure_keeps_blocks_file(paths, monkeypatch, capsys):
    real = storage._atomic_write_bytes

    def write(path, data):
        if path.endswith(".webp"):
            raise OSError("disk full")
        return real(path, data)

    monkeypatch.setattr(storage, "_atomic_write_bytes", write)
    assert storage.seed_starter_blocks() is True
    assert storage.load_blocks() == starter_blocks()
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("[PromptBlocks] starter thumbnails not")
    assert lines[1] == FIRST_START_LINE
    "".join(lines).encode("ascii")
