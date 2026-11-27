"""The answer kinds a rule can name. Each turns profile facts into one answer, or
returns "unknown" with a reason when the profile does not settle the question.

Nothing here guesses: a missing field, an option that does not match, or a question
the profile cannot answer truthfully all give "unknown". `rules._settle` then turns an
optional unknown into a blank ("skip"). Work-related kinds live in `kinds_work`.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from getmeajob.models import Job, Question, QuestionType
from getmeajob.plan.kinds_base import (
    Ctx,
    answered,
    choose,
    field_paths,
    missing_field,
    unknown,
)
from getmeajob.plan.kinds_work import (
    k_former_employer,
    k_location,
    k_primary_language,
    k_skill_yes_no,
    k_sponsorship,
    k_work_authorization,
    k_years,
    k_years_threshold,
)
from getmeajob.plan.options import polarity
from getmeajob.plan.profile import Profile, is_blank
from getmeajob.plan.rules import Rule, RuleOutcome
from getmeajob.textutil import norm_label


def k_never(ctx: Ctx) -> RuleOutcome:
    return unknown("questions about AI or automated tools are never answered automatically")


def k_skip_optional(ctx: Ctx) -> RuleOutcome:
    return unknown("your profile has no field for this; answer it yourself")


def k_field(ctx: Ctx) -> RuleOutcome:
    """The first non-empty profile path; for choices also its `<path>_aliases` list."""
    problem = ""
    for path in field_paths(ctx):
        value = ctx.profile.get(path)
        if value is None:
            continue
        outcome = choose(ctx, value, why=f"from {path}")
        if outcome.answered:
            return outcome
        aliases = ctx.profile.strings(f"{path}_aliases") if ctx.is_choice else []
        for alias in aliases:
            alt = choose(ctx, alias, why=f"from {path}_aliases")
            if alt.answered:
                return alt
        problem = problem or outcome.reason
    return unknown(problem) if problem else missing_field(ctx)


def _bool_of(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    side = polarity(value) if isinstance(value, str) else None
    return {"yes": True, "no": False}.get(side or "")


def k_yes_no(ctx: Ctx) -> RuleOutcome:
    path = ctx.rule.field or ""
    value = _bool_of(ctx.profile.get(path))
    if value is None:
        return unknown(f"your profile has no {path} (true or false)")
    return choose(ctx, value, why=f"from {path}")


def _alias_pick(ctx: Ctx, value: str) -> RuleOutcome | None:
    """Use `options_pref` ("profile words=option regex") to map a profile value; the
    longest key found in the value wins ("not employed" before "employed")."""
    text = norm_label(value)
    best: tuple[int, str] | None = None
    for entry in ctx.rule.options_pref:
        key, sep, pattern = entry.partition("=")
        key = norm_label(key)
        if not sep or not key or not re.search(rf"(?<!\w){re.escape(key)}(?!\w)", text):
            continue
        if best is None or len(key) > best[0]:
            best = (len(key), pattern)
    if best is None:
        return None
    regex = re.compile(best[1], re.IGNORECASE)
    hits = list(dict.fromkeys(o for o in ctx.options if regex.search(norm_label(o))))
    if len(hits) == 1:
        picked: str | list[str] = hits if ctx.q.type == QuestionType.multiselect else hits[0]
        return answered(ctx, picked, f"'{value}' from your profile")
    if len(hits) > 1:
        return unknown(f"more than one option fits '{value}': {', '.join(hits[:3])}; not guessing")
    return None


def k_choice_from(ctx: Ctx) -> RuleOutcome:
    problem = ""
    for path in field_paths(ctx):
        value = ctx.profile.text(path)
        if value is None:
            continue
        outcome = choose(ctx, value, why=f"from {path}")
        if outcome.answered or not ctx.is_choice:
            return outcome
        picked = _alias_pick(ctx, value)
        if picked is not None and picked.answered:
            return picked
        problem = problem or (picked.reason if picked is not None else outcome.reason)
    return unknown(problem) if problem else missing_field(ctx)


def k_eeo(ctx: Ctx) -> RuleOutcome:
    """Voluntary self-ID: your value when set, else the decline option, else unknown."""
    for path in field_paths(ctx):
        value = ctx.profile.get(path)
        if value is not None:
            return choose(ctx, value, why=f"from {path}")
    if ctx.is_choice:
        return choose(ctx, "", kind="decline", why="voluntary and empty in your profile: declined")
    return unknown("voluntary question with no answer in your profile")


def k_consent(ctx: Ctx) -> RuleOutcome:
    if ctx.profile.get("consent.privacy_notice") is not True:
        return unknown("consent is ticked only when consent.privacy_notice is true in your profile")
    path = ctx.rule.field or "consent.privacy_notice"
    value = ctx.profile.get(path)
    if value is True:
        return choose(ctx, True, why=f"{path} is true")
    if value is False and any(polarity(o) == "no" for o in ctx.options):
        return choose(ctx, False, why=f"{path} is false")
    return unknown(f"your profile does not opt in ({path})")


def _pay(ctx: Ctx, text_path: str, number_path: str) -> RuleOutcome:
    if not ctx.q.required:
        return RuleOutcome(None, "skip", "pay questions are left blank when optional")
    path = number_path if ctx.q.type == QuestionType.number else text_path
    value = ctx.profile.get(path)
    return choose(ctx, value, why=f"from {path}") if value is not None else missing_field(ctx)


def k_compensation(ctx: Ctx) -> RuleOutcome:
    return _pay(ctx, ctx.rule.field or "compensation.expected_text", "compensation.expected_number")


def k_current_compensation(ctx: Ctx) -> RuleOutcome:
    if ctx.profile.get("compensation.share_current") is not True:
        why = "you chose not to share current pay (compensation.share_current)"
        return RuleOutcome(None, "skip", why) if not ctx.q.required else unknown(why)
    path = ctx.rule.field or "compensation.current_text"
    return _pay(ctx, path, path)


def k_file(ctx: Ctx) -> RuleOutcome:
    path = ctx.rule.field or "files.resume"
    value = ctx.profile.text(path)
    if value is None:
        return unknown(f"your profile has no {path}")
    return RuleOutcome(value, "file", f"from {path}")


def k_education(ctx: Ctx) -> RuleOutcome:
    rows: list[str] = []
    for item in ctx.profile.get("education") or []:
        if not isinstance(item, Mapping) or is_blank(item.get("school")):
            continue
        years = "-".join(
            str(item[k]) for k in ("start_year", "end_year") if not is_blank(item.get(k))
        )
        parts = [item.get("school"), item.get("degree"), item.get("discipline"), years]
        rows.append(" | ".join(str(p) for p in parts if not is_blank(p)))
    if not rows:
        return unknown("your profile has no education entries")
    return answered(ctx, rows, "from education")


KIND_HANDLERS: dict[str, Callable[[Ctx], RuleOutcome]] = {
    "never": k_never,
    "skip_optional": k_skip_optional,
    "field": k_field,
    "yes_no": k_yes_no,
    "years": k_years,
    "years_threshold": k_years_threshold,
    "choice_from": k_choice_from,
    "eeo": k_eeo,
    "consent": k_consent,
    "sponsorship": k_sponsorship,
    "work_authorization": k_work_authorization,
    "former_employer": k_former_employer,
    "location": k_location,
    "compensation": k_compensation,
    "current_compensation": k_current_compensation,
    "file": k_file,
    "education": k_education,
    "primary_language": k_primary_language,
    "skill_yes_no": k_skill_yes_no,
}


def apply_kind(
    rule: Rule, q: Question, profile: Profile, company: str, job: Job | None
) -> RuleOutcome:
    handler = KIND_HANDLERS.get(rule.kind, k_skip_optional)
    return handler(Ctx(rule=rule, q=q, profile=profile, company=company, job=job))
