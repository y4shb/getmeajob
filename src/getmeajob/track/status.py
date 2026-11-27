"""The status ladder in one place: order, plain meanings, parsing and counts.

Every status change goes through `StatusLog.record` in `getmeajob.store`, which holds
the rules (people may set anything, automatic steps only move forward). Changes made by
a person go through `record_by_person` here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from getmeajob.files import parse_ts as parse_ts  # moved to files; kept here for callers
from getmeajob.models import FORWARD_ORDER, AppStatus
from getmeajob.store import QueueLog, StatusLog
from getmeajob.workspace import Workspace

SIDE_ORDER: tuple[AppStatus, ...] = (
    AppStatus.rejected,
    AppStatus.withdrawn,
    AppStatus.closed,
    AppStatus.skipped,
    AppStatus.ghosted,
)
LADDER: tuple[AppStatus, ...] = (*FORWARD_ORDER, *SIDE_ORDER)

MEANING: dict[AppStatus, str] = {
    AppStatus.discovered: "found by `getmeajob source`",
    AppStatus.shortlisted: "scored high enough in `getmeajob rank`",
    AppStatus.planned: "form read and answers planned",
    AppStatus.ready: "every required question has an answer",
    AppStatus.applied: "application sent",
    AppStatus.screening: "first contact: recruiter call or test",
    AppStatus.interviewing: "interviews under way",
    AppStatus.offer: "you have an offer",
    AppStatus.accepted: "you took the offer",
    AppStatus.rejected: "the company said no",
    AppStatus.withdrawn: "you pulled out",
    AppStatus.closed: "the posting closed",
    AppStatus.skipped: "you chose not to apply",
    AppStatus.ghosted: "no news for weeks after applying",
}

ACTIVE_FROM = FORWARD_ORDER.index(AppStatus.applied)
GREEN = frozenset(FORWARD_ORDER[ACTIVE_FROM:])  # applied and later
GREY = frozenset(SIDE_ORDER)  # dead ends


def status_names() -> str:
    return ", ".join(s.value for s in LADDER)


def norm_word(text: str) -> str:
    """Status text spelled like an `AppStatus` value: " Phone-Screen " -> "phone_screen"."""
    return "_".join(text.strip().casefold().replace("-", " ").split())


def parse_status(text: object) -> AppStatus | None:
    """`AppStatus` for text like "Applied", " screening " or "Ghosted"; None if unknown."""
    if text is None:
        return None
    try:
        return AppStatus(norm_word(str(text)))
    except ValueError:
        return None


def ladder_index(status: AppStatus) -> int:
    return LADDER.index(status)


def counts_in_ladder_order(statuses: Iterable[AppStatus | str]) -> dict[str, int]:
    """Count per status, every status present (zeros too), in ladder order."""
    counts = {s.value: 0 for s in LADDER}
    for status in statuses:
        counts[AppStatus(status).value] += 1
    return counts


def nonzero(counts: Mapping[str, int]) -> str:
    """Counts above zero as one line, in the given order: `shortlisted 2, ready 1`."""
    parts = [f"{name} {n}" for name, n in counts.items() if n]
    return ", ".join(parts) if parts else "none"


def day_of(text: str | None) -> str:
    """`2026-11-27` from an ISO stamp or date string, else ""."""
    if not text:
        return ""
    stamp = parse_ts(text)
    if stamp is not None:
        return stamp.date().isoformat()
    head = text.strip()[:10]
    return head if len(head) == 10 and head[4] == "-" and head[7] == "-" else ""


def record_by_person(ws: Workspace, key: str, status: AppStatus, source: str, note: str) -> bool:
    """The one write path for a status a person sets (`manual` or `xlsx`).

    Records the event through `StatusLog` and, when the job is now applied or later or at
    a dead end, resolves its open queue items: nothing is waiting on you any more.
    Returns whether the status was written (False when it was already that status).
    """
    if not StatusLog(ws).record(key, status, source, note):
        return False
    if status in GREEN or status in GREY:
        QueueLog(ws).resolve(key, None, f"status set to {status.value}")
    return True
