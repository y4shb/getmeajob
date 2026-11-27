"""Finding a file the user typed: the current folder first, then the workspace."""

from __future__ import annotations

from pathlib import Path

from getmeajob.workspace import Workspace


def find_user_file(text: str, ws: Workspace) -> Path:
    """`exports/tracker.xlsx` works from the workspace folder and from anywhere else."""
    path = Path(text).expanduser()
    if path.is_absolute() or path.exists():
        return path
    inside = ws.root / path
    return inside if inside.exists() else path


def shown(path: Path, ws: Workspace) -> str:
    """A path for messages: relative to the workspace when it is inside it."""
    try:
        return path.resolve().relative_to(ws.root.resolve()).as_posix()
    except (ValueError, OSError):
        return str(path)
