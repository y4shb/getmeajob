"""Read a career-ops-style `portals.yml` file into boards and filters.

Entries come from `tracked_companies` and `job_boards`. For each one the ATS is taken
from `provider` (when it names a source getmeajob has), else from the `api` URL, else
from the `careers_url`. Anything else is reported as unsupported, with a reason.
`enabled: false` entries are imported as disabled boards. The title and location
filters are read so `import-portals` can print them; they are not applied.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from getmeajob.models import Board
from getmeajob.sources.boards import board_id
from getmeajob.sources.common import as_dict, as_list, as_str, clean_text
from getmeajob.sources.discover import board_from_url
from getmeajob.sources.feeds import FEEDS
from getmeajob.sources.registry import all_sources
from getmeajob.textutil import truncate
from getmeajob.yamlio import load_yaml

LOCATION_KEYS = ("always_allow", "allow", "block", "block_hard")
ENTRY_LISTS = ("tracked_companies", "job_boards")


@dataclass
class PortalsImport:
    boards: list[Board]
    unsupported: list[tuple[str, str]]
    title_include: list[str] = field(default_factory=list)
    title_exclude: list[str] = field(default_factory=list)
    location_rules: dict[str, list[str]] = field(default_factory=dict)
    aliases: dict[str, list[str]] = field(default_factory=dict)


def _strings(value: Any) -> list[str]:
    items = value if isinstance(value, list) else [value] if isinstance(value, str) else []
    return [s for s in (clean_text(as_str(i)) for i in items) if s]


# ----------------------------------------------------------------- entries


def _board_for_provider(provider: str, urls: list[str], name: str) -> Board | None:
    source = all_sources()[provider]
    for url in urls:
        slug = source.parse_url(url)
        if slug:
            board = board_from_url(url, name)
            region = board.region if board is not None and board.ats == provider else None
            return Board(company=name, ats=provider, slug=slug, region=region)
    return None


def _entry(entry: Mapping[str, Any]) -> tuple[Board | None, str]:
    """(board, reason it is unsupported)."""
    name = clean_text(entry.get("name"))
    provider = clean_text(entry.get("provider")).casefold()
    urls = [u for u in (clean_text(entry.get("api")), clean_text(entry.get("careers_url"))) if u]
    board: Board | None = None
    if provider and provider in all_sources():
        board = _board_for_provider(provider, urls, name)
        if board is None:
            return None, f"provider {provider}, but no {provider} board URL to read the slug from"
    elif provider in FEEDS:
        return None, f"{provider} is a feed: use `getmeajob source --feeds {provider}`"
    elif provider:
        return None, f"provider '{provider}' is not supported"
    else:
        for url in urls:
            board = board_from_url(url, name)
            if board is not None:
                board.company = name
                break
    if board is None:
        if clean_text(entry.get("scan_method")).casefold() == "websearch":
            return None, "web-search entries are not supported (no board URL)"
        if not urls:
            return None, "no careers_url or api to read a board from"
        return None, "the URL is not a supported job board (try `getmeajob discover`)"
    board.enabled = entry.get("enabled") is not False
    careers = clean_text(entry.get("careers_url"))
    board.careers_url = careers or None
    notes = clean_text(entry.get("notes"))
    board.notes = truncate(notes, 200) if notes else None
    return board, ""


def import_portals(path: Path) -> PortalsImport:
    """Boards and filters from a portals.yml file (nothing is written here)."""
    data = load_yaml(path)
    title = as_dict(data.get("title_filter"))
    location = as_dict(data.get("location_filter"))
    result = PortalsImport(
        boards=[],
        unsupported=[],
        title_include=_strings(title.get("positive")),
        title_exclude=_strings(title.get("negative")),
        location_rules={k: _strings(location.get(k)) for k in LOCATION_KEYS if k in location},
        aliases={
            clean_text(as_str(k)): _strings(v)
            for k, v in as_dict(data.get("company_aliases")).items()
            if clean_text(as_str(k))
        },
    )
    seen: set[tuple[str, str]] = set()
    for list_name in ENTRY_LISTS:
        for index, raw in enumerate(as_list(data.get(list_name)), start=1):
            entry = as_dict(raw)
            name = clean_text(entry.get("name"))
            if not name:
                result.unsupported.append((f"{list_name} entry {index}", "no name"))
                continue
            board, reason = _entry(entry)
            if board is None:
                result.unsupported.append((name, reason))
            elif board_id(board) in seen:
                result.unsupported.append((name, f"duplicate of {board.ats}:{board.slug}"))
            else:
                seen.add(board_id(board))
                result.boards.append(board)
    return result
