"""Warnings about wording in a resume: weak openers, stock phrases, hidden characters."""

from __future__ import annotations

import re

from getmeajob.textutil import strip_invisible

WEAK_OPENERS = (
    "responsible for",
    "helped with",
    "helped to",
    "worked on",
    "assisted with",
    "assisted in",
    "participated in",
    "duties included",
    "involved in",
)
STOCK_PHRASES = (
    "results-driven",
    "team player",
    "passionate about",
    "detail-oriented",
    "self-starter",
    "go-getter",
    "think outside the box",
    "synergy",
    "spearheaded",
    "leveraged",
    "delve",
    "proven track record",
    "dynamic environment",
    "fast-paced environment",
)
_BULLET = re.compile(r"^\s*(?:[-*\u2022]\s+)?(?:[A-Za-z0-9-]+:\s+)?")
_EM_DASH = "\u2014"


def lint_text(text: str) -> list[str]:
    """Plain-language warnings, each starting with the line number. Empty means clean."""
    warnings: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if strip_invisible(line) != line:
            warnings.append(f"line {number}: has an invisible character; retype the line")
        lower = line.lower()
        body = _BULLET.sub("", lower, count=1)
        for opener in WEAK_OPENERS:
            if body.startswith(opener):
                warnings.append(f"line {number}: weak opener '{opener}'; start with what you did")
        for phrase in STOCK_PHRASES:
            if re.search(r"(?<![a-z])" + re.escape(phrase) + r"(?![a-z])", lower):
                warnings.append(f"line {number}: stock phrase '{phrase}'; say something specific")
        if _EM_DASH in line:
            warnings.append(f"line {number}: has an em dash; use a comma, colon or full stop")
    return warnings
