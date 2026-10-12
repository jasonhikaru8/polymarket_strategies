"""Read a JSON file the way readers actually save it."""
from __future__ import annotations

from pathlib import Path


def read_json_text(path) -> str:
    """Text of a JSON file as written by an editor or a shell: UTF-8 with or without a byte-order mark, or the UTF-16 that
    Windows PowerShell 5 writes for `>`."""
    raw = Path(path).read_bytes()
    return raw.decode("utf-16") if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else raw.decode("utf-8-sig")
