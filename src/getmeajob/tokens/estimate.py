"""Rough token counts: characters divided by 4.

This is an estimate, not a tokenizer. It is close enough to compare files and to keep
an agent's reading inside a budget.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from getmeajob.errors import GetmeajobError

CHARS_PER_TOKEN = 4
METHOD = "estimate: characters / 4"


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


@dataclass(slots=True)
class FileEstimate:
    path: str
    chars: int
    tokens_estimate: int

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "chars": self.chars, "tokens_estimate": self.tokens_estimate}


def estimate_file(path: Path, label: str | None = None) -> FileEstimate:
    if path.is_dir():
        raise GetmeajobError(f"{path} is a folder.", hint="Name the files inside it instead.")
    if not path.is_file():
        raise GetmeajobError(f"There is no file at {path}.", hint="Check the path and try again.")
    text = path.read_bytes().decode("utf-8", errors="replace")
    return FileEstimate(label or str(path), len(text), estimate_tokens(text))


def estimate_files(paths: Iterable[tuple[Path, str]]) -> dict[str, Any]:
    files = [estimate_file(path, label) for path, label in paths]
    return {
        "method": METHOD,
        "files": [f.to_dict() for f in files],
        "total_chars": sum(f.chars for f in files),
        "total_tokens_estimate": sum(f.tokens_estimate for f in files),
    }
