"""Choosing one option from a form's list, shared by the planner and the form filler.

Order of attempts: exact (after normalising), yes/no/decline synonyms, unique prefix,
unique word containment, year ranges, then a strict fuzzy match. Each step that finds
more than one candidate stops with "ambiguous": the matcher refuses to guess. When
nothing fits it returns no option and a reason. It never falls back to the first option.
"""

from __future__ import annotations

import difflib
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

from getmeajob.textutil import norm_label

YES = frozenset(
    {"yes", "y", "true", "yeah", "yep", "agree", "i agree", "accept", "i accept", "confirm"}
)
NO = frozenset({"no", "n", "false", "nope", "i do not", "i don't", "i am not", "not"})
DECLINE = frozenset(
    {
        "decline",
        "decline to answer",
        "decline to self-identify",
        "i decline to self-identify",
        "prefer not to say",
        "prefer not to answer",
        "prefer not to disclose",
        "i don't wish to answer",
        "i do not wish to answer",
        "not specified",
    }
)

_DECLINE_RE = re.compile(
    r"decline|prefer not|rather not|choose not|do not wish|don'?t wish|do not want to|"
    r"don'?t want to|not to (say|disclose|answer|self|identify|respond)|not specified|"
    r"not disclosed|no answer|wish not to"
)
_NO_RE = re.compile(
    r"^(no|n|false|nope|none)\b|^i (do not|don'?t|am not|have not|haven'?t|will not|won'?t|"
    r"would not|cannot|can'?t)\b|^i'?m not\b|^not\b"
)
_YES_RE = re.compile(
    r"^(yes|y|true|yeah|yep)\b|^i (do|am|have|will|would|can|agree|accept|acknowledge|consent|"
    r"confirm|understand|certify)\b|^i'?m\b|^(agree|accept|acknowledged?|confirm(ed)?|consent)\b"
)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
_UP = re.compile(r"\+|\bor more\b|\bat least\b|\bminimum\b|\band (above|up|over)\b")
_UP_STRICT = re.compile(r"\b(more than|over|above|greater than|beyond)\b")
_DOWN = re.compile(r"\bor (less|fewer)\b|\bup to\b|\bat most\b|\bmaximum\b")
_DOWN_STRICT = re.compile(r"\b(less than|under|below|fewer than)\b|<")
_ZERO = re.compile(r"^(none|no experience|no professional experience|0)$|\bno experience\b")
FUZZY_MIN = 0.88
FUZZY_MARGIN = 0.05


@dataclass(slots=True)
class MatchResult:
    """`option` is the chosen label or None. `method` says how: exact, synonym, prefix,
    contains, years, fuzzy, ambiguous, none. `reason` is a short human sentence."""

    option: str | None
    method: str
    reason: str

    @property
    def ok(self) -> bool:
        return self.option is not None


def polarity(option: str) -> str | None:
    """ "decline", "no" or "yes" for an option label, else None. Decline is checked first,
    then no ("I do not" starts like "I do"), then yes."""
    text = norm_label(option)
    if not text:
        return None
    if text in DECLINE or _DECLINE_RE.search(text):
        return "decline"
    if text in NO or _NO_RE.search(text):
        return "no"
    if text in YES or _YES_RE.search(text):
        return "yes"
    return None


def _show(options: Sequence[str], limit: int = 3) -> str:
    shown = ", ".join(f"'{o}'" for o in options[:limit])
    return shown + (" and more" if len(options) > limit else "")


def _single(found: list[str], method: str, what: str) -> MatchResult | None:
    """One distinct label: a match. Several: ambiguous. None: keep looking."""
    distinct = list(dict.fromkeys(found))
    distinct_norm = {norm_label(o) for o in distinct}
    if not distinct:
        return None
    if len(distinct_norm) == 1:
        return MatchResult(distinct[0], method, f"{method} match for {what}")
    return MatchResult(
        None, "ambiguous", f"more than one option fits {what}: {_show(distinct)}; not guessing"
    )


def _by_polarity(want: str, options: Sequence[str], what: str) -> MatchResult:
    found = [o for o in options if polarity(o) == want]
    hit = _single(found, "synonym", what)
    if hit is not None:
        return hit
    return MatchResult(None, "none", f"no {want} option among {_show(list(options))}")


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text))


def match_option(
    desired: str | bool | int | float, options: Sequence[str], *, kind: str = "text"
) -> MatchResult:
    """Pick the one option that means `desired`.

    `desired` True/False means yes/no. `kind="decline"` looks for a decline option,
    `kind="years"` (or a number) uses year ranges. Text goes through exact, synonym,
    prefix, containment and fuzzy steps.
    """
    labels = [str(o) for o in options if str(o).strip()]
    if not labels:
        return MatchResult(None, "none", "the question has no options")
    if kind == "decline":
        return _by_polarity("decline", labels, "decline")
    if isinstance(desired, bool):
        return _by_polarity("yes" if desired else "no", labels, "yes" if desired else "no")
    if kind == "years" or isinstance(desired, int | float):
        try:
            return match_years(float(desired), labels)
        except (TypeError, ValueError):
            return MatchResult(None, "none", f"'{desired}' is not a number of years")
    want = norm_label(str(desired))
    if not want:
        return MatchResult(None, "none", "there is no answer to match")
    what = f"'{desired}'"
    normed = [(o, norm_label(o)) for o in labels]

    hit = _single([o for o, n in normed if n == want], "exact", what)
    if hit is not None:
        return hit
    if want in YES or want in NO or want in DECLINE:
        side = "yes" if want in YES else "no" if want in NO else "decline"
        return _by_polarity(side, labels, what)
    if len(want) >= 3:
        hit = _single([o for o, n in normed if n.startswith(want)], "prefix", what)
        if hit is not None:
            return hit
    want_words = _words(want)
    if want_words:
        hit = _single([o for o, n in normed if want_words <= _words(n)], "contains", what)
        if hit is not None:
            return hit
        inside = [o for o, n in normed if _words(n) and _words(n) <= want_words and len(n) >= 3]
        hit = _single(inside, "contains", what)
        if hit is not None:
            return hit
    return _fuzzy(want, normed, what)


def _fuzzy(want: str, normed: list[tuple[str, str]], what: str) -> MatchResult:
    scored = sorted(
        ((difflib.SequenceMatcher(None, want, n).ratio(), o) for o, n in normed),
        key=lambda pair: pair[0],
        reverse=True,
    )
    best, best_label = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    if best >= FUZZY_MIN and best - second >= FUZZY_MARGIN:
        return MatchResult(best_label, "fuzzy", f"close match for {what} ({best:.2f})")
    return MatchResult(
        None,
        "none",
        f"none of the {len(normed)} options matches {what}: {_show([o for o, _ in normed])}",
    )


def _interval(option: str) -> tuple[float, float] | None:
    """The year range an option stands for, inclusive, or None when it has no number."""
    text = norm_label(option).replace("\u2013", "-").replace("\u2014", "-")
    if _ZERO.search(text):
        return (0.0, 0.0)
    numbers = [float(n) for n in _NUMBER.findall(text)]
    if not numbers:
        return None
    if len(numbers) >= 2:
        lo, hi = sorted(numbers[:2])
        return (lo, hi)
    n = numbers[0]
    if _UP_STRICT.search(text):
        return (n + 1, math.inf)
    if _UP.search(text):
        return (n, math.inf)
    if _DOWN_STRICT.search(text):
        return (-math.inf, n - 1)
    if _DOWN.search(text):
        return (-math.inf, n)
    return (n, n)


def match_years(n: float, options: Sequence[str]) -> MatchResult:
    """Pick the option whose year range holds `n` completed years ("3-5", "10+", "Less than 1").

    A closed range wins over an open-ended one; among open-ended ranges the tightest
    ("5+" over "1+") wins. Two different closed ranges that both fit are ambiguous.
    """
    labels = [str(o) for o in options if str(o).strip()]
    if not labels:
        return MatchResult(None, "none", "the question has no options")
    years = math.floor(n)
    closed: list[tuple[float, str]] = []
    open_up: list[tuple[float, str]] = []
    for label in labels:
        span = _interval(label)
        if span is None or not span[0] <= years <= span[1]:
            continue
        if math.isinf(span[1]) or math.isinf(span[0]):
            open_up.append((span[0], label))
        else:
            closed.append((span[1] - span[0], label))
    what = f"{years} years"
    if closed:
        narrowest = min(width for width, _ in closed)
        best = [label for width, label in closed if width == narrowest]
        hit = _single(best, "years", what)
        assert hit is not None
        return hit
    if open_up:
        tightest = max(lo for lo, _ in open_up)
        hit = _single([label for lo, label in open_up if lo == tightest], "years", what)
        assert hit is not None
        return hit
    return MatchResult(None, "none", f"no option covers {what}: {_show(labels)}")


def match_many(desired: Sequence[str], options: Sequence[str]) -> tuple[list[str], list[str]]:
    """Match each wanted value for a multi-select. Returns (chosen labels, problems)."""
    chosen: list[str] = []
    problems: list[str] = []
    for value in desired:
        result = match_option(str(value), options)
        if result.option is None:
            problems.append(result.reason)
        elif result.option not in chosen:
            chosen.append(result.option)
    return chosen, problems
