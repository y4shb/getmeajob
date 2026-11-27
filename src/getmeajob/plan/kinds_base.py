"""Shared pieces for the answer kinds: the context object and value helpers.

`choose` maps a profile value onto a question: one option for choice questions (with
the shared matcher, which never guesses), checked text for number and date fields,
plain text otherwise. `unknown` is the honest "the profile does not settle this".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from getmeajob.models import Job, Question, QuestionType
from getmeajob.plan.options import match_option
from getmeajob.plan.profile import Profile, is_blank
from getmeajob.plan.rules import Rule, RuleOutcome
from getmeajob.textutil import norm_label

CHOICE_TYPES = frozenset({QuestionType.select, QuestionType.multiselect, QuestionType.boolean})
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class Ctx:
    rule: Rule
    q: Question
    profile: Profile
    company: str
    job: Job | None

    @property
    def label(self) -> str:
        return norm_label(self.q.label)

    @property
    def options(self) -> list[str]:
        labels = [o.label for o in self.q.options if o.label]
        if not labels and self.q.type == QuestionType.boolean:
            return ["Yes", "No"]
        return labels

    @property
    def is_choice(self) -> bool:
        return self.q.type in CHOICE_TYPES


def answered(ctx: Ctx, value: str | list[str], reason: str = "") -> RuleOutcome:
    return RuleOutcome(value, f"rule:{ctx.rule.id}", reason)


def unknown(reason: str) -> RuleOutcome:
    return RuleOutcome(None, "unknown", reason)


def as_text(value: Any) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, list | tuple):
        return ", ".join(as_text(v) for v in value if not is_blank(v))
    return str(value).strip()


def is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int | float):
        return True
    try:
        float(str(value))
    except ValueError:
        return False
    return True


def choose(ctx: Ctx, desired: Any, *, kind: str = "text", why: str = "") -> RuleOutcome:
    """Map a profile value onto the question: an option for choices, text otherwise."""
    if ctx.is_choice:
        result = match_option(desired, ctx.options, kind=kind)
        if result.option is None:
            return unknown(f"{why}; {result.reason}" if why else result.reason)
        value: str | list[str] = (
            [result.option] if ctx.q.type == QuestionType.multiselect else result.option
        )
        return answered(ctx, value, why)
    if ctx.q.type == QuestionType.number and not is_number(desired):
        return unknown(f"the form wants a number, and the profile gives {as_text(desired)!r}")
    if ctx.q.type == QuestionType.date and not ISO_DATE.match(as_text(desired)):
        return unknown(f"the form wants a date (YYYY-MM-DD), not {as_text(desired)!r}")
    return answered(ctx, as_text(desired), why)


def field_paths(ctx: Ctx) -> list[str]:
    """The rule's profile paths; `a|b` means "a, else b"."""
    return [p.strip() for p in (ctx.rule.field or "").split("|") if p.strip()]


def missing_field(ctx: Ctx) -> RuleOutcome:
    paths = field_paths(ctx)
    where = paths[0] if paths else "a matching field"
    return unknown(f"your profile has no {where}")
