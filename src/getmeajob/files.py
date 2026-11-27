"""Plain file helpers: UTC timestamps, JSON and JSONL reading and atomic writing.

JSONL appends take an exclusive lock (POSIX `fcntl.flock`) so two processes never
interleave half lines. Atomic writes go to a temp file in the same folder, then rename.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
from collections.abc import Iterable, Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from getmeajob.errors import StoreError


def now_iso() -> str:
    """Current UTC time like `2026-11-27T14:05:09Z`."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(text: str) -> datetime | None:
    """A UTC datetime from an ISO stamp like `2026-11-27T12:16:50Z`; None when unreadable."""
    if not text:
        return None
    try:
        value = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def utc_text(ts: str) -> str:
    """An ISO stamp for people: `2026-11-27T14:05:09Z` -> `2026-11-27 14:05:09 UTC`."""
    return ts.replace("T", " ").replace("Z", " UTC")


def minute_text(ts: str) -> str:
    """An ISO stamp to the minute: `2026-11-27T14:05:09Z` -> `2026-11-27 14:05`."""
    return ts.replace("T", " ").replace("Z", "")[:16]


@contextlib.contextmanager
def _locked(fh: IO[Any], *, exclusive: bool) -> Iterator[None]:
    """Hold an advisory lock on an open file (POSIX only; a no-op elsewhere)."""
    if sys.platform == "win32":
        yield
        return
    import fcntl

    fcntl.flock(fh.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
    try:
        yield
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write `data` to `path` via a temp file in the same folder and a rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def _dumps_line(record: Mapping[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """All records of a JSONL file. A missing file gives `[]`; a bad line raises StoreError."""
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh, _locked(fh, exclusive=False):
        for number, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise StoreError(
                    f"{path} line {number} is not valid JSON ({exc.msg}).",
                    hint="Fix or delete that line. The file is plain text, one record per line.",
                ) from exc
            if not isinstance(record, dict):
                raise StoreError(
                    f"{path} line {number} is not a JSON object.",
                    hint="Fix or delete that line. The file is plain text, one record per line.",
                )
            records.append(record)
    return records


def append_jsonl(path: Path, record: Mapping[str, Any]) -> None:
    """Append one record as a line, under an exclusive lock so processes do not interleave."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = _dumps_line(record)
    with path.open("a", encoding="utf-8") as fh, _locked(fh, exclusive=True):
        fh.write(line)
        fh.flush()


def write_jsonl_atomic(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    atomic_write_text(path, "".join(_dumps_line(r) for r in records))


def write_json_atomic(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path, default: Any = None) -> Any:
    """Parsed JSON, or `default` when the file does not exist."""
    if not path.exists():
        return default
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise StoreError(
            f"{path} line {exc.lineno} is not valid JSON ({exc.msg}).",
            hint="Fix the file, or delete it and run the command that writes it again.",
        ) from exc
