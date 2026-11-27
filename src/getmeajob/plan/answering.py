"""Answering one question: your saved answer first, then the rules.

Saved answers are checked against the question (an option must match, a file must
exist). Files from the rules are resolved inside the workspace; the resume can come
from a tailored role folder. Required questions without a truthful answer become
`UnknownQuestion`s; optional ones become blank answers with source `skip`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from getmeajob.errors import GetmeajobError
from getmeajob.models import Job, PlannedAnswer, Question, QuestionType, UnknownQuestion
from getmeajob.plan.options import match_many, match_option
from getmeajob.plan.overrides import Answers, entry_value, lookup
from getmeajob.plan.profile import Profile, is_blank
from getmeajob.plan.rules import Rule, answer_question
from getmeajob.textutil import html_to_text, norm_label, options_hash, truncate
from getmeajob.workspace import Workspace
from getmeajob.yamlio import load_yaml

CHOICES = (QuestionType.select, QuestionType.boolean)


def dedupe_key(q: Question) -> str:
    """Normalised label plus a hash of the option labels."""
    return f"{norm_label(q.label)}#{options_hash(o.label for o in q.options)}"


def resume_for(ws: Workspace, profile: Profile, key: str) -> str | None:
    """A tailored `roles/<dir>/resume.pdf` listing this job, else `files.resume`."""
    for meta in sorted(ws.roles_dir.glob("*/meta.yaml")):
        try:
            data = load_yaml(meta, required=False)
        except GetmeajobError:
            continue
        keys = data.get("job_keys") or []
        pdf = meta.parent / "resume.pdf"
        if isinstance(keys, list) and key in keys and pdf.is_file():
            return str(pdf.resolve())
    return workspace_file(ws, profile.text("files.resume"))


def workspace_file(ws: Workspace, rel: str | None) -> str | None:
    if not rel:
        return None
    path = Path(rel).expanduser()
    path = path if path.is_absolute() else ws.root / path
    return str(path.resolve()) if path.is_file() else None


def validate_saved(ws: Workspace, q: Question, value: Any) -> tuple[str | list[str] | None, str]:
    """Check a saved answer against the question. Returns (value, problem)."""
    options = [o.label for o in q.options] or (
        ["Yes", "No"] if q.type == QuestionType.boolean else []
    )
    if q.type in CHOICES and options:
        desired: Any = value if isinstance(value, bool) else str(value)
        result = match_option(desired, options)
        if result.option is None:
            return None, f"your saved answer {value!r} is not one of the options ({result.reason})"
        return result.option, ""
    if q.type == QuestionType.multiselect and options:
        wanted = value if isinstance(value, list) else [value]
        chosen, problems = match_many([str(v) for v in wanted], options)
        if problems:
            return None, f"your saved answer does not fit the options: {problems[0]}"
        return chosen, ""
    if q.type == QuestionType.file:
        found = workspace_file(ws, str(value))
        return (found, "") if found else (None, f"the file {value!r} was not found")
    if isinstance(value, list):
        return ", ".join(str(v) for v in value), ""
    if isinstance(value, bool):
        return ("Yes" if value else "No"), ""
    return str(value).strip(), ""


def unknown_question(q: Question, reason: str) -> UnknownQuestion:
    return UnknownQuestion(
        question_id=q.id,
        label=q.label,
        type=q.type,
        required=q.required,
        options=[o.label for o in q.options],
        reason=reason,
        dedupe_key=dedupe_key(q),
        description=truncate(q.description or "", 300),
    )


def answer_one(
    ws: Workspace,
    job: Job,
    q: Question,
    profile: Profile,
    rules: Sequence[Rule],
    answers: Answers,
    resume_path: str | None,
) -> PlannedAnswer | UnknownQuestion:
    hit = lookup(answers, job, q)
    if hit is not None:
        entry, source = hit
        raw, needs_review, origin = entry_value(entry)
        value, problem = validate_saved(ws, q, raw)
        if value is not None and not is_blank(value):
            source = "draft" if origin == "draft" else source
            return PlannedAnswer(q.id, q.label, q.type, value, source, needs_review)
        if q.required:
            return unknown_question(q, problem)
        return PlannedAnswer(q.id, q.label, q.type, None, "skip", note=problem)
    outcome = answer_question(q, profile, rules, job.company, job=job)
    value = outcome.value
    if outcome.source == "file":
        is_resume = value == profile.text("files.resume")
        value = resume_path if is_resume else workspace_file(ws, str(value))
        if value is None:
            reason = f"the file {outcome.value!r} was not found in the workspace"
            if q.required:
                return unknown_question(q, reason)
            return PlannedAnswer(q.id, q.label, q.type, None, "skip", note=reason)
    if outcome.source == "unknown":
        return unknown_question(q, outcome.reason)
    return PlannedAnswer(q.id, q.label, q.type, value, outcome.source, note=outcome.reason)


def find_refusal(questions: Iterable[Question], patterns: Sequence[re.Pattern[str]]) -> str | None:
    """The first "do not use automated tools" text in a label or description, if any."""
    for q in questions:
        text = f"{norm_label(q.label)}\n{html_to_text(q.description or '').casefold()}"
        for pattern in patterns:
            found = pattern.search(text)
            if found:
                return truncate(found.group(0), 120)
    return None
