"""The ghost sweep: jobs you applied to that have gone quiet.

A job is a candidate when its status is `applied` or `screening` and its newest status
event is older than N days (21 by default). `apply_ghosts` records `ghosted` with the
automatic source `ghost`, so the store rules apply: only from applied or screening,
never over a status you set later.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from getmeajob.models import AppStatus
from getmeajob.store import StatusLog
from getmeajob.track.snapshot import Snapshot
from getmeajob.track.status import parse_ts
from getmeajob.workspace import Workspace

GHOST_SOURCE = "ghost"
DEFAULT_DAYS = 21
QUIET_STATUSES = (AppStatus.applied, AppStatus.screening)


@dataclass(slots=True)
class GhostCandidate:
    key: str
    status: AppStatus
    last_event: str
    days_quiet: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "status": self.status.value,
            "last_event": self.last_event,
            "days_quiet": self.days_quiet,
        }


def ghost_candidates(
    snap: Snapshot, days: int = DEFAULT_DAYS, now: datetime | None = None
) -> list[GhostCandidate]:
    """Jobs in applied or screening with no newer status event for `days` days."""
    moment = now or datetime.now(UTC)
    found: list[GhostCandidate] = []
    for key, events in snap.history.items():
        if not events or snap.current.get(key) not in QUIET_STATUSES:
            continue
        stamps = [s for s in (parse_ts(e.ts) for e in events) if s is not None]
        if not stamps:
            continue
        newest = max(stamps)
        quiet = (moment - newest).days
        if quiet >= days:
            found.append(GhostCandidate(key, snap.current[key], events[-1].ts, quiet))
    return sorted(found, key=lambda c: (-c.days_quiet, c.key))


def apply_ghosts(ws: Workspace, candidates: Iterable[GhostCandidate]) -> list[str]:
    """Record `ghosted` for each candidate the rules allow. Returns the keys written."""
    log = StatusLog(ws)
    written: list[str] = []
    for item in candidates:
        note = f"no news for {item.days_quiet} days"
        if log.record(item.key, AppStatus.ghosted, GHOST_SOURCE, note):
            written.append(item.key)
    return written
