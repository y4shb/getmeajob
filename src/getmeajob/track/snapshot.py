"""One read of the whole workspace, shared by the trackers, `status` and `context`.

Nothing here writes files. `load_snapshot(ws)` reads jobs, ranks, plans, status events,
the queue, the ledger, your notes and the latest `getmeajob source` run once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from getmeajob.files import now_iso, read_json, read_jsonl
from getmeajob.models import (
    FORWARD_ORDER,
    AppStatus,
    Job,
    LedgerEntry,
    Plan,
    QueueItem,
    RankResult,
    StatusEvent,
)
from getmeajob.plan.plans import all_plans
from getmeajob.store import HUMAN_SOURCES, JobStore, Ledger, QueueLog
from getmeajob.track.notes import JobNotes, NotesLog
from getmeajob.track.status import counts_in_ladder_order, ladder_index
from getmeajob.workspace import Workspace


@dataclass(slots=True)
class RunInfo:
    """The latest `data/runs/<ts>.json` written by `getmeajob source`."""

    run_id: str
    started: str
    new_keys: list[str]
    closed_keys: list[str]
    changed_keys: list[str]
    errors: list[str]

    def change_for(self, key: str) -> str:
        if key in self.new_keys:
            return "new"
        if key in self.closed_keys:
            return "closed"
        if key in self.changed_keys:
            return "changed"
        return ""


def _strings(value: Any) -> list[str]:
    return [str(v) for v in value] if isinstance(value, list) else []


def latest_run(ws: Workspace) -> RunInfo | None:
    """The newest run summary (file names sort in run order), or None."""
    if not ws.runs_dir.is_dir():
        return None
    for path in sorted(ws.runs_dir.glob("*.json"), reverse=True):
        data = read_json(path, default=None)
        if not isinstance(data, dict):
            continue
        return RunInfo(
            run_id=str(data.get("run_id") or path.stem),
            started=str(data.get("started") or ""),
            new_keys=_strings(data.get("new_keys")),
            closed_keys=_strings(data.get("closed_keys")),
            changed_keys=_strings(data.get("changed_keys")),
            errors=_strings(data.get("errors")),
        )
    return None


@dataclass
class Snapshot:
    ws: Workspace
    jobs: dict[str, Job]
    ranked: dict[str, RankResult]
    plans: dict[str, Plan]
    current: dict[str, AppStatus]
    history: dict[str, list[StatusEvent]]
    queue_open: list[QueueItem]
    ledger: dict[str, list[LedgerEntry]]
    notes: dict[str, JobNotes]
    last_run: RunInfo | None
    taken_at: str = field(default_factory=now_iso)

    def status_of(self, key: str) -> AppStatus:
        """Current status; a job with no events yet counts as `discovered`."""
        return self.current.get(key, AppStatus.discovered)

    def queue_for(self, key: str) -> list[QueueItem]:
        return [item for item in self.queue_open if item.job_key == key]

    def is_tracked(self, key: str) -> bool:
        """On the Tracker: shortlisted or further, or a plan, ledger entry, queue item,
        note or a status you set yourself."""
        events = self.history.get(key, [])
        if any(e.source in HUMAN_SOURCES for e in events):
            return True
        if any(e.status not in (AppStatus.discovered, AppStatus.closed) for e in events):
            return True
        return (
            key in self.plans
            or key in self.ledger
            or key in self.notes
            or any(item.job_key == key for item in self.queue_open)
        )

    def score_of(self, key: str) -> int | None:
        result = self.ranked.get(key)
        return result.score if result else None

    def order_key(self, key: str) -> tuple[int, int, str, str]:
        """Ladder order, then best score first, then company and title."""
        job = self.jobs[key]
        score = self.score_of(key)
        return (
            ladder_index(self.status_of(key)),
            -(score if score is not None else -1),
            job.company.casefold(),
            job.title.casefold(),
        )

    def tracked_keys(self) -> list[str]:
        keys = [k for k in self.jobs if self.is_tracked(k)]
        return sorted(keys, key=self.order_key)

    def all_keys_by_score(self) -> list[str]:
        def by_score(key: str) -> tuple[int, str, str]:
            score = self.score_of(key)
            job = self.jobs[key]
            return (-(score if score is not None else -1), job.company.casefold(), key)

        return sorted(self.jobs, key=by_score)

    def applied_on(self, key: str) -> str:
        """Stamp of the first `applied` event, else of the first submitted attempt."""
        for event in self.history.get(key, []):
            if event.status == AppStatus.applied:
                return event.ts
        for entry in self.ledger.get(key, []):
            if entry.status.value == "submitted":
                return entry.ts
        return ""

    def counts(self) -> dict[str, int]:
        return counts_in_ladder_order(self.status_of(key) for key in self.jobs)


def load_snapshot(ws: Workspace) -> Snapshot:
    jobs = JobStore(ws).load()
    ranked = {}
    for record in read_jsonl(ws.ranked_path):
        result = RankResult.from_dict(record)
        if result.key:
            ranked[result.key] = result
    plans = {p.job_key: p for p in all_plans(ws)}
    history: dict[str, list[StatusEvent]] = {}
    current: dict[str, AppStatus] = {}
    for record in read_jsonl(ws.events_path):  # same reading as StatusLog: last one wins
        event = StatusEvent.from_dict(record)
        history.setdefault(event.job_key, []).append(event)
        current[event.job_key] = event.status
    ledger: dict[str, list[LedgerEntry]] = {}
    for entry in Ledger(ws).entries():
        ledger.setdefault(entry.job_key, []).append(entry)
    return Snapshot(
        ws=ws,
        jobs=jobs,
        ranked=ranked,
        plans=plans,
        current=current,
        history=history,
        queue_open=QueueLog(ws).open_items(),
        ledger=ledger,
        notes=NotesLog(ws).current(),
        last_run=latest_run(ws),
    )


def funnel(ws: Workspace) -> dict[str, Any]:
    """Jobs per status now, and per forward step how many got at least that far."""
    snap = load_snapshot(ws)
    now = snap.counts()
    reached = {s.value: 0 for s in FORWARD_ORDER}
    for key in snap.jobs:
        events = snap.history.get(key, [])
        steps = [FORWARD_ORDER.index(e.status) for e in events if e.status in FORWARD_ORDER]
        top = max(steps, default=0)
        for status in FORWARD_ORDER[: top + 1]:
            reached[status.value] += 1
    return {"total": len(snap.jobs), "now": now, "reached": reached}
