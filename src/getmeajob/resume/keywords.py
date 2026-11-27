"""Keywords in a job description, and how many of them a resume covers."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from getmeajob.rank.skills import find_skills, skill_regex

MAX_KEYWORDS = 40
MAX_TOKENS = 10
_ACRONYM = re.compile(r"(?<![A-Za-z0-9/])[A-Z]{2,6}(?![A-Za-z0-9/])")
_CAMEL = re.compile(r"(?<![A-Za-z0-9])[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+(?![A-Za-z0-9])")
# Capital-letter words that show up in job posts but are not skills.
_NOT_SKILLS = frozenset(
    {
        *("AND", "THE", "FOR", "YOU", "OUR", "ARE", "NOT", "ALL", "ANY", "CEO", "CFO", "COO"),
        *("CTO", "HR", "PTO", "EEO", "EOE", "LLC", "INC", "LTD", "USD", "CAD", "EUR", "GBP"),
        *("FAQ", "USA", "EST", "PST", "EDT", "PDT", "CET", "UTC", "GMT", "PM", "AM", "OK"),
        *("NA", "TBD", "ASAP", "FTE", "PTE", "RSU", "ESOP", "ID", "US", "UK", "EU"),
    }
)


@dataclass(slots=True)
class Coverage:
    matched: list[str]
    missing: list[str]

    @property
    def ratio(self) -> float:
        total = len(self.matched) + len(self.missing)
        return len(self.matched) / total if total else 0.0


def term_present(text: str, term: str) -> bool:
    """Does `text` contain this term as a whole word (or known skill name)?"""
    return skill_regex(term).search(text) is not None


def jd_keywords(text: str, extra_terms: Sequence[str] = ()) -> list[str]:
    """The terms a job description asks for, most important first.

    Order: known skills by how often they appear, then any of `extra_terms` (for example the
    words in your fact bank) that the text contains, then up to ten acronyms and CamelCase
    names such as "SRE" or "OpenTelemetry". Nothing is invented: every term is in the text.
    """
    found = find_skills(text)
    ordered = sorted(found, key=lambda name: (-found[name], name))
    seen_patterns = {id(skill_regex(name)) for name in ordered}
    keywords = list(ordered)

    def add(term: str) -> bool:
        pattern = id(skill_regex(term))
        if pattern in seen_patterns:
            return False
        seen_patterns.add(pattern)
        keywords.append(term)
        return True

    for term in extra_terms:
        clean = term.strip()
        if clean and term_present(text, clean):
            add(clean)
    tokens: list[str] = []
    for pattern in (_ACRONYM, _CAMEL):
        for match in pattern.finditer(text):
            token = match.group(0)
            if token not in _NOT_SKILLS and token not in tokens:
                tokens.append(token)
    added = 0
    for token in tokens:
        if added >= MAX_TOKENS:
            break
        if add(token):
            added += 1
    return keywords[:MAX_KEYWORDS]


def coverage(jd_text: str, resume_text: str, extra_terms: Sequence[str] = ()) -> Coverage:
    """Which of the job's keywords the resume text mentions, and which it does not."""
    matched: list[str] = []
    missing: list[str] = []
    for term in jd_keywords(jd_text, extra_terms):
        (matched if term_present(resume_text, term) else missing).append(term)
    return Coverage(matched, missing)
