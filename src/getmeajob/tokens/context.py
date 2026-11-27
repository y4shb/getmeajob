"""`getmeajob context KEY`: the smallest useful pack about one job for an agent.

Under 2,000 characters (about 500 tokens, estimate): the job, a JD digest, the rank
score with reasons and flags, the plan status and its open questions, and the resume
folder with its keyword gaps. Nothing else is read into the agent's context.
"""

from __future__ import annotations

from typing import Any

from getmeajob.files import read_json
from getmeajob.models import Job
from getmeajob.rank.score import job_text
from getmeajob.resume.store import role_for_key
from getmeajob.sources.jd import jd_digest
from getmeajob.store import JobStore
from getmeajob.textutil import truncate
from getmeajob.track.snapshot import load_snapshot
from getmeajob.workspace import Workspace
from getmeajob.yamlio import load_yaml

BUDGET = 1_900  # leaves room for the line break and a caller's own framing
LINE_CHARS = 160
LIST_MAX = 5
_DIGEST_SKIP = ("where:", "key:", "link:", "text:")


def _digest(ws: Workspace, job: Job, text: str) -> list[str]:
    prefs = load_yaml(ws.preferences_path, required=False)
    lines = jd_digest(job, text, prefs)[1:]  # the first line repeats the title
    kept = [line for line in lines if not line.startswith(_DIGEST_SKIP)]
    if text.strip():
        kept.append(f"text: {len(text):,} chars; more: getmeajob jd {job.key} --grep WORD")
    return kept


def _resume(ws: Workspace, key: str) -> dict[str, Any] | None:
    folder = role_for_key(ws, key)
    if folder is None:
        return None
    report = read_json(folder / "report.json", default={})
    report = report if isinstance(report, dict) else {}
    return {
        "folder": f"roles/{folder.name}",
        "has_pdf": (folder / "resume.pdf").is_file(),
        "gaps": [str(k) for k in report.get("gaps_not_in_bank") or []],
        "unused_in_bank": [str(k) for k in report.get("unused_in_bank") or []],
    }


def context_pack(ws: Workspace, job: Job) -> dict[str, Any]:
    snap = load_snapshot(ws)
    key = job.key
    result = snap.ranked.get(key)
    plan = snap.plans.get(key)
    return {
        "key": key,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "workplace": job.workplace,
        "url": job.url,
        "status": snap.status_of(key).value,
        "jd": _digest(ws, job, job_text(ws, job)),
        "rank": None
        if result is None
        else {
            "score": result.score,
            "eligible": result.eligible,
            "tier": result.tier,
            "track": result.track,
            "reasons": result.reasons,
            "flags": [f"{f.code}: {f.reason}" for f in result.flags],
        },
        "plan": None
        if plan is None
        else {"status": plan.status.value, "unknowns": [u.label for u in plan.unknowns]},
        "resume": _resume(ws, key),
        "queue": [f"{i.kind.value} (item {i.id})" for i in snap.queue_for(key)],
    }


def _short(text: str) -> str:
    return truncate(" ".join(text.split()), LINE_CHARS)


def context_text(pack: dict[str, Any]) -> str:
    where = pack["location"] or "location not given"
    if pack["workplace"] and pack["workplace"] not in where.casefold():
        where += f" ({pack['workplace']})"
    lines = [
        f"job: {pack['title']} at {pack['company']}",
        f"key: {pack['key']} | status: {pack['status']}",
        f"where: {where}",
        f"url: {pack['url']}",
        "jd:",
        *(f"  {_short(line)}" for line in pack["jd"]),
    ]
    rank = pack["rank"]
    if rank is None:
        lines.append("rank: not ranked yet (getmeajob rank)")
    else:
        verdict = "eligible" if rank["eligible"] else "NOT eligible"
        lines.append(
            f"rank: {rank['score']}/100, {verdict}, tier {rank['tier']}, track {rank['track']}"
        )
        lines += [f"  - {_short(r)}" for r in rank["reasons"][:LIST_MAX]]
        lines += [f"  ! {_short(f)}" for f in rank["flags"][:LIST_MAX]] or ["  flags: none"]
        if len(rank["flags"]) > LIST_MAX:
            lines.append(
                f"  ! and {len(rank['flags']) - LIST_MAX} more: getmeajob explain {pack['key']}"
            )
    plan = pack["plan"]
    if plan is None:
        lines.append("plan: none yet")
    else:
        lines.append(f"plan: {plan['status']}, {len(plan['unknowns'])} unknown(s)")
        lines += [f"  ? {_short(u)}" for u in plan["unknowns"][:LIST_MAX]]
    resume = pack["resume"]
    if resume is None:
        lines.append(f"resume: none tailored (getmeajob resume tailor {pack['key']})")
    else:
        pdf = "pdf ready" if resume["has_pdf"] else "no pdf yet"
        gaps = ", ".join(resume["gaps"]) or "none"
        lines.append(f"resume: {resume['folder']} ({pdf}); keyword gaps: {_short(gaps)}")
    if pack["queue"]:
        lines.append("waiting on you: " + ", ".join(pack["queue"]))
    text = "\n".join(lines)
    return text if len(text) <= BUDGET else truncate(text, BUDGET)


def find_job_by_key(ws: Workspace, key: str) -> Job:
    return JobStore(ws).find(key)


def context_for(ws: Workspace, key: str) -> str:
    """The context pack for one job as text (for agents and the MCP server)."""
    return context_text(context_pack(ws.require(), JobStore(ws).find(key)))
