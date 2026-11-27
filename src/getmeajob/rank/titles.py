"""Job titles: which of your tracks a title fits, and whether it is excluded or too senior."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache

from getmeajob.rank.prefs import Preferences, Track

_TECHNICAL_STAFF = re.compile(r"\b(?:member of )?technical staff\b", re.IGNORECASE)


@cache
def _word(term: str) -> re.Pattern[str]:
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(term.strip()) + r"(?![A-Za-z0-9])", re.I)


def has_word(text: str, term: str) -> bool:
    """Does `text` contain `term` as a whole word or phrase, ignoring case?"""
    return bool(term.strip()) and _word(term).search(text) is not None


def first_hit(title: str, words: list[str]) -> str | None:
    """The first of `words` that appears in `title`, if any."""
    for word in words:
        if has_word(title, word):
            return word
    return None


@dataclass(slots=True)
class TrackMatch:
    name: str
    score: float  # 0 to 1: how well the title and the description fit this track
    title_hit: str
    jd_hits: list[str]


def _track_match(track: Track, title: str, text: str) -> TrackMatch | None:
    hit = first_hit(title, track.title_any)
    if hit is None:
        return None
    jd_hits = [w for w in track.jd_any if has_word(text, w)]
    jd_share = len(jd_hits) / len(track.jd_any) if track.jd_any else 1.0
    return TrackMatch(track.name, track.weight * (0.8 + 0.2 * jd_share), hit, jd_hits)


def best_track(title: str, text: str, prefs: Preferences) -> TrackMatch | None:
    """The track whose title words match this title best (None if no track matches)."""
    best: TrackMatch | None = None
    for track in prefs.tracks:
        match = _track_match(track, title, text)
        if match is not None and (best is None or match.score > best.score):
            best = match
    return best


@dataclass(slots=True)
class TitleCheck:
    excluded: str | None  # the excluded word found, if any
    too_senior: str | None
    junior: str | None


def check_title(title: str, prefs: Preferences) -> TitleCheck:
    """Look for the title words you listed under `title:` in your preferences."""
    plain = _TECHNICAL_STAFF.sub(" ", title)
    return TitleCheck(
        excluded=first_hit(plain, prefs.title_exclude),
        too_senior=first_hit(plain, prefs.title_too_senior),
        junior=first_hit(plain, prefs.title_junior),
    )
