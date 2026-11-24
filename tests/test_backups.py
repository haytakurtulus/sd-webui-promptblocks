import datetime
import json
import os

import pytest

from pb_core import storage


class Clock:
    """Injectable clock: each call returns the current time and then advances it by `step` seconds."""

    def __init__(self, step=1):
        self.t = datetime.datetime(2026, 11, 15, 14, 28, 30)
        self.step = step

    def __call__(self):
        t = self.t
        self.t += datetime.timedelta(seconds=self.step)
        return t


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_FILE", str(tmp_path / "data" / "blocks.json"))
    monkeypatch.setattr(storage, "THUMB_DIR", str(tmp_path / "data" / "thumbs"))
    clock = Clock()
    monkeypatch.setattr(storage, "_now", clock)
    return tmp_path / "data"


def _blocks(i):
    return {f"b{j}": {"category": "C", "text": f"text {i}"} for j in range(i)}


def _backup_files(data):
    folder = data / "backups"
    return sorted(os.listdir(folder)) if folder.exists() else []


def test_backup_dir_follows_data_file(data):
    assert storage.backup_dir() == str(data / "backups")


def test_first_save_makes_no_backup(data):
    storage.save_blocks(_blocks(1))
    assert _backup_files(data) == []
    assert storage.list_backups() == []


def test_second_save_backs_up_first_content(data):
    storage.save_blocks(_blocks(1))
    first = (data / "blocks.json").read_bytes()
    storage.save_blocks(_blocks(2))
    files = _backup_files(data)
    assert files == ["blocks-20261115-142830.json"]
    assert (data / "backups" / files[0]).read_bytes() == first
    assert storage.load_blocks() == _blocks(2)
    assert not (data / "backups" / (files[0] + ".tmp")).exists()


def test_identical_content_not_backed_up_twice(data):
    storage.save_blocks(_blocks(1))
    storage.save_blocks(_blocks(1))  # backs up content 1
    storage.save_blocks(_blocks(1))  # current is still content 1 == newest backup -> skipped
    assert len(_backup_files(data)) == 1
    storage.save_blocks(_blocks(2))  # current content 1 == newest backup -> skipped again
    assert len(_backup_files(data)) == 1
    storage.save_blocks(_blocks(3))  # current content 2 -> new backup
    assert len(_backup_files(data)) == 2


def test_more_than_max_removes_oldest(data):
    for i in range(1, storage.MAX_BACKUPS + 3):
        storage.save_blocks(_blocks(i))
    # MAX_BACKUPS + 2 saves -> MAX_BACKUPS + 1 backups made, the oldest one deleted.
    entries = storage.list_backups()
    assert len(entries) == storage.MAX_BACKUPS == len(_backup_files(data))
    counts = [e["count"] for e in entries]
    assert counts == list(range(storage.MAX_BACKUPS + 1, 1, -1))  # newest first; content 1 is gone
    assert "blocks-20261115-142830.json" not in _backup_files(data)


def test_same_second_backups_do_not_overwrite(data, monkeypatch):
    monkeypatch.setattr(storage, "_now", Clock(step=0))
    for i in range(1, 5):
        storage.save_blocks(_blocks(i))
    files = _backup_files(data)
    assert len(files) == 3
    entries = storage.list_backups()
    assert [e["count"] for e in entries] == [3, 2, 1]
    assert [e["file"] for e in entries] == ["blocks-20261115-142830-3.json", "blocks-20261115-142830-2.json",
                                           "blocks-20261115-142830.json"]


def test_list_backups_format_and_unreadable(data):
    storage.save_blocks(_blocks(1))
    storage.save_blocks(_blocks(2))
    storage.save_blocks(_blocks(3))
    folder = data / "backups"
    (folder / "blocks-20200101-000000.json").write_text("{not json", encoding="utf-8")
    (folder / "notes.txt").write_text("ignored", encoding="utf-8")
    (folder / "blocks-latest.json").write_text("{}", encoding="utf-8")
    entries = storage.list_backups()
    assert entries == [
        {"file": "blocks-20261115-142831.json", "time": "2026-11-15 14:28:31", "count": 2},
        {"file": "blocks-20261115-142830.json", "time": "2026-11-15 14:28:30", "count": 1},
        {"file": "blocks-20200101-000000.json", "time": "2020-01-01 00:00:00", "count": None},
    ]
    assert storage.backup_choices() == [
        ("2026-11-15 14:28:31 - 2 blocks", "blocks-20261115-142831.json"),
        ("2026-11-15 14:28:30 - 1 block", "blocks-20261115-142830.json"),
        ("2020-01-01 00:00:00 - unreadable", "blocks-20200101-000000.json"),
    ]


def test_list_backups_without_folder(data):
    assert storage.list_backups() == []
    assert storage.backup_choices() == []


def test_restore_brings_old_content_back_and_backs_up_replaced(data):
    storage.save_blocks(_blocks(1))
    old_bytes = (data / "blocks.json").read_bytes()
    storage.save_blocks(_blocks(2))
    replaced = (data / "blocks.json").read_bytes()
    target = storage.list_backups()[0]["file"]

    restored = storage.restore_backup(target)
    assert restored == _blocks(1)
    assert storage.load_blocks() == _blocks(1)
    assert (data / "blocks.json").read_bytes() == old_bytes
    assert not (data / "blocks.json.tmp").exists()
    newest = storage.list_backups()[0]
    assert newest["count"] == 2
    assert (data / "backups" / newest["file"]).read_bytes() == replaced
    assert (data / "backups" / target).exists()  # the restored backup itself is kept


@pytest.mark.parametrize("bad", ["../blocks.json", "..\\blocks.json", "blocks.json", "",
                                 "blocks-20990101-000000.json", os.path.join("..", "data", "blocks.json")])
def test_restore_rejects_unknown_names(data, bad):
    storage.save_blocks(_blocks(1))
    storage.save_blocks(_blocks(2))
    before = (data / "blocks.json").read_bytes()
    with pytest.raises(ValueError):
        storage.restore_backup(bad)
    assert (data / "blocks.json").read_bytes() == before


def test_restore_unreadable_backup_raises_and_keeps_current(data):
    storage.save_blocks(_blocks(1))
    (data / "backups").mkdir()
    (data / "backups" / "blocks-20200101-000000.json").write_text("{broken", encoding="utf-8")
    before = (data / "blocks.json").read_bytes()
    with pytest.raises(ValueError):
        storage.restore_backup("blocks-20200101-000000.json")
    assert (data / "blocks.json").read_bytes() == before
    assert len(_backup_files(data)) == 1  # no backup made for a failed restore


def test_restore_aborts_when_current_cannot_be_backed_up(data, monkeypatch):
    storage.save_blocks(_blocks(1))
    storage.save_blocks(_blocks(2))
    target = storage.list_backups()[0]["file"]

    def boom():
        raise OSError("disk full")

    monkeypatch.setattr(storage, "backup_current", boom)
    with pytest.raises(ValueError):
        storage.restore_backup(target)
    assert storage.load_blocks() == _blocks(2)


def test_backup_failure_does_not_stop_save(data, monkeypatch, capsys):
    storage.save_blocks(_blocks(1))

    def boom():
        raise OSError("disk full ş")

    monkeypatch.setattr(storage, "_now", boom)
    storage.save_blocks(_blocks(2))
    assert storage.load_blocks() == _blocks(2)
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line]
    assert len(lines) == 1 and "backup" in lines[0]
    assert lines[0].isascii()


def test_backup_failure_when_backup_dir_is_a_file(data):
    storage.save_blocks(_blocks(1))
    (data / "backups").write_text("not a folder", encoding="utf-8")
    storage.save_blocks(_blocks(2))
    assert storage.load_blocks() == _blocks(2)
    assert storage.list_backups() == []


def test_backup_written_payload_is_valid_json(data):
    storage.save_blocks({"saber": {"category": "PCharacter", "text": "şeker"}})
    storage.save_blocks({})
    file_name = storage.list_backups()[0]["file"]
    with open(data / "backups" / file_name, encoding="utf-8") as f:
        assert json.load(f) == {"version": 1, "blocks": {"saber": {"category": "PCharacter", "text": "şeker"}}}
