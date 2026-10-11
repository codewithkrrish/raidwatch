"""Tests for crash-safe JSON persistence."""

import json

import pytest

from raidwatch.storage import StorageError, read_json, write_json_atomic


def test_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    payload = {"locked": True, "actions": [{"kind": "channel_lock"}]}
    write_json_atomic(path, payload)
    assert read_json(path) == payload


def test_no_temp_file_left_behind(tmp_path):
    path = tmp_path / "state.json"
    write_json_atomic(path, {"a": 1})
    leftovers = list(tmp_path.glob("*.tmp")) + list(tmp_path.glob("*.tmp.*"))
    assert leftovers == []
    assert path.exists()


def test_overwrite_replaces_content(tmp_path):
    path = tmp_path / "state.json"
    write_json_atomic(path, {"a": 1})
    write_json_atomic(path, {"b": 2})
    assert read_json(path) == {"b": 2}


def test_read_missing_file_raises_storage_error(tmp_path):
    with pytest.raises(StorageError):
        read_json(tmp_path / "missing.json")


def test_read_corrupt_file_raises_storage_error(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{oops")
    with pytest.raises(StorageError, match="not valid JSON"):
        read_json(path)


def test_write_creates_parent_dirs(tmp_path):
    path = tmp_path / "nested" / "deep" / "state.json"
    write_json_atomic(path, {"ok": True})
    assert read_json(path) == {"ok": True}


def test_payload_is_valid_json_on_disk(tmp_path):
    path = tmp_path / "state.json"
    write_json_atomic(path, {"x": [1, 2, 3]})
    assert json.loads(path.read_text(encoding="utf-8")) == {"x": [1, 2, 3]}
