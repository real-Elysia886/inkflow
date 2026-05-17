"""Atomic file writers.

These helpers write to a sibling temp file then `os.replace()` it onto the
target path. On POSIX `replace` is atomic; on NTFS it is atomic for files on
the same volume. This avoids leaving half-written JSON / YAML / text files if
the process crashes or two writers race.

All helpers create parent directories as needed.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

__all__ = [
    "write_text_atomic",
    "write_bytes_atomic",
    "write_json_atomic",
]


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Use a NamedTemporaryFile in the same dir so os.replace is atomic.
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # fsync not supported on some filesystems; ignore.
                pass
        os.replace(tmp_path, path)
    except Exception:
        # Best-effort cleanup of the temp file on failure.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def write_text_atomic(path: str | Path, content: str, encoding: str = "utf-8") -> None:
    """Atomically write ``content`` to ``path`` using ``encoding``."""
    p = Path(path)
    _atomic_write(p, content.encode(encoding))


def write_bytes_atomic(path: str | Path, data: bytes) -> None:
    """Atomically write raw bytes to ``path``."""
    p = Path(path)
    _atomic_write(p, data)


def write_json_atomic(
    path: str | Path,
    obj: Any,
    *,
    indent: Optional[int] = 2,
    ensure_ascii: bool = False,
) -> None:
    """Atomically write ``obj`` as JSON to ``path``."""
    text = json.dumps(obj, ensure_ascii=ensure_ascii, indent=indent)
    write_text_atomic(path, text)
