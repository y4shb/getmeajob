"""Which jobs a run may touch: duplicates, exclusions, per-company caps, submit opt-in.

Reads files only (preferences, ledger, status log, plans), so it is tested without a browser.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from getmeajob.errors import ConfigError, GetmeajobError
from getmeajob.files import parse_ts
from getmeajob.models import (
    FORWARD_ORDER,
    SIDE_STATES,
    ApplyMode,
    ApplyStatus,
    AppStatus,
    Job,
    LedgerEntry,
    Plan,
)
from getmeajob.store import StatusLog
from getmeajob.workspace import Workspace
from getmeajob.yamlio import get_path, load_yaml

CAP_WINDOW_DAYS = 30
DEFAULT_CAP = 2
# A job with any of these as its last attempt waits for the human and is not filled again.
WAITING_ON_HUMAN = frozenset(
    {
        ApplyStatus.awaiting_human,
        ApplyStatus.captcha,
        ApplyStatus.account_required,
        ApplyStatus.automation_refused,
    }
)
# Attempts that sent (or may have sent) an application. These count toward the cap.
SENT = frozenset({ApplyStatus.submitted, ApplyStatus.awaiting_human, ApplyStatus.needs_email_code})
SKIPS = frozenset(
    {
        ApplyStatus.skipped_duplicate,
        ApplyStatus.skipped_excluded,
        ApplyStatus.skipped_cap,
        ApplyStatus.skipped_not_ready,
    }
)


@dataclass(slots=True)
class ApplyPrefs:
    submit_boards: list[str] = field(default_factory=list)
    per_company_cap: int = DEFAULT_CAP
    exclude: list[str] = field(default_factory=list)


def _strings(value: object, where: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str | int) for v in value):
        raise ConfigError(
            f"preferences.yaml: '{where}' should be a list of names, not {value!r}.",
            hint=f"Write it like: {where}: [greenhouse, ashby]  (or [] for none).",
        )
    return [str(v).strip() for v in value if str(v).strip()]


def load_apply_prefs(ws: Workspace) -> ApplyPrefs:
    """The `apply:` block of preferences.yaml (defaults when it is missing)."""
    data = load_yaml(ws.preferences_path, required=False)
    cap = get_path(data, "apply.per_company_cap")
    if cap is None:
        cap = DEFAULT_CAP
    if isinstance(cap, bool) or not isinstance(cap, int) or cap < 0:
        raise ConfigError(
            f"preferences.yaml: 'apply.per_company_cap' should be a whole number, not {cap!r}.",
            hint="Use 2 for two applications per company in 30 days, or 0 for no cap.",
        )
    return ApplyPrefs(
        submit_boards=[
            b.casefold()
            for b in _strings(get_path(data, "apply.submit_boards"), "apply.submit_boards")
        ],
        per_company_cap=cap,
        exclude=_strings(get_path(data, "apply.exclude"), "apply.exclude")
        + _strings(data.get("exclude_companies"), "exclude_companies"),
    )


def excluded_by(plan: Plan, exclude: Iterable[str]) -> str | None:
    """The exclusion entry that matches this job: its key, its board slug, or a part of the
    company name (case does not matter). None when the job is not excluded."""
    company = plan.company.casefold()
    slug = Job.board_of(plan.job_key).casefold()
    for entry in exclude:
        want = entry.strip().casefold()
        if want and (want == plan.job_key.casefold() or want == slug or want in company):
            return entry
    return None


def attempts(history: Sequence[LedgerEntry], job_key: str) -> list[LedgerEntry]:
    """Real attempts for a job, oldest first (skips are never written, but be safe)."""
    return [e for e in history if e.job_key == job_key and e.status not in SKIPS]


def duplicate_reason(
    plan: Plan, mode: ApplyMode, history: Sequence[LedgerEntry], current: AppStatus | None
) -> str | None:
    """Why this job must not be filled again, or None.

    Skipped: anything already submitted (by us, or tracked as applied or later), and
    anything whose last attempt waits for the human (a bot check, an account wall, a
    refusal of automated tools, or a submit click with no answer yet). A job waiting for
    an emailed code is left for a hold run.
    """
    applied = FORWARD_ORDER.index(AppStatus.applied)
    if current is not None and current in FORWARD_ORDER and FORWARD_ORDER.index(current) >= applied:
        return f"already {current.value} (from your tracker)"
    tried = attempts(history, plan.job_key)
    if any(e.status == ApplyStatus.submitted for e in tried):
        return "already submitted"
    if not tried:
        return None
    last = tried[-1].status
    if last in WAITING_ON_HUMAN:
        return f"waiting for you since the last run ({last.value}); see: getmeajob queue"
    if last == ApplyStatus.needs_email_code and mode != ApplyMode.hold:
        return "waiting for the emailed code; finish it with --mode hold --headed"
    return None


def sent_recently(
    history: Sequence[LedgerEntry], company: str, now: datetime, days: int = CAP_WINDOW_DAYS
) -> set[str]:
    """Job keys at this company with an application sent (or possibly sent) in the window."""
    since = now - timedelta(days=days)
    keys: set[str] = set()
    for entry in history:
        if entry.status not in SENT or entry.company.casefold() != company.casefold():
            continue
        when = parse_ts(entry.ts)
        if when is not None and when >= since:
            keys.add(entry.job_key)
    return keys


def cap_reason(
    plan: Plan, prefs: ApplyPrefs, history: Sequence[LedgerEntry], now: datetime | None = None
) -> str | None:
    """Why the per-company cap stops this job, or None. The job itself never counts."""
    if prefs.per_company_cap <= 0:
        return None
    now = now or datetime.now(UTC)
    others = sent_recently(history, plan.company, now) - {plan.job_key}
    if len(others) >= prefs.per_company_cap:
        return (
            f"{len(others)} application(s) to {plan.company} in the last {CAP_WINDOW_DAYS} days "
            f"(cap {prefs.per_company_cap}, apply.per_company_cap)"
        )
    return None


def not_ready_reason(plan: Plan, mode: ApplyMode) -> str | None:
    """Why the plan cannot be used in this mode, or None."""
    if plan.status.value != "ready":
        nxt = (
            "getmeajob plan unknowns"
            if plan.status.value == "needs_answers"
            else "getmeajob plan show"
        )
        why = f" ({plan.blocked_reason})" if plan.blocked_reason else ""
        return f"plan is {plan.status.value}{why}; next: {nxt}"
    if mode == ApplyMode.submit and any(a.needs_review for a in plan.answers):
        return (
            "has drafted answers you have not reviewed; run: getmeajob plan review, then "
            f"getmeajob plan approve {plan.job_key} (or --all)"
        )
    return None


def submit_allowed(plan: Plan, prefs: ApplyPrefs) -> bool:
    return plan.ats.casefold() in prefs.submit_boards


def require_opt_in(plans: Sequence[Plan], prefs: ApplyPrefs) -> None:
    """Refuse a submit run unless at least one of its jobs is on an opted-in board."""
    if any(submit_allowed(p, prefs) for p in plans):
        return
    boards = sorted({p.ats for p in plans}) or ["greenhouse", "ashby"]
    listed = ", ".join(prefs.submit_boards) if prefs.submit_boards else "none"
    raise GetmeajobError(
        f"Submit mode is not switched on for {', '.join(boards)} (apply.submit_boards: {listed}).",
        hint=(
            "To let getmeajob click Submit, add the board to apply.submit_boards in "
            f"preferences.yaml (for example submit_boards: [{boards[0]}]). Or use a hold "
            "run and click Submit yourself: getmeajob apply --mode hold --headed"
        ),
    )


def ruled_out(job: Job | None, current: AppStatus | None) -> str | None:
    """Why a job you ruled out (or the board closed) must not be opened, or None."""
    if current is not None and current in SIDE_STATES:
        return f"tracked as {current.value} (from your tracker)"
    if job is not None and job.status == "closed":
        return "the job is closed on the board"
    return None


def skip_reason(
    plan: Plan,
    mode: ApplyMode,
    prefs: ApplyPrefs,
    history: list[LedgerEntry],
    tracker: StatusLog,
    job: Job | None,
    stale: bool,
) -> tuple[ApplyStatus, str] | None:
    """(skip status, why) for a job this run must not open, else None. In order: excluded
    or ruled out, duplicate or waiting, plan not ready or out of date, board not opted in
    (submit), cap (not dry)."""
    entry = excluded_by(plan, prefs.exclude)
    if entry:
        where = "apply.exclude or exclude_companies"
        return ApplyStatus.skipped_excluded, f"matches '{entry}' in {where}"
    current = tracker.current(plan.job_key)
    why = ruled_out(job, current)
    if why:
        return ApplyStatus.skipped_excluded, why
    why = duplicate_reason(plan, mode, history, current)
    if why:
        return ApplyStatus.skipped_duplicate, why
    why = not_ready_reason(plan, mode)
    if why:
        return ApplyStatus.skipped_not_ready, why
    if stale:
        return ApplyStatus.skipped_not_ready, (
            "the plan is out of date (your profile, answers, rules or the job changed); "
            f"run: getmeajob plan {plan.job_key}"
        )
    if mode == ApplyMode.submit and not submit_allowed(plan, prefs):
        return ApplyStatus.skipped_not_ready, f"{plan.ats} is not in apply.submit_boards"
    if mode != ApplyMode.dry:
        why = cap_reason(plan, prefs, history, datetime.now(UTC))
        if why:
            return ApplyStatus.skipped_cap, why
    return None
