"""Answer kinds about work: years of experience, work permits and sponsorship, former
employers, location, and programming languages."""

from __future__ import annotations

import re
from collections.abc import Mapping

from getmeajob.plan.countries import canonical, countries_in
from getmeajob.plan.kinds_base import Ctx, answered, choose, is_number, missing_field, unknown
from getmeajob.plan.options import polarity
from getmeajob.plan.profile import is_blank
from getmeajob.plan.rules import RuleOutcome
from getmeajob.textutil import norm_label

# Words that keep a years question about total experience (not one skill or role).
GENERIC_YEARS = frozenset(
    "software backend back-end engineering engineer development developer programming coding "  # noqa: SIM905
    "industry professional professionally work working tech technology technical it total "
    "overall full-time paid commercial career".split()
)
_YEARS_ADJ = re.compile(r"\byears?\s+(?:of\s+)?((?:[\w+#./-]+\s+){0,3}?)experience\b")
_YEARS_TOPIC = re.compile(
    r"\byears?\b.*?\b(?:with|in|using|as|on|doing|building|writing|programming in)\s+"
    r"(?:an?\s+|the\s+)?([\w+#./-]+)"
)
_THRESHOLD = re.compile(
    r"\b(more than|less than|fewer than|at least|minimum(?: of)?|over|under)\s*(\d+)\+?"
    r"|\b(\d+)\s*\+|\b(\d+) or more\b"
)
_COMPANY_WORDS = re.compile(
    r"\b(us|our (company|organi[sz]ation|firm|team|group)|this (company|organi[sz]ation|firm)|"
    r"the company)\b"
)
_SUFFIXES = frozenset(
    "inc incorporated ltd limited llc llp plc corp corporation co company gmbh ag sa bv "  # noqa: SIM905
    "group holdings".split()
)
_LISTING = re.compile(r",|/| and | or |&")


# ------------------------------------------------------------------- years


def topic_of_years(label: str) -> str | None:
    """The subject of a years question when it is about one skill or role, else None."""
    adjective = _YEARS_ADJ.search(label)
    if adjective:
        for word in adjective.group(1).split():
            if word not in GENERIC_YEARS:
                return word
    topic = _YEARS_TOPIC.search(label)
    if topic and topic.group(1) not in GENERIC_YEARS:
        return topic.group(1)
    return None


def _total_years(ctx: Ctx) -> float | None:
    value = ctx.profile.get(ctx.rule.field or "experience.total_years")
    return float(str(value)) if is_number(value) else None


def k_years(ctx: Ctx) -> RuleOutcome:
    topic = topic_of_years(ctx.label)
    if topic:
        return unknown(f"this asks for years with '{topic}', not total years; answer it yourself")
    years = _total_years(ctx)
    if years is None:
        return missing_field(ctx)
    kind = "years" if ctx.is_choice else "text"
    return choose(ctx, years, kind=kind, why="from experience.total_years")


def k_years_threshold(ctx: Ctx) -> RuleOutcome:
    found = _THRESHOLD.search(ctx.label)
    topic = topic_of_years(ctx.label)
    if found is None or topic:
        what = f" with '{topic}'" if topic else ""
        return unknown(f"this asks about years{what} that the profile does not state")
    years = _total_years(ctx)
    if years is None:
        return missing_field(ctx)
    word = (found.group(1) or "at least").replace(" of", "")
    limit = float(found.group(2) or found.group(3) or found.group(4))
    meets = {
        "more than": years > limit,
        "over": years > limit,
        "less than": years < limit,
        "fewer than": years < limit,
        "under": years < limit,
    }.get(word, years >= limit)
    return choose(ctx, meets, why=f"{years:g} years in your profile, asked {word} {limit:g}")


# ------------------------------------------------- work permit, sponsorship


def _named_and_lists(ctx: Ctx) -> tuple[list[str], set[str], set[str], str]:
    """(countries the question is about, authorized, needs sponsorship, where from)."""
    authorized = ctx.profile.strings("eligibility.authorized_countries")
    needs = ctx.profile.strings("eligibility.needs_sponsorship_countries")
    home = ctx.profile.text("location.country")
    extra = [*authorized, *needs, home or ""]
    named = countries_in(f"{ctx.q.label}\n{ctx.q.description or ''}", extra)
    where = "the question"
    if not named and ctx.job is not None:
        named = countries_in(ctx.job.location or "", extra)
        where = "the job location"
    return named, {canonical(c) for c in authorized}, {canonical(c) for c in needs}, where


def k_sponsorship(ctx: Ctx) -> RuleOutcome:
    named, auth, needs, where = _named_and_lists(ctx)
    if not auth and not needs:
        return unknown("your profile has no eligibility.authorized_countries")
    if not named:
        return unknown("neither the question nor the job says which country")
    if any(c in needs for c in named):
        return choose(ctx, True, why=f"you need sponsorship there ({where})")
    if all(c in auth for c in named):
        return choose(ctx, False, why=f"you may work there ({where})")
    return unknown(f"{', '.join(named)} is not in your eligibility lists")


def k_work_authorization(ctx: Ctx) -> RuleOutcome:
    named, auth, needs, where = _named_and_lists(ctx)
    if not auth and not needs:
        return unknown("your profile has no eligibility.authorized_countries")
    if not named:
        return unknown("neither the question nor the job says which country")
    if all(c in auth for c in named):
        return choose(ctx, True, why=f"you may work there ({where})")
    if any(c in needs for c in named):
        return choose(ctx, False, why=f"you would need sponsorship there ({where})")
    return unknown(f"{', '.join(named)} is not in your eligibility lists")


# ---------------------------------------------------------- former employer


def company_core(name: str) -> str:
    """A company name without punctuation and legal suffixes ("Example Corp." -> "example")."""
    words = re.sub(r"[^\w\s&-]", " ", norm_label(name)).split()
    while words and words[-1] in _SUFFIXES:
        words.pop()
    return " ".join(words)


def k_former_employer(ctx: Ctx) -> RuleOutcome:
    core = company_core(ctx.company)
    if not core:
        return unknown("the job has no company name to compare with")
    label = ctx.label
    mentions = re.search(rf"(?<!\w){re.escape(core)}(?!\w)", label) is not None
    if not mentions and not _COMPANY_WORDS.search(label):
        return unknown("the question does not name this company")
    employers = ctx.profile.strings("experience.former_employers")
    employers += ctx.profile.strings("experience.current_company")
    for item in ctx.profile.get("employment") or []:
        if isinstance(item, Mapping) and not is_blank(item.get("company")):
            employers.append(str(item["company"]))
    if not employers:
        return unknown("your profile lists no employers")
    # Whole names only: "Initech Example Ltd" is not "Example Corp".
    worked = any(company_core(e) == core for e in employers)
    return choose(ctx, worked, why="from the employers in your profile")


# ------------------------------------------------------------------ location


def k_location(ctx: Ctx) -> RuleOutcome:
    city = ctx.profile.text("location.city")
    state = ctx.profile.text("location.state")
    country = ctx.profile.text("location.country")
    if city is None:
        return unknown("your profile has no location.city")
    full = ", ".join(p for p in (city, state, country) if p)
    if not ctx.is_choice:
        return answered(ctx, full, "from location")
    for candidate in [full, ", ".join(p for p in (city, state) if p), city]:
        outcome = choose(ctx, candidate, why="from location")
        if outcome.answered:
            return outcome
    for alias in ctx.profile.strings("location.city_aliases"):
        outcome = choose(ctx, alias, why="from location.city_aliases")
        if outcome.answered:
            return outcome
    return unknown(f"no option matches {full}")


# ----------------------------------------------------------------- languages


def _languages_named(ctx: Ctx) -> list[str]:
    langs = ctx.profile.strings(ctx.rule.field or "experience.primary_languages")
    label = ctx.label
    return [x for x in langs if re.search(rf"(?<!\w){re.escape(x.casefold())}(?!\w)", label)]


def k_primary_language(ctx: Ctx) -> RuleOutcome:
    langs = ctx.profile.strings(ctx.rule.field or "experience.primary_languages")
    if not langs:
        return missing_field(ctx)
    if ctx.is_choice and any(polarity(o) in ("yes", "no") for o in ctx.options):
        if _languages_named(ctx):
            return choose(ctx, True, why="listed in experience.primary_languages")
        return unknown("the question names a language not in experience.primary_languages")
    if ctx.is_choice:
        for lang in langs:
            outcome = choose(ctx, lang, why="from experience.primary_languages")
            if outcome.answered:
                return outcome
        return unknown("no option matches your primary languages")
    if "programming" in ctx.label or "coding" in ctx.label:
        return answered(ctx, langs[0], "from experience.primary_languages")
    return unknown("this may ask about a spoken language; answer it yourself")


def k_skill_yes_no(ctx: Ctx) -> RuleOutcome:
    named = _languages_named(ctx)
    if named and not _LISTING.search(ctx.label):
        return choose(ctx, True, why=f"{named[0]} is in experience.primary_languages")
    return unknown("only single skills listed in experience.primary_languages are answered")
