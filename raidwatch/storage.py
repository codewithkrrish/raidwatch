"""Crash-safe JSON persistence: write to a temp file, then atomic rename."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class StorageError(Exception):
    """Raised when persisted state cannot be read or written."""


def write_json_atomic(path: str | Path, data: Any) -> None:
    """Write JSON to ``path`` atomically.

    The payload goes to a temp file in the same directory first, so a crash
    can never leave a half-written file behind.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=target.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_name, target)
    except OSError as exc:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise StorageError(f"could not write {target}: {exc}") from exc


def read_json(path: str | Path) -> Any:
    """Read and parse a JSON file.

    Raises:
        StorageError: if the file is missing, unreadable, or not valid JSON.
    """
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise StorageError(f"could not read {source}: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise StorageError(f"{source} is not valid JSON: {exc}") from exc
