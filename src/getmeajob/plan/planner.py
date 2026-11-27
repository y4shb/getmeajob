"""Build a form plan per job: every question with its answer, or as an unknown.

Order per question: your saved answer (answers.yaml, checked against the options), else
the first rule that fits. Required questions nobody can answer truthfully become
unknowns and the plan is `needs_answers`; optional ones are left blank (`skip`).
Text asking candidates not to use automated tools blocks the plan.

A plan is stored in `data/plans/<key>.json` with an `inputs_hash` of everything it
depends on, so re-running with unchanged inputs reuses it and writes nothing.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from getmeajob.files import now_iso, read_jsonl, write_json_atomic
from getmeajob.http import HttpClient, client_for
from getmeajob.models import AppStatus, Job, Plan, PlanStatus, QueueKind, UnknownQuestion
from getmeajob.plan.answering import answer_one, find_refusal, resume_for
from getmeajob.plan.overrides import Answers, load_answers
from getmeajob.plan.plans import all_plans, load_plan
from getmeajob.plan.profile import Profile, load_profile
from getmeajob.plan.rules import Rule, load_refusal_patterns, load_rules
from getmeajob.plan.schema import (
    FORM_ATS,
    PageReader,
    SchemaUnavailable,
    fetch_schema,
    form_url,
    schema_hash,
)
from getmeajob.store import JobStore, QueueLog, StatusLog
from getmeajob.textutil import norm_label, short_hash, truncate
from getmeajob.workspace import Workspace
from getmeajob.yamlio import get_path, load_yaml

__all__ = ["PlanRun", "all_plans", "load_plan", "plan_job", "plan_many", "plan_run", "shortlist"]

PLANNER_VERSION = "1"
DEFAULT_SHORTLIST = 60


@dataclass
class PlanRun:
    plans: list[Plan] = field(default_factory=list)
    reused: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    ranked_missing: bool = False


# ------------------------------------------------------------------- inputs


def _rules_signature(rules: Sequence[Rule], refusal: Sequence[re.Pattern[str]]) -> str:
    parts = [
        [
            r.id,
            [p.pattern for p in r.match],
            [p.pattern for p in r.exclude],
            r.kind,
            r.field,
            r.options_pref,
            sorted(t.value for t in r.types or ()),
        ]
        for r in rules
    ]
    return short_hash(json.dumps([parts, [p.pattern for p in refusal]], sort_keys=True))


def _answers_signature(answers: Answers, job: Job) -> str:
    company = {
        k: v
        for k, v in answers.by_company.items()
        if k.casefold() == job.board.casefold() or norm_label(k) == norm_label(job.company)
    }
    relevant = [answers.global_, company, answers.by_job.get(job.key) or {}]
    return short_hash(json.dumps(relevant, sort_keys=True, default=str))


def _file_sig(path: str | None) -> str:
    if path is None:
        return "-"
    stat = Path(path).stat()
    return f"{path}:{stat.st_size}:{stat.st_mtime_ns}"


# ------------------------------------------------------------------ planning


def _record(ws: Workspace, plan: Plan, url: str, refused: str = "") -> None:
    """Queue items and status events for a freshly written plan."""
    queue = QueueLog(ws)
    status = StatusLog(ws)
    if plan.status == PlanStatus.blocked:
        detail = f'The form asks applicants not to use automated tools: "{refused}"'
        queue.add(plan.job_key, QueueKind.automation_refused, detail, url)
        queue.resolve(plan.job_key, QueueKind.needs_answers, "blocked: the form refuses tools")
        return
    queue.resolve(plan.job_key, QueueKind.automation_refused, "the form no longer refuses tools")
    if plan.status == PlanStatus.needs_answers:
        labels = "; ".join(truncate(u.label, 60) for u in plan.unknowns[:3])
        more = f" and {len(plan.unknowns) - 3} more" if len(plan.unknowns) > 3 else ""
        detail = f"{len(plan.unknowns)} question(s) need your answer: {labels}{more}"
        queue.add(plan.job_key, QueueKind.needs_answers, detail, url)
        status.record(plan.job_key, AppStatus.planned, "plan")
    elif plan.status == PlanStatus.ready:
        queue.resolve(plan.job_key, QueueKind.needs_answers, "answered")
        status.record(plan.job_key, AppStatus.planned, "plan")
        status.record(plan.job_key, AppStatus.ready, "plan")


def _base_plan(job: Job, status: PlanStatus) -> Plan:
    return Plan(
        job_key=job.key,
        ats=job.ats,
        company=job.company,
        title=job.title,
        url=job.url,
        form_url=form_url(job),
        status=status,
        answers=[],
        unknowns=[],
        created_at=now_iso(),
    )


def _plan_job(
    ws: Workspace,
    client: HttpClient,
    job: Job,
    profile: Profile,
    rules: Sequence[Rule],
    answers: Answers,
    *,
    refresh: bool,
    page_reader: PageReader | None | bool,
    refusal: Sequence[re.Pattern[str]],
) -> tuple[Plan, bool]:
    existing = load_plan(ws, job.key)
    try:
        questions = fetch_schema(ws, client, job, refresh=refresh, page_reader=page_reader)
    except SchemaUnavailable as exc:
        plan = _base_plan(job, PlanStatus.schema_unavailable)
        plan.blocked_reason = exc.message
        same = existing is not None and existing.status == plan.status
        if same and existing is not None and existing.blocked_reason == plan.blocked_reason:
            return existing, True
        write_json_atomic(ws.plan_path(job.key), plan.to_dict())
        return plan, False
    shash = schema_hash(questions)
    resume_path = resume_for(ws, profile, job.key)
    inputs = short_hash(
        json.dumps(
            [
                PLANNER_VERSION,
                shash,
                profile.digest(),
                _answers_signature(answers, job),
                _rules_signature(rules, refusal),
                _file_sig(resume_path),
                [job.company, job.title, job.location, job.remote, job.workplace, job.board],
            ],
            default=str,
        )
    )
    if existing is not None and existing.inputs_hash == inputs and not refresh:
        return existing, True
    plan = _base_plan(job, PlanStatus.ready)
    plan.schema_hash, plan.inputs_hash, plan.resume_path = shash, inputs, resume_path
    refused = find_refusal(questions, refusal)
    if refused is not None:
        plan.status, plan.blocked_reason = PlanStatus.blocked, "automation_refused"
        plan.unknowns = []
        write_json_atomic(ws.plan_path(job.key), plan.to_dict())
        _record(ws, plan, plan.form_url, refused)
        return plan, False
    for q in questions:
        result = answer_one(ws, job, q, profile, rules, answers, resume_path)
        if isinstance(result, UnknownQuestion):
            plan.unknowns.append(result)
        else:
            plan.answers.append(result)
    plan.status = PlanStatus.needs_answers if plan.unknowns else PlanStatus.ready
    write_json_atomic(ws.plan_path(job.key), plan.to_dict())
    _record(ws, plan, plan.form_url)
    return plan, False


def plan_job(
    ws: Workspace,
    client: HttpClient,
    job: Job,
    profile: Profile,
    rules: Sequence[Rule],
    answers: Answers,
    *,
    refresh: bool = False,
    page_reader: PageReader | None | bool = True,
) -> Plan:
    """Plan one job and store it in `data/plans/<key>.json` (reused when inputs match)."""
    plan, _ = _plan_job(
        ws,
        client,
        job,
        profile,
        rules,
        answers,
        refresh=refresh,
        page_reader=page_reader,
        refusal=load_refusal_patterns(ws),
    )
    return plan


def shortlist(ws: Workspace, min_score: int | None) -> tuple[list[str], bool]:
    """Eligible ranked jobs at or above the threshold, best first, and whether
    `data/ranked.jsonl` was missing."""
    if not ws.ranked_path.exists():
        return [], True
    if min_score is None:
        prefs = load_yaml(ws.preferences_path, required=False)
        raw = get_path(prefs, "thresholds.shortlist")
        min_score = (
            int(raw)
            if isinstance(raw, int | float) and not isinstance(raw, bool)
            else DEFAULT_SHORTLIST
        )
    rows = [r for r in read_jsonl(ws.ranked_path) if r.get("eligible") is True]
    rows = [r for r in rows if isinstance(r.get("score"), int | float) and r["score"] >= min_score]
    rows.sort(key=lambda r: -float(r["score"]))
    return [str(r["key"]) for r in rows if r.get("key")], False


def plan_run(
    ws: Workspace,
    keys: Sequence[str] | None,
    *,
    min_score: int | None = None,
    refresh: bool = False,
    client: HttpClient | None = None,
    page_reader: PageReader | None | bool = True,
) -> PlanRun:
    """Plan the given jobs, or by default the shortlisted ranked jobs with forms."""
    ws.require()
    run = PlanRun()
    if keys:
        selected = list(dict.fromkeys(keys))
    else:
        selected, run.ranked_missing = shortlist(ws, min_score)
    if not selected:
        return run
    profile, rules, answers = load_profile(ws), load_rules(ws), load_answers(ws)
    refusal = load_refusal_patterns(ws)
    jobs = JobStore(ws).load()
    own_client = client is None
    http = client if client is not None else client_for(ws)
    try:
        for key in selected:
            job = jobs.get(key)
            if job is None:
                run.skipped.append((key, "not in data/jobs.jsonl (run getmeajob source)"))
                continue
            if job.ats not in FORM_ATS:
                run.skipped.append((key, f"{job.ats} forms are not supported yet"))
                continue
            plan, reused = _plan_job(
                ws,
                http,
                job,
                profile,
                rules,
                answers,
                refresh=refresh,
                page_reader=page_reader,
                refusal=refusal,
            )
            run.plans.append(plan)
            if reused:
                run.reused.append(key)
    finally:
        if own_client:
            http.close()
    return run


def plan_many(
    ws: Workspace,
    keys: Sequence[str] | None,
    *,
    min_score: int | None = None,
    refresh: bool = False,
) -> list[Plan]:
    """Plan many jobs (see `plan_run`) and return the plans."""
    return plan_run(ws, keys, min_score=min_score, refresh=refresh).plans
