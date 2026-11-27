"""`run_source`: fetch boards and feeds, store jobs and job text, and work out the diff.

Per run:
1. Boards are grouped by ATS. Groups run side by side; boards in a group run one after
   another, and a bot check on one board skips the rest of that group.
2. All jobs are upserted into `data/jobs.jsonl` (`first_seen` kept), job text goes to
   `data/jd/<key>.txt`, and new jobs get a `discovered` status event.
3. A job that is missing from a board that answered in full is closed, with a `closed`
   status event. A board that failed (or answered only in part) closes nothing.
4. A summary goes to `data/runs/<ts>.json`.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from getmeajob.errors import BotWallError, GetmeajobError
from getmeajob.files import atomic_write_text, now_iso, write_json_atomic
from getmeajob.http import HttpClient
from getmeajob.models import AppStatus, Board, Job
from getmeajob.sources.base import SourceResult
from getmeajob.sources.boards import board_id
from getmeajob.sources.feeds import FEEDS, harvest_boards
from getmeajob.sources.registry import all_sources
from getmeajob.store import JobStore, StatusLog
from getmeajob.workspace import Workspace

MAX_LISTED_ERRORS = 50


@dataclass
class SourceRunSummary:
    new: int
    changed: int
    closed: int
    unchanged: int
    errors: list[str]
    per_board: list[dict[str, Any]]
    # Additions beyond the planned contract:
    new_keys: list[str] = field(default_factory=list)
    changed_keys: list[str] = field(default_factory=list)
    closed_keys: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    harvested: list[str] = field(default_factory=list)
    run_id: str = ""
    run_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @property
    def empty_diff(self) -> bool:
        return not (self.new or self.changed or self.closed)


@dataclass
class _BoardOutcome:
    board: Board
    result: SourceResult | None
    error: str | None


def _fetch_group(boards: Sequence[Board], client: HttpClient) -> list[_BoardOutcome]:
    sources = all_sources()
    outcomes: list[_BoardOutcome] = []
    wall: str | None = None
    for board in boards:
        if wall is not None:
            outcomes.append(_BoardOutcome(board, None, f"skipped: {wall}"))
            continue
        source = sources.get(board.ats)
        if source is None:
            known = ", ".join(sources)
            outcomes.append(_BoardOutcome(board, None, f"no source '{board.ats}' (known: {known})"))
            continue
        try:
            outcomes.append(_BoardOutcome(board, source.list_jobs(board, client), None))
        except BotWallError as exc:
            wall = f"{board.ats} showed a bot check earlier in this run"
            outcomes.append(_BoardOutcome(board, None, exc.message))
        except GetmeajobError as exc:
            outcomes.append(_BoardOutcome(board, None, exc.message))
    return outcomes


def fetch_boards(boards: Iterable[Board], client: HttpClient) -> list[_BoardOutcome]:
    """Fetch boards, one thread per ATS, keeping the input order in the result."""
    unique: dict[tuple[str, str], Board] = {}
    for board in boards:
        unique.setdefault(board_id(board), board)
    groups: dict[str, list[Board]] = {}
    for board in unique.values():
        groups.setdefault(board.ats, []).append(board)
    by_id: dict[tuple[str, str], _BoardOutcome] = {}
    for group, outcome in zip(
        groups.values(), client.map(lambda g: _fetch_group(g, client), groups.values()), strict=True
    ):
        if isinstance(outcome, Exception):
            outcome = [_BoardOutcome(b, None, f"failed: {outcome}") for b in group]
        for item in outcome:
            by_id[board_id(item.board)] = item
    return [by_id[key] for key in unique]


def _board_row(item: _BoardOutcome) -> dict[str, Any]:
    result = item.result
    if item.error is not None or result is None or result.error is not None:
        status, count = "error", 0
    elif not result.found:
        status, count = "not_found", 0
    else:
        status, count = ("partial" if result.partial else "ok"), len(result.jobs)
    row: dict[str, Any] = {
        "board": f"{item.board.ats}:{item.board.slug}",
        "company": item.board.company,
        "status": status,
        "jobs": count,
    }
    if result is not None and result.board_name:
        row["board_name"] = result.board_name
    if item.error or (result is not None and result.error):
        row["error"] = item.error or (result.error if result else None)
    if result is not None and result.skipped:
        row["skipped"] = len(result.skipped)
    return row


def _error_line(item: _BoardOutcome) -> str | None:
    where = f"{item.board.ats}:{item.board.slug}"
    if item.error is not None:
        return f"{where}: {item.error}"
    result = item.result
    if result is None:
        return None
    if result.error is not None:
        return f"{where}: {result.error}"
    if not result.found:
        return f"{where}: board not found (check the slug in companies.yaml)"
    return None


def _write_jd(ws: Workspace, jobs: Iterable[Job]) -> None:
    for job in jobs:
        if not job.description:
            continue
        path = ws.jd_path(job.key)
        if path.exists() and path.read_text(encoding="utf-8") == job.description:
            continue
        atomic_write_text(path, job.description)


def _run_path(ws: Workspace, started: str) -> tuple[str, Path]:
    """`data/runs/20261127T140509Z.json`; a second run in the same second gets `_02`
    (names sort in run order)."""
    run_id = started.replace(":", "").replace("-", "")
    path = ws.runs_dir / f"{run_id}.json"
    counter = 2
    while path.exists():
        path = ws.runs_dir / f"{run_id}_{counter:02d}.json"
        counter += 1
    return path.stem, path


def _fetch_feeds(
    names: Sequence[str], client: HttpClient, errors: list[str], skipped: list[str]
) -> list[Job]:
    jobs: list[Job] = []
    for name in names:
        feed = FEEDS.get(name)
        if feed is None:
            errors.append(f"feed {name}: unknown (known: {', '.join(FEEDS)})")
            continue
        try:
            jobs += feed(client, skipped)
        except GetmeajobError as exc:
            errors.append(f"feed {name}: {exc.message}")
    return jobs


def run_source(
    ws: Workspace,
    client: HttpClient,
    boards: list[Board],
    *,
    feeds: Sequence[str] = (),
) -> SourceRunSummary:
    """Fetch `boards` (and `feeds`), store the jobs and return the diff."""
    started = now_iso()
    outcomes = fetch_boards(boards, client)
    errors: list[str] = []
    skipped: list[str] = []
    notes: list[str] = []
    fetched: list[Job] = []
    complete: list[Board] = []
    for item in outcomes:
        line = _error_line(item)
        if line:
            errors.append(line)
        result = item.result
        if result is None or result.error is not None or not result.found:
            continue
        fetched += result.jobs
        skipped += result.skipped
        notes += result.notes
        if not result.partial:
            complete.append(item.board)

    feed_jobs = _fetch_feeds(list(feeds), client, errors, skipped)
    known = {board_id(b) for b in boards}
    harvested = [b for b in harvest_boards(feed_jobs) if board_id(b) not in known]

    store = JobStore(ws)
    events = StatusLog(ws)
    stamp = now_iso()
    upsert = store.upsert([*fetched, *feed_jobs], stamp)
    _write_jd(ws, [*fetched, *feed_jobs])
    for key in upsert.new:
        events.record(key, AppStatus.discovered, "source")
    for key in upsert.changed:  # only a closed posting that came back actually changes
        events.record(key, AppStatus.discovered, "source", note="back on the board")

    seen = {job.key for job in fetched}
    complete_ids = {board_id(b) for b in complete}
    vanished = [
        job.key
        for job in store.all()
        if job.status != "closed"
        and (job.ats.casefold(), job.board.casefold()) in complete_ids
        and job.key not in seen
    ]
    closed = store.mark_closed(vanished, stamp)
    for key in closed:
        events.record(key, AppStatus.closed, "source", note="no longer on the board")

    run_id, path = _run_path(ws, started)
    summary = SourceRunSummary(
        new=len(upsert.new),
        changed=len(upsert.changed),
        closed=len(closed),
        unchanged=len(upsert.unchanged),
        errors=errors[:MAX_LISTED_ERRORS],
        per_board=[_board_row(item) for item in outcomes],
        new_keys=upsert.new,
        changed_keys=upsert.changed,
        closed_keys=closed,
        skipped=skipped,
        notes=notes,
        harvested=[f"{b.ats}:{b.slug}" for b in harvested],
        run_id=run_id,
        run_path=str(path),
    )
    record = summary.to_dict()
    record.update(started=started, finished=now_iso(), feeds=list(feeds))
    write_json_atomic(path, record)
    return summary
