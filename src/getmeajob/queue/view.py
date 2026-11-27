"""The revisit queue as people read it: grouped by kind, each kind with one plain line
saying what getmeajob needs from you.

The items themselves live in `data/queue.jsonl` (`QueueLog` in `getmeajob.store`). The
planner and the applier add and resolve them; you add your own with `queue add`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from getmeajob.models import Job, QueueItem, QueueKind
from getmeajob.store import JobStore, QueueLog
from getmeajob.workspace import Workspace

NEED: dict[QueueKind, str] = {
    QueueKind.needs_email_code: (
        "Open the form with `getmeajob apply KEY --mode hold --headed`, then type the code "
        "from your email."
    ),
    QueueKind.needs_answers: (
        "Answer the open questions: run `getmeajob plan unknowns --stub answers-todo.yaml`, "
        "fill it in, then `getmeajob plan answer answers-todo.yaml` and `getmeajob plan`."
    ),
    QueueKind.captcha: (
        "The site showed a bot check, which getmeajob never solves. Apply by hand at the "
        "link, then run `getmeajob track set KEY applied`."
    ),
    QueueKind.account_required: (
        "The site wants an account, which getmeajob never creates. Apply by hand at the "
        "link, then run `getmeajob track set KEY applied`."
    ),
    QueueKind.automation_refused: (
        "The form asks people not to use automated tools. If you still want the job, apply "
        "by hand at the link, then run `getmeajob track set KEY applied`."
    ),
    QueueKind.validation_error: (
        "The form did not accept some answers. Read the detail, fix the answer in "
        "answers.yaml, then run `getmeajob plan KEY` and apply again."
    ),
    QueueKind.fill_problem: (
        "Some fields could not be filled. Run `getmeajob apply KEY --mode hold --headed` "
        "and finish those fields yourself."
    ),
    QueueKind.manual: "Your own reminders. When one is done, run `getmeajob queue resolve ID`.",
}

KIND_ORDER: tuple[QueueKind, ...] = (
    QueueKind.needs_email_code,
    QueueKind.needs_answers,
    QueueKind.validation_error,
    QueueKind.fill_problem,
    QueueKind.captcha,
    QueueKind.account_required,
    QueueKind.automation_refused,
    QueueKind.manual,
)


def need_line(kind: QueueKind, key: str | None = None) -> str:
    """What getmeajob needs from you for this kind; `KEY` filled in when a key is given."""
    line = NEED[QueueKind(kind)]
    return line.replace("KEY", key) if key else line


@dataclass
class QueueGroup:
    kind: QueueKind
    need: str
    items: list[QueueItem] = field(default_factory=list)

    def to_dict(self, jobs: Mapping[str, Job]) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "need": self.need,
            "count": len(self.items),
            "items": [item_row(i, jobs) for i in self.items],
        }


def item_row(item: QueueItem, jobs: Mapping[str, Job]) -> dict[str, Any]:
    job = jobs.get(item.job_key)
    return {
        "id": item.id,
        "kind": item.kind.value,
        "key": item.job_key,
        "company": job.company if job else "",
        "role": job.title if job else "",
        "detail": item.detail,
        "url": item.url or (job.url if job else None),
        "since": item.created_at,
        "resolved_at": item.resolved_at,
        "resolution": item.resolution,
    }


def _id_order(item: QueueItem) -> tuple[int, str]:
    return (int(item.id) if item.id.isdigit() else 10**9, item.id)


def group_items(items: Iterable[QueueItem]) -> list[QueueGroup]:
    """Items grouped by kind in a fixed order (codes first, your reminders last)."""
    groups = {kind: QueueGroup(kind, need_line(kind)) for kind in KIND_ORDER}
    for item in sorted(items, key=_id_order):
        groups[QueueKind(item.kind)].items.append(item)
    return [g for g in groups.values() if g.items]


def counts_by_kind(items: Iterable[QueueItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for group in group_items(items):
        counts[group.kind.value] = len(group.items)
    return counts


def queue_view(
    ws: Workspace, *, include_resolved: bool = False, kind: QueueKind | None = None
) -> dict[str, Any]:
    """The queue as plain data (what `getmeajob queue --json` prints)."""
    log = QueueLog(ws)
    items = log.all_items() if include_resolved else log.open_items()
    if kind is not None:
        items = [i for i in items if i.kind == kind]
    jobs = JobStore(ws).load()
    open_count = sum(1 for i in items if i.resolved_at is None)
    return {"open": open_count, "groups": [g.to_dict(jobs) for g in group_items(items)]}
