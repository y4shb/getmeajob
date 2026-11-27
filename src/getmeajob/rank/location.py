"""Where a job is, which of your location tiers it falls in, and region limits in the text.

Nothing here knows where you live. Your home city, region and country, the regions you
accept and the names you use for them all come from `preferences.yaml`. The small table in
`regions_default.yaml` only says that "US" and "United States" are the same place.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

from getmeajob.models import Flag, Job
from getmeajob.rank.prefs import Preferences

REGIONS_FILE = Path(__file__).with_name("regions_default.yaml")
JD_HEAD = 6000

_GLOBAL = re.compile(
    r"(?<![A-Za-z])(?:worldwide|world-wide|global(?:ly)?|anywhere|international|any country|"
    r"all locations|work from anywhere)(?![A-Za-z])",
    re.IGNORECASE,
)
_REMOTE = re.compile(
    r"(?<![A-Za-z])(?:remote|work from home|wfh|distributed|telecommut\w*)(?![A-Za-z])",
    re.IGNORECASE,
)
_HYBRID = re.compile(r"(?<![A-Za-z])hybrid(?![A-Za-z])", re.IGNORECASE)
_FULLY_REMOTE = re.compile(
    r"fully remote|100% remote|remote[- ]first|work from anywhere|fully distributed", re.I
)
_NOISE = re.compile(
    r"(?<![A-Za-z])(?:remote|remotely|hybrid|on-?site|in[- ]office|office|work from home|wfh|"
    r"anywhere|distributed|flexible|only|based|the|in|within|for|and|or|of|from|home|first|"
    r"friendly|worldwide|global(?:ly)?|international|location|locations)(?![A-Za-z])",
    re.IGNORECASE,
)
_SPLIT_PLACES = re.compile(r"\s*(?:;|\||\n)\s*")


@dataclass(slots=True)
class TierResult:
    kind: str
    name: str
    score: float
    reason: str
    restricted_to: str = ""  # set when a remote job is limited to a region you cannot use


# ----------------------------------------------------------------- region names


@cache
def _defaults() -> dict[str, list[str]]:
    raw = yaml.safe_load(REGIONS_FILE.read_text(encoding="utf-8")) or {}
    return {str(k).lower(): [str(a).lower() for a in (v or [])] for k, v in raw.items()}


def _clean(name: str) -> str:
    out = name.strip().lower()
    out = re.sub(r"^the\s+", "", out)
    return out.strip(" .,;:")


def alias_table(prefs: Preferences) -> dict[str, str]:
    """Every known name (lower case, as written) mapped to one canonical region name."""
    groups: dict[str, set[str]] = {k: {k, *v} for k, v in _defaults().items()}
    for name, aliases in prefs.region_aliases.items():
        groups.setdefault(name, {name}).update(a.lower() for a in aliases)
    home = _clean(prefs.home.country)
    if home:
        groups.setdefault(home, {home}).update(
            _clean(a) for a in [prefs.home.country, *prefs.home.country_aliases]
        )
    table: dict[str, str] = {}
    for canon, names in groups.items():
        for name in names:
            table.setdefault(_clean(name), canon)
    return table


def canon_region(name: str, prefs: Preferences) -> str:
    """The canonical form of a region name: "U.S." and "the United States" agree."""
    cleaned = _clean(name)
    return alias_table(prefs).get(cleaned, cleaned)


def _term_pattern(term: str) -> re.Pattern[str]:
    term = term.strip()
    if len(term) <= 3 and term.isalpha():  # short codes must be in capitals ("US", not "us")
        return re.compile(r"(?<![A-Za-z])" + re.escape(term.upper()) + r"(?![A-Za-z])")
    return re.compile(r"(?<![A-Za-z])" + re.escape(term) + r"(?![A-Za-z])", re.IGNORECASE)


def term_in(text: str, term: str) -> bool:
    return bool(term.strip()) and _term_pattern(term).search(text) is not None


def _home_city_terms(prefs: Preferences) -> list[str]:
    return [t for t in [prefs.home.city, *prefs.home.city_aliases] if t.strip()]


def _home_area_terms(prefs: Preferences) -> list[str]:
    terms = [prefs.home.country, prefs.home.region, *prefs.home.country_aliases]
    return [t for t in terms if t.strip()]


def is_home_city(text: str, prefs: Preferences) -> bool:
    return any(term_in(text, t) for t in _home_city_terms(prefs))


def is_home_area(text: str, prefs: Preferences) -> bool:
    return any(term_in(text, t) for t in _home_area_terms(prefs))


def _acceptable_names(prefs: Preferences) -> set[str]:
    names = [*_home_area_terms(prefs), *_home_city_terms(prefs)]
    names += [*prefs.allowed_regions, *prefs.authorized_in]
    return {canon_region(n, prefs) for n in names if n.strip()}


def mentions_region(text: str, region: str, prefs: Preferences) -> bool:
    """Does `text` name this region, under any of its known names?"""
    wanted = canon_region(region, prefs)
    names = {region, *(n for n, canon in alias_table(prefs).items() if canon == wanted)}
    return any(term_in(text, n) for n in names)


def region_ok(phrase: str, prefs: Preferences) -> bool:
    """Is this region one you can work from (home, allowed, or authorised)?"""
    if _GLOBAL.search(phrase):
        return True
    return canon_region(phrase, prefs) in _acceptable_names(prefs) or is_home_area(phrase, prefs)


# --------------------------------------------------------------- restrictions

_WORD = r"(?:(?:[A-Z]\.){2,}|[A-Z]\w*)"
_CAP = rf"(?:the\s+)?(?P<r>{_WORD}(?:\s+(?:of\s+)?{_WORD}){{0,3}})"
_MORE = re.compile(rf"\s*(?:,|/|\band\b|\bor\b)\s*(?:the\s+)?({_WORD}(?:\s+{_WORD}){{0,2}})")
_BASED = re.compile(
    r"(?i:(?:must|need to|needs to|required to|have to|should)\s+(?:be\s+)?"
    r"(?:based|located|reside|residing|live|living|resident|working)\s+(?:in|within))\s+" + _CAP
)
_AUTHORIZED = re.compile(
    r"(?i:(?:authori[sz]ed|eligible|legally entitled|permitted|allowed)\s+to\s+work\s+"
    r"(?:in|within))\s+" + _CAP
)
_REMOTE_IN = re.compile(r"(?i:remote(?:ly)?\s+(?:in|within|from))\s+" + _CAP)
_TIMEZONE = re.compile(
    r"\b(?:[A-Z]{2,4}T|Pacific|Eastern|Central|Mountain|European)\s+(?i:time\s*zone|hours)\b"
)


@cache
def _known_regex(names: tuple[str, ...]) -> re.Pattern[str]:
    parts: list[str] = []
    for name in sorted(set(names), key=lambda n: (-len(n), n)):
        if len(name) <= 3 and name.isalpha():
            parts.append(re.escape(name.upper()))
        else:
            parts.append("(?i:" + re.escape(name) + ")")
    return re.compile(r"(?<![A-Za-z])(?P<r>" + "|".join(parts) + r")(?![A-Za-z])")


def _known_names(prefs: Preferences) -> tuple[str, ...]:
    names = {n for n in alias_table(prefs) if n}
    names.update(_clean(n) for n in [*prefs.allowed_regions, *prefs.needs_sponsorship_in])
    return tuple(sorted(n for n in names if n and n not in {"worldwide", "anywhere"}))


def _only_pattern(prefs: Preferences) -> re.Pattern[str]:
    known = _known_regex(_known_names(prefs)).pattern
    return re.compile(known + r"\s*[-\u2013]?\s*(?i:only)\b")


def _adjective_pattern(prefs: Preferences) -> re.Pattern[str]:
    known = _known_regex(_known_names(prefs)).pattern
    return re.compile(known + r"[- ](?i:based|citizens?|residents?|persons?|work authori[sz]ation)")


def _regions_after(text: str, match: re.Match[str]) -> list[str]:
    """The region in the match plus any more joined by "and", "or" or commas."""
    regions = [match.group("r").rstrip(".,;:")]
    pos = match.end()
    for _ in range(3):
        more = _MORE.match(text, pos)
        if more is None:
            break
        regions.append(more.group(1).rstrip(".,;:"))
        pos = more.end()
    return regions


def region_restrictions(text: str, prefs: Preferences) -> list[Flag]:
    """Wording that limits a job to a region you cannot use, as `region_restricted` flags.

    "Must be based in X", "authorized to work in X", "remote in X", "X only", "X-based"
    count when X is not your home area, an allowed region or somewhere you are authorized.
    A time zone lock is reported as a soft flag.
    """
    flags: list[Flag] = []
    seen: set[str] = set()

    def add(regions: list[str], label: str) -> None:
        if any(region_ok(r, prefs) for r in regions):
            return
        reason = f"limited to {' or '.join(regions)} ({label})"
        if reason not in seen:
            seen.add(reason)
            flags.append(Flag("region_restricted", reason[:88], True))

    for pattern, label in (
        (_BASED, "must be based there"),
        (_AUTHORIZED, "must be authorized to work there"),
        (_REMOTE_IN, "remote only there"),
    ):
        for match in pattern.finditer(text):
            add(_regions_after(text, match), label)
    for pattern, label in ((_only_pattern(prefs), "only"), (_adjective_pattern(prefs), "based")):
        for match in pattern.finditer(text):
            add([match.group("r")], label)
    for match in _TIMEZONE.finditer(text):
        reason = f"time zone lock: {match.group(0)}"
        if reason not in seen:
            seen.add(reason)
            flags.append(Flag("region_restricted", reason[:88], False))
    return flags


# ---------------------------------------------------------------------- tiers


def _tier(prefs: Preferences, kind: str, reason: str, restricted_to: str = "") -> TierResult:
    tier = prefs.tier_for(kind)
    return TierResult(kind, tier.name, tier.score, reason, restricted_to)


def _leftover(part: str) -> str:
    rest = _NOISE.sub(" ", part)
    rest = re.sub(r"[^\w.+#&' ]+", " ", rest)
    return " ".join(rest.split())


def _mentions_acceptable(text: str, prefs: Preferences) -> bool:
    if _GLOBAL.search(text) or is_home_area(text, prefs):
        return True
    return any(term_in(text, r) for r in prefs.allowed_regions)


def _remote_tier(part: str, prefs: Preferences, text: str) -> TierResult:
    rest = _leftover(part)
    if _GLOBAL.search(part) and not rest:
        return _tier(prefs, "remote_worldwide", "location: remote worldwide")
    if not rest:
        limits = region_restrictions(text, prefs)
        hard = [f for f in limits if f.hard]
        if hard:
            return _tier(prefs, "other", "location: remote, region limited in the text")
        if text and _mentions_acceptable(text, prefs):
            return _tier(prefs, "remote_worldwide", "location: remote, text names your region")
        return _tier(prefs, "other", "location: remote, region not stated")
    if is_home_area(rest, prefs) or is_home_city(rest, prefs):
        return _tier(prefs, "remote_home_country", f"location: remote in {rest[:40]}")
    for region in prefs.allowed_regions:
        if term_in(rest, region):
            kind = "remote_worldwide" if _GLOBAL.search(region) else "remote_home_country"
            return _tier(prefs, kind, f"location: remote, {region[:40]} is allowed")
    return _tier(prefs, "other", f"location: remote, only {rest[:40]}", rest[:60])


def _place_tier(part: str, hybrid: bool, prefs: Preferences, text: str) -> TierResult:
    head = text[:JD_HEAD]
    if is_home_city(part, prefs):
        if hybrid or _HYBRID.search(head):
            return _tier(prefs, "hybrid_home_city", "location: hybrid in your city")
        return _tier(prefs, "onsite_home_city", "location: on site in your city")
    if is_home_area(part, prefs):
        if _FULLY_REMOTE.search(head):
            return _tier(prefs, "remote_home_country", "location: your region, text says remote")
        return _tier(prefs, "home_country_other", "location: elsewhere in your country")
    shown = " ".join(part.split())[:40] or "not given"
    return _tier(prefs, "other", f"location: {shown} (outside your area)")


def location_tier(job: Job, prefs: Preferences, text: str = "") -> TierResult:
    """Which of your location tiers this job falls in.

    `text` is the job description; it is only used when the location alone does not say
    enough (a bare "Remote", or a city with no word on hybrid or on site). A job listed in
    several places gets the best tier among them.
    """
    workplace = (job.workplace or "").strip()
    parts = [p for p in _SPLIT_PLACES.split(job.location or "") if p.strip()] or [""]
    best: TierResult | None = None
    for part in parts:
        joined = f"{part} {workplace}".strip()
        hybrid = bool(_HYBRID.search(joined))
        remote = bool(_REMOTE.search(joined)) or job.remote is True
        if remote and not hybrid:
            result = _remote_tier(part, prefs, text)
        else:
            result = _place_tier(part, hybrid, prefs, text)
        if best is None or result.score > best.score:
            best = result
    assert best is not None
    return best
