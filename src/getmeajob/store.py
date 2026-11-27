"""Workspace storage: the job store and the append-only logs (events, queue, ledger)."""

from __future__ import annotations

import dataclasses
import difflib
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from getmeajob.errors import GetmeajobError
from getmeajob.files import append_jsonl, now_iso, read_jsonl, write_jsonl_atomic
from getmeajob.models import (
    FORWARD_ORDER,
    SIDE_STATES,
    ApplyStatus,
    AppStatus,
    Job,
    LedgerEntry,
    QueueItem,
    QueueKind,
    StatusEvent,
)
from getmeajob.textutil import short_hash
from getmeajob.workspace import Workspace

HUMAN_SOURCES = frozenset({"manual", "xlsx"})
AUTO_CLOSERS = frozenset({"source", "liveness"})


class _LogFile:
    """Remembers a file's size and mtime so a log is only re-read when it changed."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._sig: tuple[int, int] | None = None

    def signature(self) -> tuple[int, int]:
        try:
            st = self.path.stat()
        except FileNotFoundError:
            return (-1, -1)
        return (st.st_size, st.st_mtime_ns)

    def stale(self) -> bool:
        return self._sig != self.signature()

    def mark_fresh(self) -> None:
        self._sig = self.signature()


# --------------------------------------------------------------------- job store


@dataclasses.dataclass(slots=True)
class UpsertResult:
    new: list[str] = dataclasses.field(default_factory=list)
    changed: list[str] = dataclasses.field(default_factory=list)
    unchanged: list[str] = dataclasses.field(default_factory=list)
    reopened: list[str] = dataclasses.field(default_factory=list)


def _job_signature(job: Job) -> tuple[str, str, str, str]:
    return (job.title, job.location, short_hash(job.description), job.url)


class JobStore:
    """All known jobs, one JSON object per line in `data/jobs.jsonl`, keyed by job key."""

    def __init__(self, ws: Workspace) -> None:
        self.ws = ws
        self.path = ws.jobs_path

    def load(self) -> dict[str, Job]:
        jobs: dict[str, Job] = {}
        for record in read_jsonl(self.path):
            job = Job.from_dict(record)
            jobs[job.key] = job
        return jobs

    def all(self) -> list[Job]:
        return list(self.load().values())

    def get(self, key: str) -> Job | None:
        return self.load().get(key)

    def find(self, key: str) -> Job:
        """The job with this key, else the one job whose key contains `key` (any case)."""
        jobs = self.load()
        if key in jobs:
            return jobs[key]
        part = key.casefold()
        matches = [k for k in jobs if part and part in k.casefold()]
        if len(matches) == 1:
            return jobs[matches[0]]
        if matches:
            raise GetmeajobError(
                f"'{key}' matches {len(matches)} jobs.",
                hint=f"Did you mean {', '.join(matches[:3])}? Give more of the key.",
            )
        close = difflib.get_close_matches(key, list(jobs), n=3, cutoff=0.6)
        if close:
            hint = f"Did you mean {', '.join(close)}?"
        elif jobs:
            hint = "Run `getmeajob rank --all` to see the keys."
        else:
            hint = "No jobs are stored yet. Run `getmeajob source` first."
        raise GetmeajobError(f"No job with the key '{key}'.", hint=hint)

    def _save(self, jobs: Mapping[str, Job]) -> None:
        write_jsonl_atomic(self.path, (job.to_dict() for job in jobs.values()))

    def upsert(self, jobs: Iterable[Job], now: str) -> UpsertResult:
        """Add or refresh jobs. Keeps `first_seen`, sets `last_seen` to `now`.

        "changed" means the title, location, description or url changed, or a closed job
        came back ("reopened"). An empty incoming description keeps the stored one (some list
        endpoints leave it out) and does not count as a change.
        """
        stored = self.load()
        result = UpsertResult()
        seen: set[str] = set()
        for job in jobs:
            old = stored.get(job.key)
            if old is None:
                merged = dataclasses.replace(job, first_seen=job.first_seen or now, last_seen=now)
                stored[job.key] = merged
                if job.key not in seen:
                    result.new.append(job.key)
                seen.add(job.key)
                continue
            description = job.description or old.description
            merged = dataclasses.replace(
                job,
                description=description,
                first_seen=old.first_seen or job.first_seen or now,
                last_seen=now,
            )
            stored[job.key] = merged
            if job.key in seen:
                continue
            seen.add(job.key)
            reopened = old.status == "closed" and merged.status != "closed"
            if reopened:
                result.reopened.append(job.key)
            if reopened or _job_signature(old) != _job_signature(merged):
                result.changed.append(job.key)
            else:
                result.unchanged.append(job.key)
        self._save(stored)
        return result

    def mark_closed(self, keys: Iterable[str], now: str) -> list[str]:
        """Set status "closed" on these jobs. Returns the keys that were open before."""
        stored = self.load()
        closed: list[str] = []
        for key in keys:
            job = stored.get(key)
            if job is None or job.status == "closed":
                continue
            stored[key] = dataclasses.replace(job, status="closed")
            closed.append(key)
        if closed:
            self._save(stored)
        return closed


# -------------------------------------------------------------- status events


def _forward_index(status: AppStatus) -> int:
    return FORWARD_ORDER.index(status)


def transition_allowed(
    current: AppStatus | None, new: AppStatus, source: str, closed_by: str = ""
) -> bool:
    """The status rules. Humans (`manual`, `xlsx`) may set anything; automatic sources
    only move forward, may close a job only before `applied`, may mark `ghosted` only
    from `applied` or `screening`, and never move a job out of a side state, except that
    sourcing may reopen a posting that came back (back to `discovered`) when `source` or
    `liveness` closed it (`closed_by`)."""
    if current == new:
        return False
    if source in HUMAN_SOURCES:
        return True
    if current == AppStatus.closed and new == AppStatus.discovered and source == "source":
        return closed_by in AUTO_CLOSERS
    if current in SIDE_STATES:
        return False
    if new in FORWARD_ORDER:
        return current is None or _forward_index(new) > _forward_index(current)
    if new == AppStatus.closed:
        return current is None or _forward_index(current) < _forward_index(AppStatus.applied)
    if new == AppStatus.ghosted:
        return current in (AppStatus.applied, AppStatus.screening)
    return False


class StatusLog:
    """Application status per job, as an append-only log in `data/events.jsonl`."""

    def __init__(self, ws: Workspace) -> None:
        self.ws = ws
        self.path = ws.events_path
        self._file = _LogFile(self.path)
        self._events: list[StatusEvent] = []
        self._last: dict[str, StatusEvent] = {}

    def _refresh(self) -> None:
        if not self._file.stale():
            return
        self._events = [StatusEvent.from_dict(r) for r in read_jsonl(self.path)]
        self._last = {event.job_key: event for event in self._events}
        self._file.mark_fresh()

    def record(self, key: str, status: AppStatus, source: str, note: str = "") -> bool:
        """Write a status change if the rules allow it. Returns whether it was written."""
        self._refresh()
        status = AppStatus(status)
        last = self._last.get(key)
        current, closed_by = (last.status, last.source) if last else (None, "")
        if not transition_allowed(current, status, source, closed_by):
            return False
        event = StatusEvent(ts=now_iso(), job_key=key, status=status, source=source, note=note)
        append_jsonl(self.path, event.to_dict())
        self._events.append(event)
        self._last[key] = event
        self._file.mark_fresh()
        return True

    def current(self, key: str) -> AppStatus | None:
        self._refresh()
        last = self._last.get(key)
        return last.status if last else None

    def history(self, key: str) -> list[StatusEvent]:
        self._refresh()
        return [e for e in self._events if e.job_key == key]


# ------------------------------------------------------------------- queue


class QueueLog:
    """Things that need the human, as an append-only log in `data/queue.jsonl`.

    Records are `{"op": "add", <QueueItem fields>}` or
    `{"op": "resolve", "id": ..., "resolved_at": ..., "resolution": ...}`.
    Item ids are short increasing numbers ("1", "2", ...) so they are easy to type.
    """

    def __init__(self, ws: Workspace) -> None:
        self.ws = ws
        self.path = ws.queue_path
        self._file = _LogFile(self.path)
        self._items: dict[str, QueueItem] = {}

    def _refresh(self) -> None:
        if not self._file.stale():
            return
        items: dict[str, QueueItem] = {}
        for record in read_jsonl(self.path):
            op = record.get("op")
            if op == "add":
                item = QueueItem.from_dict(record)
                old = items.get(item.id)
                if old is not None:
                    item = dataclasses.replace(item, created_at=old.created_at)
                items[item.id] = item
            elif op == "resolve" and str(record.get("id")) in items:
                item_id = str(record["id"])
                items[item_id] = dataclasses.replace(
                    items[item_id],
                    resolved_at=record.get("resolved_at") or now_iso(),
                    resolution=record.get("resolution"),
                )
        self._items = items
        self._file.mark_fresh()

    def _next_id(self) -> str:
        numbers = [int(i) for i in self._items if i.isdigit()]
        return str(max(numbers, default=0) + 1)

    def _write(self, record: Mapping[str, Any]) -> None:
        append_jsonl(self.path, record)
        self._file.mark_fresh()

    def add(self, job_key: str, kind: QueueKind, detail: str, url: str | None = None) -> QueueItem:
        """Add an item. An open item for the same job and kind is updated, not duplicated."""
        self._refresh()
        kind = QueueKind(kind)
        for item in self._items.values():
            if item.job_key == job_key and item.kind == kind and item.resolved_at is None:
                if item.detail == detail and item.url == url:
                    return item
                updated = dataclasses.replace(item, detail=detail, url=url)
                self._write({"op": "add", **updated.to_dict()})
                self._items[item.id] = updated
                return updated
        item = QueueItem(
            id=self._next_id(),
            job_key=job_key,
            kind=kind,
            detail=detail,
            url=url,
            created_at=now_iso(),
        )
        self._write({"op": "add", **item.to_dict()})
        self._items[item.id] = item
        return item

    def _resolve_item(self, item: QueueItem, resolution: str) -> None:
        ts = now_iso()
        self._write({"op": "resolve", "id": item.id, "resolved_at": ts, "resolution": resolution})
        self._items[item.id] = dataclasses.replace(item, resolved_at=ts, resolution=resolution)

    def resolve(self, job_key: str, kind: QueueKind | None, resolution: str) -> int:
        """Resolve the open items of a job (only of `kind` when given). Returns the count."""
        self._refresh()
        wanted = QueueKind(kind) if kind is not None else None
        count = 0
        for item in list(self._items.values()):
            if item.job_key != job_key or item.resolved_at is not None:
                continue
            if wanted is not None and item.kind != wanted:
                continue
            self._resolve_item(item, resolution)
            count += 1
        return count

    def resolve_id(self, item_id: str, resolution: str) -> bool:
        self._refresh()
        item = self._items.get(str(item_id))
        if item is None or item.resolved_at is not None:
            return False
        self._resolve_item(item, resolution)
        return True

    def open_items(self) -> list[QueueItem]:
        self._refresh()
        return [i for i in self._items.values() if i.resolved_at is None]

    def all_items(self) -> list[QueueItem]:
        self._refresh()
        return list(self._items.values())


# ------------------------------------------------------------------- ledger


class Ledger:
    """One record per apply attempt, append-only in `data/ledger.jsonl` (no answer text)."""

    def __init__(self, ws: Workspace) -> None:
        self.ws = ws
        self.path = ws.ledger_path

    def append(self, entry: LedgerEntry) -> None:
        append_jsonl(self.path, entry.to_dict())

    def entries(self, job_key: str | None = None) -> list[LedgerEntry]:
        out = [LedgerEntry.from_dict(r) for r in read_jsonl(self.path)]
        if job_key is not None:
            out = [e for e in out if e.job_key == job_key]
        return out

    def last_status(self, job_key: str) -> ApplyStatus | None:
        entries = self.entries(job_key)
        return entries[-1].status if entries else None
