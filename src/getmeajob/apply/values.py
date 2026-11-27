"""Pure helpers that turn planned answers into what a form field accepts.

No browser here, so everything can be tested without Chromium: number and date
coercion, the local part of a phone number, month names, education and employment
rows, and choosing one location suggestion.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from getmeajob.plan.options import MatchResult, match_option
from getmeajob.plan.profile import Profile
from getmeajob.textutil import norm_label

MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_MONEY = re.compile(r"(?:[$€£¥]|\b(?:usd|cad|eur|gbp|aud|inr)\b)\s*([\d,]+(?:\.\d+)?)", re.I)
_YEAR_MONTH = re.compile(r"^(\d{4})-(\d{1,2})(?:-(\d{1,2}))?$")
_WORD = re.compile(r"[a-z0-9]+")
DEGREE_PATTERNS = {
    "high_school": r"high school|secondary|ged",
    "associates": r"^associate",
    "bachelors": r"^bachelor|\bb\.?(s|a|sc|eng)\b",
    "masters": r"^master|\bm\.?(s|a|sc|eng|ba)\b",
    "doctorate": r"doctor|ph\.?\s?d",
}


def coerce_number(value: Any, label: str = "") -> str | None:
    """Bare digits for a number field ("4 years" -> "4"), or None when there is no number.

    Pay questions take the amount after a currency sign or code when there is one, so
    "CAD 95,000" becomes "95000".
    """
    text = str(value if value is not None else "").strip()
    if not text:
        return None
    if re.search(r"salary|compensation|pay|wage|rate", label, re.I):
        money = _MONEY.search(text)
        if money:
            return _plain_number(money.group(1).replace(",", ""))
    found = _NUMBER.search(text.replace(",", ""))
    return _plain_number(found.group(0)) if found else None


def _plain_number(text: str) -> str:
    number = float(text)
    return str(int(number)) if number.is_integer() else f"{number:g}"


def coerce_date(value: Any) -> str | None:
    """`YYYY-MM-DD` for a date input ("2026-12" becomes "2026-12-01"), else None."""
    match = _YEAR_MONTH.match(str(value or "").strip())
    if not match:
        return None
    year, month, day = match.group(1), int(match.group(2)), int(match.group(3) or 1)
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        return None
    return f"{year}-{month:02d}-{day:02d}"


def local_phone(value: str, profile: Profile) -> str:
    """The number without its country code, for forms that ask for the country separately."""
    local = profile.text("contact.phone_local")
    if local:
        return local
    digits = re.sub(r"\D", "", value)
    code = re.sub(r"\D", "", profile.text("contact.phone_country_code") or "")
    if code and value.strip().startswith("+") and digits.startswith(code):
        return digits[len(code) :]
    return digits


def dial_code(option: str) -> str | None:
    """The `+N` dial code inside a country option ("Canada +1" -> "+1"), if any."""
    match = re.search(r"\+\d{1,4}\b", option)
    return match.group(0) if match else None


def month_name(value: Any) -> str | None:
    """ "June" for "2021-06" (or for 6), else None."""
    text = str(value or "").strip()
    match = _YEAR_MONTH.match(text if text.count("-") else f"2000-{text}")
    if not match:
        return None
    month = int(match.group(2))
    return MONTHS[month - 1] if 1 <= month <= 12 else None


def year_of(value: Any) -> str | None:
    match = re.match(r"^\s*(\d{4})", str(value or ""))
    return match.group(1) if match else None


# ------------------------------------------------------------------- repeaters


@dataclass(slots=True)
class EducationRow:
    school: str
    degree: str = ""
    discipline: str = ""
    start_year: str = ""
    end_year: str = ""
    degree_level: str = ""
    school_aliases: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EmploymentRow:
    company: str
    title: str = ""
    start_month: str | None = None
    start_year: str | None = None
    end_month: str | None = None
    end_year: str | None = None
    current: bool = False


def education_rows(value: Any, profile: Profile) -> list[EducationRow]:
    """Rows from the plan's "School | Degree | Discipline | 2017-2021" strings, with the
    degree level and school aliases taken from the matching profile entry."""
    items = value if isinstance(value, list) else [value] if value else []
    entries = profile.get("education")
    entries = entries if isinstance(entries, list) else []
    rows: list[EducationRow] = []
    for i, item in enumerate(items):
        parts = [p.strip() for p in str(item).split("|")]
        parts += [""] * (4 - len(parts))
        years = re.findall(r"\d{4}", parts[3])
        entry = entries[i] if i < len(entries) and isinstance(entries[i], dict) else {}
        aliases = entry.get("school_aliases")
        rows.append(
            EducationRow(
                school=parts[0],
                degree=parts[1],
                discipline=parts[2],
                start_year=years[0] if years else "",
                end_year=years[1] if len(years) > 1 else "",
                degree_level=str(entry.get("degree_level") or ""),
                school_aliases=[str(a) for a in aliases] if isinstance(aliases, list) else [],
            )
        )
    return [r for r in rows if r.school]


def employment_rows(profile: Profile) -> list[EmploymentRow]:
    """Rows from `employment[]` in the profile (company, title, start, end, current)."""
    entries = profile.get("employment")
    rows: list[EmploymentRow] = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or not str(entry.get("company") or "").strip():
            continue
        end = str(entry.get("end") or "").strip()
        current = bool(entry.get("current")) or end.casefold() == "present"
        rows.append(
            EmploymentRow(
                company=str(entry["company"]).strip(),
                title=str(entry.get("title") or "").strip(),
                start_month=month_name(entry.get("start")),
                start_year=year_of(entry.get("start")),
                end_month=None if current else month_name(end),
                end_year=None if current else year_of(end),
                current=current,
            )
        )
    return rows


def match_degree(row: EducationRow, options: Sequence[str]) -> MatchResult:
    """The degree option: by its name first, then by the profile's `degree_level`."""
    by_name = match_option(row.degree, options) if row.degree else None
    if by_name is not None and by_name.ok:
        return by_name
    pattern = DEGREE_PATTERNS.get(row.degree_level.casefold().replace("'", ""))
    if not pattern:
        return by_name or MatchResult(None, "none", "no degree in the plan")
    hits = list(dict.fromkeys(o for o in options if re.search(pattern, norm_label(o))))
    if len(hits) == 1:
        return MatchResult(hits[0], "degree_level", f"matches degree level {row.degree_level}")
    if hits:
        return MatchResult(None, "ambiguous", "more than one degree option fits; not guessing")
    return MatchResult(None, "none", "no degree option fits")


# -------------------------------------------------------------------- location


def _words(text: str) -> set[str]:
    return set(_WORD.findall(norm_label(text)))


def _has(option_words: set[str], name: str) -> bool:
    words = _words(name)
    return bool(words) and words <= option_words


def location_parts(profile: Profile) -> tuple[str, list[str], str, str]:
    """(city, city aliases, state, country) from the profile."""
    city = profile.text("location.city") or ""
    aliases = profile.strings("location.city_aliases")
    return (
        city,
        aliases,
        profile.text("location.state") or "",
        profile.text("location.country") or "",
    )


def pick_location(
    options: Sequence[str], profile: Profile, desired: str | None = None
) -> MatchResult:
    """Choose the one suggestion that is the candidate's city.

    An exact match of the planned value wins. Otherwise a suggestion must name the city
    (or an alias) and, when the profile has them, the country and the state; the most
    specific level with exactly one suggestion wins. Several fits is ambiguous, none is
    no match. The first suggestion is never taken just because it is first.
    """
    labels = [o for o in options if o.strip()]
    if not labels:
        return MatchResult(None, "none", "no suggestions appeared")
    if desired:
        exact = [o for o in labels if norm_label(o) == norm_label(desired)]
        if len(set(map(norm_label, exact))) == 1:
            return MatchResult(exact[0], "exact", "exact match for the planned location")
    city, aliases, state, country = location_parts(profile)
    names = [n for n in [city, *aliases] if n]
    if not names:
        return MatchResult(None, "none", "your profile has no location.city")
    words = {o: _words(o) for o in labels}
    level = [o for o in labels if any(_has(words[o], n) for n in names)]
    if not level:
        return MatchResult(None, "none", f"none of the {len(labels)} suggestions names your city")
    regions = [r for r in (country, state) if r]
    if regions:
        level = [o for o in level if any(_has(words[o], r) for r in regions)]
        if not level:
            return MatchResult(
                None, "none", "no suggestion names your city together with your state or country"
            )
    for extra in (country, state):
        if not extra:
            continue
        narrower = [o for o in level if _has(words[o], extra)]
        if narrower:
            level = narrower
    distinct = list(dict.fromkeys(level))
    if len(distinct) == 1:
        return MatchResult(distinct[0], "location", "the only suggestion with your city and region")
    return MatchResult(
        None, "ambiguous", f"{len(distinct)} suggestions fit your city and region; not guessing"
    )
