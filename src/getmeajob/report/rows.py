"""Rows for the trackers, built from one workspace snapshot.

The Excel and Markdown writers only format what these functions return, so both files
always agree.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from getmeajob.plan.unknowns import UnknownGroup, collect_unknowns
from getmeajob.queue.view import group_items, item_row, need_line
from getmeajob.rank.score import job_text
from getmeajob.resume.store import list_roles
from getmeajob.textutil import truncate
from getmeajob.track.snapshot import Snapshot
from getmeajob.track.status import GREEN, GREY, day_of
from getmeajob.workspace import Workspace

WHY_CHARS = 200
UNKNOWN_CHARS = 200


@dataclass(slots=True)
class TrackerRow:
    key: str
    company: str
    role: str
    location: str
    tier: str
    score: int | None
    eligible: bool | None
    why: str
    status: str
    applied_on: str
    next_action: str
    resume_used: str
    plan_status: str
    unknowns: str
    job_link: str
    jd_file: Path | None
    posted: str
    first_seen: str
    change: str
    notes: str
    open_queue: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "company": self.company,
            "role": self.role,
            "location": self.location,
            "tier": self.tier,
            "score": self.score,
            "eligible": self.eligible,
            "why": self.why,
            "status": self.status,
            "applied_on": self.applied_on,
            "next_action": self.next_action,
            "resume_used": self.resume_used,
            "plan_status": self.plan_status,
            "unknowns": self.unknowns,
            "job_link": self.job_link,
            "jd_file": str(self.jd_file) if self.jd_file else "",
            "posted": self.posted,
            "first_seen": self.first_seen,
            "change": self.change,
            "notes": self.notes,
            "open_queue": self.open_queue,
        }


def _relative(path_text: str, root: Path) -> str:
    path = Path(path_text)
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return path.name


def _role_dirs(ws: Workspace) -> dict[str, str]:
    """Job key to the role folder (`roles/<name>`) that lists it."""
    found: dict[str, str] = {}
    for role in list_roles(ws):
        for key in role.job_keys:
            found.setdefault(key, f"roles/{role.name}")
    return found


def _why(snap: Snapshot, key: str) -> str:
    result = snap.ranked.get(key)
    if result is None:
        return "not ranked yet"
    parts = [f"not eligible: {f.reason}" for f in result.flags if f.hard]
    parts += [f.reason for f in result.flags if not f.hard]
    parts += result.reasons
    return truncate("; ".join(parts), WHY_CHARS)


def tracker_rows(snap: Snapshot) -> list[TrackerRow]:
    ws = snap.ws
    roles = _role_dirs(ws)
    rows: list[TrackerRow] = []
    for key in snap.tracked_keys():
        job = snap.jobs[key]
        result = snap.ranked.get(key)
        plan = snap.plans.get(key)
        notes = snap.notes.get(key)
        jd = ws.jd_path(key)
        if plan is not None and plan.resume_path:
            resume = _relative(plan.resume_path, ws.root)  # the file apply will upload
        else:
            resume = roles.get(key, "")
        unknowns = "; ".join(u.label for u in plan.unknowns) if plan else ""
        rows.append(
            TrackerRow(
                key=key,
                company=job.company,
                role=job.title,
                location=job.location,
                tier=(result.tier or "") if result else "",
                score=result.score if result else None,
                eligible=result.eligible if result else None,
                why=_why(snap, key),
                status=snap.status_of(key).value,
                applied_on=day_of(snap.applied_on(key)),
                next_action=notes.next_action if notes else "",
                resume_used=resume,
                plan_status=plan.status.value if plan else "",
                unknowns=truncate(unknowns, UNKNOWN_CHARS),
                job_link=job.url,
                jd_file=jd if jd.is_file() else None,
                posted=day_of(job.posted) or (job.posted or ""),
                first_seen=day_of(job.first_seen),
                change=snap.last_run.change_for(key) if snap.last_run else "",
                notes=notes.notes if notes else "",
                open_queue=len(snap.queue_for(key)),
            )
        )
    return rows


def all_job_rows(snap: Snapshot) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in snap.all_keys_by_score():
        job = snap.jobs[key]
        result = snap.ranked.get(key)
        flags = "; ".join(f"{f.code}: {f.reason}" for f in result.flags) if result else ""
        rows.append(
            {
                "Key": key,
                "Company": job.company,
                "Role": job.title,
                "Location": job.location,
                "Score": result.score if result else None,
                "Eligible": ("yes" if result.eligible else "no") if result else "",
                "Flags": truncate(flags, WHY_CHARS),
                "Status": snap.status_of(key).value,
                "Posting": job.status,
                "Job link": job.url,
                "First seen": day_of(job.first_seen),
            }
        )
    return rows


def jd_text_for(ws: Workspace, snap: Snapshot, key: str) -> str:
    return job_text(ws, snap.jobs[key])


def queue_rows(snap: Snapshot) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group in group_items(snap.queue_open):
        for item in group.items:
            row = item_row(item, snap.jobs)
            rows.append(
                {
                    "ID": item.id,
                    "Kind": item.kind.value,
                    "What we need from you": need_line(item.kind, item.job_key),
                    "Key": item.job_key,
                    "Company": row["company"],
                    "Role": row["role"],
                    "Detail": item.detail,
                    "Link": row["url"] or "",
                    "Since": day_of(item.created_at),
                }
            )
    return rows


def question_rows(groups: list[UnknownGroup]) -> list[dict[str, Any]]:
    return [
        {
            "Question": g.label,
            "Type": g.type.value,
            "Required": "yes" if g.required else "no",
            "Jobs": len(g.jobs),
            "Companies": ", ".join(g.companies),
            "Options": " | ".join(g.options),
            "Why unknown": g.reason,
        }
        for g in groups
    ]


def open_questions(snap: Snapshot) -> list[UnknownGroup]:
    """Unknown questions, once each, counting only jobs you have not applied to or
    dropped yet (an answer no longer matters once the job is past that point)."""
    groups: list[UnknownGroup] = []
    for group in collect_unknowns(snap.ws):
        jobs = [k for k in group.jobs if snap.status_of(k) not in GREEN | GREY]
        if not jobs:
            continue
        companies = list(dict.fromkeys(snap.jobs[k].company for k in jobs if k in snap.jobs))
        groups.append(dataclasses.replace(group, jobs=jobs, companies=companies))
    return groups
