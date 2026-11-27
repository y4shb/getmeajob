"""Answering one question: your saved answer first, then the rules.

Saved answers are checked against the question (an option must match, a file must
exist). A file must sit inside the workspace or be `files.resume` or `files.cover_letter`;
the resume can come from a tailored role folder. Required questions without a truthful
answer become `UnknownQuestion`s; optional ones become blank answers with source `skip`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from getmeajob.models import Job, PlannedAnswer, Question, QuestionType, UnknownQuestion
from getmeajob.plan.options import match_many, match_option
from getmeajob.plan.overrides import Answers, entry_value, lookup
from getmeajob.plan.profile import Profile, is_blank
from getmeajob.plan.rules import Rule, answer_question
from getmeajob.resume.store import role_for_key
from getmeajob.textutil import html_to_text, norm_label, options_hash, truncate
from getmeajob.workspace import Workspace

CHOICES = (QuestionType.select, QuestionType.boolean)


def dedupe_key(q: Question) -> str:
    """Normalised label plus a hash of the option labels."""
    return f"{norm_label(q.label)}#{options_hash(o.label for o in q.options)}"


def resume_for(ws: Workspace, profile: Profile, key: str) -> str | None:
    """A tailored `roles/<dir>/resume.pdf` listing this job, else `files.resume`."""
    role = role_for_key(ws, key)
    if role is not None and (role / "resume.pdf").is_file():
        return str((role / "resume.pdf").resolve())
    return allowed_file(ws, profile, profile.text("files.resume"))[0]


def _resolve(ws: Workspace, name: str) -> Path:
    path = Path(name).expanduser()
    return (path if path.is_absolute() else ws.root / path).resolve()


def allowed_file(ws: Workspace, profile: Profile, name: str | None) -> tuple[str | None, str]:
    """(full path, problem) for a file to attach: it must exist and sit inside the
    workspace, or be the `files.resume` or `files.cover_letter` of the profile."""
    if not name:
        return None, "no file was given"
    path = _resolve(ws, name)
    if not path.is_file():
        return None, f"the file {name!r} was not found"
    named = [profile.text("files.resume"), profile.text("files.cover_letter")]
    if path.is_relative_to(ws.root.resolve()) or path in {_resolve(ws, n) for n in named if n}:
        return str(path), ""
    return None, (
        f"the file {name!r} is outside the workspace and is not files.resume or "
        "files.cover_letter, so getmeajob will not attach it"
    )


def validate_saved(
    ws: Workspace, profile: Profile, q: Question, value: Any
) -> tuple[str | list[str] | None, str]:
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
        return allowed_file(ws, profile, str(value))
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
        value, problem = validate_saved(ws, profile, q, raw)
        if value is not None and not is_blank(value):
            source = origin if origin in ("draft", "agent") else source
            return PlannedAnswer(q.id, q.label, q.type, value, source, needs_review)
        if q.required:
            return unknown_question(q, problem)
        return PlannedAnswer(q.id, q.label, q.type, None, "skip", note=problem)
    outcome = answer_question(q, profile, rules, job.company, job=job)
    value = outcome.value
    if outcome.source == "file":
        reason = f"the file {outcome.value!r} was not found"
        if value != profile.text("files.resume"):
            value, reason = allowed_file(ws, profile, str(value))
        else:
            value = resume_path
        if value is None:
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
