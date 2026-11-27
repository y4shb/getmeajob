"""`getmeajob status`: the whole search on one screen (at most 40 lines).

Built for agents as much as people: counts, the latest changes, what waits on you and
one suggested next command, instead of reading every file.
"""

from __future__ import annotations

from typing import Any

from getmeajob.models import AppStatus, PlanStatus, QueueKind
from getmeajob.queue.view import counts_by_kind
from getmeajob.report.rows import open_questions
from getmeajob.sources.registry import ATS_FOR_FORMS
from getmeajob.textutil import truncate
from getmeajob.track.ghost import ghost_candidates
from getmeajob.track.snapshot import Snapshot, load_snapshot
from getmeajob.track.status import nonzero
from getmeajob.workspace import Workspace

MAX_LINES = 40
NAMES_SHOWN = 3
QUESTIONS_SHOWN = 3


def _names(snap: Snapshot, keys: list[str]) -> str:
    shown = []
    for key in keys[:NAMES_SHOWN]:
        job = snap.jobs.get(key)
        shown.append(f"{job.company}: {job.title}" if job else key)
    more = f" (+{len(keys) - NAMES_SHOWN} more)" if len(keys) > NAMES_SHOWN else ""
    return truncate("; ".join(shown), 150) + more


def _next_command(snap: Snapshot, unknowns: int) -> str:
    if not snap.jobs:
        return "getmeajob source"
    if not snap.ranked:
        return "getmeajob rank"
    human = [i for i in snap.queue_open if i.kind != QueueKind.needs_answers]
    if human:
        return "getmeajob queue"
    if unknowns:
        return "getmeajob plan unknowns --stub todo.yaml"
    unplanned = [
        k
        for k, job in snap.jobs.items()
        if snap.status_of(k) == AppStatus.shortlisted
        and k not in snap.plans
        and job.ats in ATS_FOR_FORMS
    ]
    if unplanned:
        return "getmeajob plan"
    ready = [
        k
        for k, plan in snap.plans.items()
        if plan.status == PlanStatus.ready
        and snap.status_of(k) == AppStatus.ready
        and k not in snap.ledger
    ]
    if ready:
        return "getmeajob apply --mode dry"
    if ghost_candidates(snap):
        return "getmeajob track ghost"
    return "getmeajob report"


def status_digest(ws: Workspace) -> dict[str, Any]:
    """Everything `status` shows, as plain data."""
    snap = load_snapshot(ws)
    groups = open_questions(snap)
    open_jobs = sum(1 for j in snap.jobs.values() if j.status != "closed")
    eligible = sum(1 for r in snap.ranked.values() if r.eligible)
    plans: dict[str, int] = {s.value: 0 for s in PlanStatus}
    for plan in snap.plans.values():
        plans[plan.status.value] += 1
    run = snap.last_run
    return {
        "taken_at": snap.taken_at,
        "jobs": {
            "found": len(snap.jobs),
            "open": open_jobs,
            "eligible": eligible,
            "tracked": len(snap.tracked_keys()),
        },
        "status_counts": snap.counts(),
        "last_run": None
        if run is None
        else {
            "run_id": run.run_id,
            "started": run.started,
            "new": run.new_keys,
            "closed": run.closed_keys,
            "errors": len(run.errors),
        },
        "last_run_names": {
            "new": _names(snap, run.new_keys) if run else "",
            "closed": _names(snap, run.closed_keys) if run else "",
        },
        "queue": counts_by_kind(snap.queue_open),
        "plans": plans,
        "questions": [
            {"label": g.label, "jobs": len(g.jobs), "required": g.required} for g in groups
        ],
        "next": _next_command(snap, len(groups)),
    }


def status_lines(digest: dict[str, Any]) -> list[str]:
    """The human screen: short lines, never more than 40."""
    jobs = digest["jobs"]
    stamp = str(digest["taken_at"]).replace("T", " ").replace("Z", " UTC")
    lines = [
        f"getmeajob status, {stamp}",
        f"jobs: {jobs['found']} found, {jobs['open']} open, {jobs['eligible']} eligible, "
        f"{jobs['tracked']} on the tracker",
        f"status: {nonzero(digest['status_counts'])}",
    ]
    run = digest["last_run"]
    if run is None:
        lines.append("last source run: none yet")
    else:
        when = str(run["started"]).replace("T", " ").replace("Z", "")[:16] or run["run_id"]
        errors = f", {run['errors']} board error(s)" if run["errors"] else ""
        lines.append(
            f"last source run {when}: {len(run['new'])} new, {len(run['closed'])} closed{errors}"
        )
        if run["new"]:
            lines.append(f"  new: {digest['last_run_names']['new']}")
        if run["closed"]:
            lines.append(f"  closed: {digest['last_run_names']['closed']}")
    queue = digest["queue"]
    total = sum(queue.values())
    lines.append(
        f"waiting on you: {total} queue item(s)" + (f" ({nonzero(queue)})" if total else "")
    )
    plans = digest["plans"]
    questions = digest["questions"]
    lines.append(
        f"plans: {sum(plans.values())} ({nonzero(plans)}); {len(questions)} question(s) to answer"
    )
    for q in questions[:QUESTIONS_SHOWN]:
        need = "required" if q["required"] else "optional"
        lines.append(f"  - {truncate(q['label'], 70)} ({q['jobs']} job(s), {need})")
    if len(questions) > QUESTIONS_SHOWN:
        lines.append(f"  - and {len(questions) - QUESTIONS_SHOWN} more: getmeajob plan unknowns")
    lines.append(f"next: {digest['next']}")
    return lines[:MAX_LINES]
