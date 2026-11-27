"""Shared data types.

Every dataclass has `to_dict()` (JSON-safe, enums as their values) and
`from_dict()` (ignores unknown keys, fills defaults). Records are stored as JSON
and JSONL in the workspace, so these two methods are the storage format.
"""

from __future__ import annotations

import dataclasses
from enum import StrEnum

from getmeajob.serial import Model

# --------------------------------------------------------------------------- enums


class QuestionType(StrEnum):
    text = "text"
    textarea = "textarea"
    select = "select"
    multiselect = "multiselect"
    boolean = "boolean"
    file = "file"
    location = "location"
    date = "date"
    number = "number"
    email = "email"
    phone = "phone"
    url = "url"
    hidden = "hidden"
    education_history = "education_history"
    unknown = "unknown"


class PlanStatus(StrEnum):
    ready = "ready"
    needs_answers = "needs_answers"
    schema_unavailable = "schema_unavailable"
    blocked = "blocked"


class ApplyMode(StrEnum):
    dry = "dry"
    hold = "hold"
    submit = "submit"


class ApplyStatus(StrEnum):
    dry_ok = "dry_ok"
    submitted = "submitted"
    awaiting_human = "awaiting_human"
    needs_email_code = "needs_email_code"
    captcha = "captcha"
    account_required = "account_required"
    automation_refused = "automation_refused"
    validation_error = "validation_error"
    fill_problem = "fill_problem"
    skipped_duplicate = "skipped_duplicate"
    skipped_excluded = "skipped_excluded"
    skipped_cap = "skipped_cap"
    skipped_not_ready = "skipped_not_ready"
    closed_by_user = "closed_by_user"
    timeout = "timeout"
    error = "error"


class QueueKind(StrEnum):
    needs_email_code = "needs_email_code"
    needs_answers = "needs_answers"
    captcha = "captcha"
    account_required = "account_required"
    automation_refused = "automation_refused"
    validation_error = "validation_error"
    fill_problem = "fill_problem"
    manual = "manual"


class AppStatus(StrEnum):
    discovered = "discovered"
    shortlisted = "shortlisted"
    planned = "planned"
    ready = "ready"
    applied = "applied"
    screening = "screening"
    interviewing = "interviewing"
    offer = "offer"
    accepted = "accepted"
    rejected = "rejected"
    withdrawn = "withdrawn"
    closed = "closed"
    skipped = "skipped"
    ghosted = "ghosted"


FORWARD_ORDER: tuple[AppStatus, ...] = (
    AppStatus.discovered,
    AppStatus.shortlisted,
    AppStatus.planned,
    AppStatus.ready,
    AppStatus.applied,
    AppStatus.screening,
    AppStatus.interviewing,
    AppStatus.offer,
    AppStatus.accepted,
)

SIDE_STATES: frozenset[AppStatus] = frozenset(
    {
        AppStatus.rejected,
        AppStatus.withdrawn,
        AppStatus.closed,
        AppStatus.skipped,
        AppStatus.ghosted,
    }
)

# ---------------------------------------------------------------------- records


@dataclasses.dataclass(slots=True)
class Board(Model):
    company: str
    ats: str
    slug: str
    enabled: bool = True
    careers_url: str | None = None
    region: str | None = None
    verified: bool = True
    notes: str | None = None


@dataclasses.dataclass(slots=True)
class Job(Model):
    key: str
    ats: str
    board: str
    job_id: str
    company: str
    title: str
    url: str
    location: str = ""
    remote: bool | None = None
    workplace: str | None = None
    apply_url: str | None = None
    posted: str | None = None
    department: str | None = None
    comp: str | None = None
    description: str = ""
    source: str = "api"
    first_seen: str = ""
    last_seen: str = ""
    status: str = "open"

    @staticmethod
    def make_key(ats: str, board: str, job_id: str) -> str:
        return f"{ats}:{board}:{job_id}"

    @staticmethod
    def board_of(key: str) -> str:
        """The board slug inside a key made by `make_key` ("" when it has none)."""
        parts = key.split(":")
        return parts[1] if len(parts) > 2 else ""


@dataclasses.dataclass(slots=True)
class Flag(Model):
    code: str
    reason: str
    hard: bool = True


@dataclasses.dataclass(slots=True)
class RankResult(Model):
    key: str
    score: int
    eligible: bool
    tier: str | None
    track: str | None
    yoe_min: int | None
    yoe_max: int | None
    reasons: list[str]
    flags: list[Flag]
    skills_hit: list[str]
    skills_missing: list[str]
    ranked_at: str


@dataclasses.dataclass(slots=True)
class Option(Model):
    label: str
    value: str | None = None


@dataclasses.dataclass(slots=True)
class Question(Model):
    id: str
    label: str
    type: QuestionType
    required: bool = False
    options: list[Option] = dataclasses.field(default_factory=list)
    description: str = ""
    section: str | None = None
    board_type: str | None = None
    max_length: int | None = None


@dataclasses.dataclass(slots=True)
class PlannedAnswer(Model):
    """`source` is one of rule:<rule_id>, override:job, override:company,
    override:global, file, skip, draft."""

    question_id: str
    label: str
    type: QuestionType
    value: str | list[str] | None
    source: str
    needs_review: bool = False
    note: str = ""


@dataclasses.dataclass(slots=True)
class UnknownQuestion(Model):
    question_id: str
    label: str
    type: QuestionType
    required: bool
    options: list[str]
    reason: str
    dedupe_key: str
    description: str = ""


@dataclasses.dataclass(slots=True)
class Plan(Model):
    job_key: str
    ats: str
    company: str
    title: str
    url: str
    form_url: str
    status: PlanStatus
    answers: list[PlannedAnswer]
    unknowns: list[UnknownQuestion]
    resume_path: str | None = None
    blocked_reason: str | None = None
    schema_hash: str = ""
    inputs_hash: str = ""
    created_at: str = ""


@dataclasses.dataclass(slots=True)
class LedgerEntry(Model):
    ts: str
    run_id: str
    job_key: str
    company: str
    title: str
    mode: ApplyMode
    status: ApplyStatus
    detail: str = ""
    problems: list[str] = dataclasses.field(default_factory=list)
    screenshot: str | None = None
    plan_path: str | None = None
    answers_digest: str | None = None
    url: str | None = None


@dataclasses.dataclass(slots=True)
class QueueItem(Model):
    id: str
    job_key: str
    kind: QueueKind
    detail: str
    url: str | None
    created_at: str
    resolved_at: str | None = None
    resolution: str | None = None


@dataclasses.dataclass(slots=True)
class StatusEvent(Model):
    """`source` is one of manual, xlsx, source, rank, plan, apply, liveness."""

    ts: str
    job_key: str
    status: AppStatus
    source: str
    note: str = ""
