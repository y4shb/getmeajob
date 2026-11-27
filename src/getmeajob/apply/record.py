"""Writing down what an apply attempt did: ledger entry, queue item, status event.

The ledger never holds answer text. It keeps a digest of the answers (to notice that
they changed) and the path of the plan file, which has the answers themselves. Detail
and problem lines are scrubbed of every planned value before they are stored.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from getmeajob.models import ApplyMode, ApplyStatus, AppStatus, LedgerEntry, Plan, QueueKind
from getmeajob.store import Ledger, QueueLog, StatusLog, now_iso
from getmeajob.workspace import Workspace

REDACTED = "[answer]"
MIN_SCRUB = 4

QUEUE_KIND = {
    ApplyStatus.captcha: QueueKind.captcha,
    ApplyStatus.account_required: QueueKind.account_required,
    ApplyStatus.automation_refused: QueueKind.automation_refused,
    ApplyStatus.fill_problem: QueueKind.fill_problem,
    ApplyStatus.validation_error: QueueKind.validation_error,
    ApplyStatus.needs_email_code: QueueKind.needs_email_code,
    ApplyStatus.awaiting_human: QueueKind.manual,
    ApplyStatus.timeout: QueueKind.manual,
}


@dataclass(slots=True)
class Outcome:
    """The result of one attempt, before it is written down."""

    status: ApplyStatus
    detail: str = ""
    problems: list[str] = field(default_factory=list)
    screenshot: Path | None = None


def new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(2)


def answers_digest(plan: Plan) -> str:
    """A hash of the planned answers (question id and value), never the answers themselves."""
    pairs = sorted((a.question_id, a.value) for a in plan.answers if a.value not in (None, ""))
    blob = json.dumps(pairs, ensure_ascii=False, default=str, sort_keys=True)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _values(plan: Plan) -> list[str]:
    """Answer values worth hiding: 4 characters or more, and not part of the job's own
    public text (a last name that is also in the company name hides nothing)."""
    public = " ".join((plan.job_key, plan.company, plan.title, plan.url, plan.form_url))
    public = public.casefold()
    found: list[str] = []
    for answer in plan.answers:
        items = answer.value if isinstance(answer.value, list) else [answer.value]
        for item in items:
            text = str(item or "").strip()
            if len(text) >= MIN_SCRUB and text.casefold() not in public:
                found.append(text)
    return sorted(set(found), key=len, reverse=True)


def scrub(text: str, plan: Plan) -> str:
    """`text` with every planned answer value (see `_values`) replaced."""
    for value in _values(plan):
        text = re.sub(re.escape(value), REDACTED, text, flags=re.IGNORECASE)
    return text


def _rel(ws: Workspace, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(ws.root.resolve()))
    except ValueError:
        return str(path)


def make_entry(
    ws: Workspace, plan: Plan, mode: ApplyMode, outcome: Outcome, run_id: str
) -> LedgerEntry:
    """The ledger record for an attempt (or a skip), with answer text scrubbed out."""
    return LedgerEntry(
        ts=now_iso(),
        run_id=run_id,
        job_key=plan.job_key,
        company=plan.company,
        title=plan.title,
        mode=mode,
        status=outcome.status,
        detail=scrub(outcome.detail, plan),
        problems=[scrub(p, plan) for p in outcome.problems],
        screenshot=_rel(ws, outcome.screenshot),
        plan_path=_rel(ws, ws.plan_path(plan.job_key)),
        answers_digest=answers_digest(plan),
        url=plan.form_url,
    )


def queue_text(entry: LedgerEntry) -> str | None:
    """What the human needs to do for this result, or None when nothing is needed."""
    key = entry.job_key
    hold = f"getmeajob apply {key} --mode hold --headed"
    why = f" ({entry.detail})" if entry.detail else ""
    problems = "; ".join(entry.problems[:4])
    texts = {
        ApplyStatus.captcha: (
            f"A bot check appeared{why}. getmeajob never solves these and will not try this "
            "job again. Apply by hand at the link if you still want it."
        ),
        ApplyStatus.account_required: (
            f"The form wants you to sign in or create an account{why}. getmeajob never "
            "creates accounts. Apply by hand at the link."
        ),
        ApplyStatus.automation_refused: (
            f"The form asks people not to use automated tools{why}. Apply by hand at the "
            "link if you want this job."
        ),
        ApplyStatus.fill_problem: (
            f"Some fields could not be filled: {problems}. Check the answers with "
            f"`getmeajob plan show {key}` or your profile, then run a dry run again."
        ),
        ApplyStatus.validation_error: (
            f"The form rejected some fields: {problems or entry.detail}. Check the plan, "
            f"then finish it in a hold run: {hold}"
        ),
        ApplyStatus.needs_email_code: (
            "The board emailed you a security code. Finish it in a hold run and type the "
            f"code in the window: {hold} --click-submit"
        ),
        ApplyStatus.awaiting_human: (
            "Submit was clicked once but no confirmation appeared. Check your email or the "
            f"careers site. If it went through: getmeajob track set {key} applied"
        ),
        ApplyStatus.timeout: f"The hold run ended before the form was finished. Run: {hold}",
    }
    return texts.get(entry.status)


def write_attempt(ws: Workspace, entry: LedgerEntry, *, extra_problems: bool = False) -> None:
    """Append the ledger entry and update the queue and the status log.

    `extra_problems` adds a fill_problem item next to the main result (a hold run where
    the human did not finish a form that had fields getmeajob could not fill).
    """
    Ledger(ws).append(entry)
    queue = QueueLog(ws)
    if entry.status == ApplyStatus.submitted:
        StatusLog(ws).record(entry.job_key, AppStatus.applied, "apply", note=f"run {entry.run_id}")
        queue.resolve(entry.job_key, None, "submitted")
        return
    if entry.status == ApplyStatus.dry_ok:
        queue.resolve(entry.job_key, QueueKind.fill_problem, "a dry run filled every field")
    kind = QUEUE_KIND.get(entry.status)
    text = queue_text(entry)
    if kind is not None and text is not None:
        queue.add(entry.job_key, kind, text, url=entry.url)
    if extra_problems and entry.problems and entry.status != ApplyStatus.fill_problem:
        problem_entry = LedgerEntry.from_dict({**entry.to_dict(), "status": "fill_problem"})
        problem_text = queue_text(problem_entry)
        if problem_text:
            queue.add(entry.job_key, QueueKind.fill_problem, problem_text, url=entry.url)
