import pytest

from pb_core import storage


def test_save_then_load(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_FILE", str(tmp_path / "data" / "blocks.json"))
    blocks = {"saber": {"category": "PCharacter", "text": "1girl, şeker"}}
    storage.save_blocks(blocks)
    assert storage.load_blocks() == blocks
    assert not (tmp_path / "data" / "blocks.json.tmp").exists()


def test_load_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_FILE", str(tmp_path / "nope.json"))
    assert storage.load_blocks() == {}


def test_thumb_roundtrip(tmp_path, monkeypatch):
    Image = pytest.importorskip("PIL.Image")
    monkeypatch.setattr(storage, "THUMB_DIR", str(tmp_path / "thumbs"))

    storage.save_thumb("saber", Image.new("RGBA", (512, 768), (255, 0, 0, 255)))
    thumb = storage.load_thumb("saber")
    assert max(thumb.size) == storage.THUMB_SIZE
    assert thumb.size == (85, 128)
    assert storage.thumb_mtime("saber") is not None

    storage.delete_thumb("saber")
    assert storage.load_thumb("saber") is None
    assert storage.thumb_mtime("saber") is None