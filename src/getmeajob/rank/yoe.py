"""Read "years of experience" asks out of a job description."""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_YEARS = 25
MAX_RANGE_TOP = 30

_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "fifteen": 15,
    "twenty": 20,
}
_NUM = r"(?:\d{1,2}|" + "|".join(_WORDS) + r")"
_SEP = r"\s*(?:-|\u2013|\u2014|to|and|or)\s*"
_MENTION = re.compile(
    rf"(?<![\w$.,/-])(?P<lo>{_NUM})(?P<p1>\s*\+)?"
    rf"(?:{_SEP}(?P<hi>{_NUM})(?P<p2>\s*\+)?)?"
    r"(?P<p3>\s*\+|\s+plus|\s+or\s+more|\s+and\s+(?:up|above|more|over))?"
    r"\s*(?:years?|yrs?)\b(?![\s-]*old)(?!\s+ago)",
    re.IGNORECASE,
)
_EXPERIENCE_WORD = re.compile(
    r"experien|background|track record|hands-on|working|industry|professional|minimum|"
    r"at least|between|required|requirements|qualifications|"
    r"of (?:software|engineering|development)",
    re.IGNORECASE,
)
_NOT_EXPERIENCE = re.compile(
    r"founded|in business|anniversary|warranty|years old|over the (?:last|past)|for over",
    re.IGNORECASE,
)
_PREFERRED = re.compile(r"prefer|nice to have|bonus|ideally|desired", re.IGNORECASE)
_PREFERRED_AFTER = re.compile(r"\b(?:a plus|preferred|nice to have|bonus)\b", re.IGNORECASE)
_REQUIRED_MARK = re.compile(r"required|must have|must|minimum|requirements|qualifications", re.I)
_SENTENCE_END = re.compile(r"[.;!?]\s")


@dataclass(slots=True)
class YoeResult:
    min: int | None
    max: int | None
    snippet: str
    required: bool


def _to_int(token: str) -> int:
    token = token.lower()
    return _WORDS[token] if token in _WORDS else int(token)


def _is_preferred(text: str, start: int, end: int) -> bool:
    """Is this mention a "nice to have" rather than a requirement?"""
    before = text[max(0, start - 120) : start]
    cut = 0
    for match in _SENTENCE_END.finditer(before):
        cut = match.end()
    before = before[cut:]
    prefer = list(_PREFERRED.finditer(before))
    if prefer and not any(m.start() > prefer[-1].end() for m in _REQUIRED_MARK.finditer(before)):
        return True
    same_line = before.rsplit("\n", 1)[-1]
    if re.search(r"\bplus\b", same_line, re.IGNORECASE):
        return True
    after = text[end : end + 60].split("\n", 1)[0]
    stop = _SENTENCE_END.search(after)
    return bool(_PREFERRED_AFTER.search(after[: stop.start()] if stop else after))


def parse_yoe(text: str) -> YoeResult:
    """The years of experience a job asks for.

    Picks the largest minimum among the required mentions (or among the "nice to have"
    ones when nothing is required). Company-age phrases and numbers above 25 are ignored.
    """
    mentions: list[tuple[int, int | None, str, bool]] = []
    for match in _MENTION.finditer(text or ""):
        low = _to_int(match.group("lo"))
        if low > MAX_YEARS:
            continue
        window = text[max(0, match.start() - 90) : match.end() + 90]
        if not _EXPERIENCE_WORD.search(window):
            continue
        if _NOT_EXPERIENCE.search(window) and "experien" not in window.lower():
            continue
        high = _to_int(match.group("hi")) if match.group("hi") else None
        if high is not None and (high < low or high > MAX_RANGE_TOP):
            high = None
        snippet = " ".join(text[max(0, match.start() - 30) : match.end() + 40].split())
        mentions.append((low, high, snippet, _is_preferred(text, match.start(), match.end())))
    if not mentions:
        return YoeResult(None, None, "", False)
    required = [m for m in mentions if not m[3]]
    pool = required or mentions
    best = pool[0]
    for item in pool[1:]:
        if item[0] > best[0]:
            best = item
    return YoeResult(best[0], best[1], best[2], bool(required))
