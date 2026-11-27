"""The boards to watch, from `companies.yaml` in the workspace.

companies:
  - name: Example Corp
    ats: greenhouse
    slug: examplecorp
    enabled: true          # optional, default true
    careers_url: ...       # optional
    region: eu             # optional, Lever only
    verified: true         # optional, default true
    notes: ...             # optional
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from getmeajob.errors import ConfigError
from getmeajob.models import Board
from getmeajob.workspace import Workspace
from getmeajob.yamlio import dump_yaml, load_yaml

_DEFAULT_HEADER = (
    "# Companies to watch. getmeajob reads each company's public job board.\n"
    "# Fields: name, ats, slug (needed); enabled, careers_url, region, verified, notes.\n"
)


def board_id(board: Board) -> tuple[str, str]:
    """What makes two boards the same: the ATS and the slug, ignoring case."""
    return board.ats.casefold(), board.slug.casefold()


def _bad(path: Path, index: int, problem: str) -> ConfigError:
    return ConfigError(
        f"{path.name}: company {index} {problem}.",
        hint=f"Fix that entry in {path}. Each one needs name, ats and slug.",
    )


def _optional_str(path: Path, index: int, entry: Mapping[str, Any], key: str) -> str | None:
    value = entry.get(key)
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        raise _bad(path, index, f"has a '{key}' that is not text")
    return str(value).strip() or None


def _flag(path: Path, index: int, entry: Mapping[str, Any], key: str, default: bool) -> bool:
    value = entry.get(key)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise _bad(path, index, f"has '{key}: {value}'; use true or false")
    return value


def parse_boards(data: Mapping[str, Any], path: Path) -> list[Board]:
    raw = data.get("companies")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ConfigError(
            f"{path.name}: 'companies' should be a list of entries starting with '-'.",
            hint="Compare it with config/companies.example.yaml.",
        )
    boards: list[Board] = []
    for index, entry in enumerate(raw, start=1):
        if not isinstance(entry, Mapping):
            raise _bad(path, index, "is not a 'name: ..., ats: ..., slug: ...' entry")
        name = _optional_str(path, index, entry, "name") or _optional_str(
            path, index, entry, "company"
        )
        ats = _optional_str(path, index, entry, "ats")
        slug = _optional_str(path, index, entry, "slug")
        if not name or not ats or not slug:
            missing = "name" if not name else "ats" if not ats else "slug"
            raise _bad(path, index, f"has no '{missing}'")
        region = _optional_str(path, index, entry, "region")
        boards.append(
            Board(
                company=name,
                ats=ats.casefold(),
                slug=slug,
                enabled=_flag(path, index, entry, "enabled", True),
                careers_url=_optional_str(path, index, entry, "careers_url"),
                region=region.casefold() if region else None,
                verified=_flag(path, index, entry, "verified", True),
                notes=_optional_str(path, index, entry, "notes"),
            )
        )
    return boards


def load_boards(ws: Workspace) -> list[Board]:
    """All boards in companies.yaml (a missing file means none)."""
    path = ws.companies_path
    return parse_boards(load_yaml(path, required=False), path)


def board_entry(board: Board) -> dict[str, Any]:
    """The YAML entry for a board, leaving out fields that have their default value."""
    entry: dict[str, Any] = {"name": board.company, "ats": board.ats, "slug": board.slug}
    if not board.enabled:
        entry["enabled"] = False
    if board.careers_url:
        entry["careers_url"] = board.careers_url
    if board.region:
        entry["region"] = board.region
    if not board.verified:
        entry["verified"] = False
    if board.notes:
        entry["notes"] = board.notes
    return entry


def _header(path: Path) -> str:
    """The comment lines at the top of the current file, kept on rewrite."""
    if not path.exists():
        return _DEFAULT_HEADER
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            lines.append(line)
        else:
            break
    text = "\n".join(lines).strip("\n")
    return text + "\n\n" if text else ""


def save_boards(ws: Workspace, boards: Iterable[Board]) -> None:
    """Rewrite companies.yaml with these boards (the top comment block is kept)."""
    path = ws.companies_path
    dump_yaml(path, {"companies": [board_entry(b) for b in boards]}, header=_header(path))


def merge_boards(existing: list[Board], new: Iterable[Board]) -> tuple[list[Board], list[Board]]:
    """(all boards, the ones added). A board already listed (same ATS and slug) is kept."""
    seen = {board_id(b) for b in existing}
    added: list[Board] = []
    for board in new:
        if board_id(board) not in seen:
            seen.add(board_id(board))
            added.append(board)
    return existing + added, added
