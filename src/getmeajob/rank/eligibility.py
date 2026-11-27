"""Hard and soft flags: reasons a job is not for you, each with a code and a plain reason."""

from __future__ import annotations

import re

from getmeajob.models import Flag, Job
from getmeajob.rank.location import (
    location_tier,
    mentions_region,
    region_restrictions,
    term_in,
)
from getmeajob.rank.prefs import Preferences
from getmeajob.rank.titles import best_track, check_title
from getmeajob.rank.yoe import YoeResult
from getmeajob.textutil import slugify

_NO_SPONSOR = re.compile(
    r"\b(?:no|not|cannot|can't|can not|unable to|won't|will not|do not|don't|does not|never|"
    r"without)\b[^.\n]{0,40}?\bsponsor\w*"
    r"|\bsponsorship\b[^.\n]{0,30}?\b(?:is not|isn't|not|will not be)\s+"
    r"(?:available|offered|provided|possible)"
    r"|\bsponsorship\s+(?:is\s+)?unavailable"
    r"|\bmust\s+not\s+require\b[^.\n]{0,30}\bsponsor",
    re.IGNORECASE,
)
_CLEARANCE = re.compile(
    r"security clearance|\bTS/SCI\b|top[- ]secret|secret clearance|public trust\b|"
    r"\bITAR\b|\bEAR\b|export[- ]controlled|(?:active|current|hold|obtain)\s+(?:an?\s+)?"
    r"(?:\w+\s+){0,2}clearance",
    re.IGNORECASE,
)
_NEGATED = re.compile(r"\b(?:no|not|without)\b[^.\n]{0,15}$", re.IGNORECASE)
_CITIZEN = re.compile(
    r"(?:must|need to|required to|have to)\s+(?:be|hold)\s+(?:an?\s+)?(?:[\w.]+\s+){0,2}citizen"
    r"|citizenship\s+(?:is\s+)?(?:required|mandatory)"
    r"|\b(?:[\w.]+)\s+citizens?\s+(?:only|required)"
    r"|\bU\.?S\.?\s+persons?\b|green card\s+(?:holder\s+)?required",
    re.IGNORECASE,
)


def _company_excluded(job: Job, prefs: Preferences) -> str | None:
    names = {slugify(job.company), slugify(job.board)}
    for entry in prefs.exclude_companies:
        if slugify(entry) in names:
            return entry
    return None


def _clearance_flag(text: str, prefs: Preferences) -> Flag | None:
    if prefs.has_clearance:
        return None
    for match in _CLEARANCE.finditer(text):
        if _NEGATED.search(text[max(0, match.start() - 20) : match.start()]):
            continue
        shown = " ".join(match.group(0).split())
        return Flag("clearance_required", f"asks for clearance or export status: {shown}"[:88])
    return None


def _citizenship_flag(text: str, prefs: Preferences) -> Flag | None:
    for match in _CITIZEN.finditer(text):
        around = text[max(0, match.start() - 60) : match.end() + 60]
        if any(term_in(around, c) for c in prefs.citizenships):
            continue
        shown = " ".join(match.group(0).split())
        return Flag("citizenship_required", f"asks for citizenship: {shown}"[:88])
    return None


def _sponsorship_flag(
    job: Job, text: str, prefs: Preferences, restricted: list[Flag]
) -> Flag | None:
    if not prefs.needs_sponsorship_in or not _NO_SPONSOR.search(text):
        return None
    scope = " ".join([job.location, *(f.reason for f in restricted)])
    for region in prefs.needs_sponsorship_in:
        if mentions_region(scope, region, prefs):
            return Flag("no_sponsorship", f"no visa sponsorship, and you need it in {region}"[:88])
    return None


def eligibility_flags(job: Job, text: str, prefs: Preferences, yoe: YoeResult) -> list[Flag]:
    """Every flag for this job. A hard flag makes it ineligible; a soft one is a warning."""
    flags: list[Flag] = []
    excluded_company = _company_excluded(job, prefs)
    if excluded_company:
        flags.append(Flag("company_excluded", f"you excluded {excluded_company}"[:88]))
    title = check_title(job.title, prefs)
    if title.excluded:
        flags.append(Flag("title_excluded", f"title has '{title.excluded}', which you excluded"))
    if title.too_senior:
        asked = yoe.min
        if asked is not None and asked <= prefs.years:
            reason = f"title says {title.too_senior}, but it asks {asked} yrs"
            flags.append(Flag("too_senior", reason[:88], False))
        else:
            reason = f"title says {title.too_senior}, too senior for {prefs.years:g} yrs"
            flags.append(Flag("too_senior", reason[:88]))
    if yoe.min is not None and yoe.min > prefs.too_senior_over:
        flags.append(Flag("too_senior", f"asks {yoe.min}+ yrs; you have {prefs.years:g}"[:88]))
    elif yoe.min is not None and yoe.min > prefs.years + prefs.stretch_years:
        reason = f"asks {yoe.min} yrs, a big stretch from {prefs.years:g}"
        flags.append(Flag("too_senior", reason[:88], False))
    if prefs.tracks and best_track(job.title, text, prefs) is None:
        flags.append(Flag("off_track", "the title fits none of your tracks"))
    tier = location_tier(job, prefs, text)
    restricted: list[Flag] = []
    if tier.restricted_to:
        restricted.append(Flag("region_restricted", f"remote, but only {tier.restricted_to}"[:88]))
    restricted += region_restrictions(text, prefs)
    flags += restricted
    sponsor = _sponsorship_flag(job, text, prefs, restricted)
    if sponsor:
        flags.append(sponsor)
    for flag in (_clearance_flag(text, prefs), _citizenship_flag(text, prefs)):
        if flag:
            flags.append(flag)
    unique: list[Flag] = []
    for flag in flags:
        if not any(f.code == flag.code and f.reason == flag.reason for f in unique):
            unique.append(flag)
    return unique
