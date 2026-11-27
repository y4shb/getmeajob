"""Finding country names in question text and job locations.

The alias table lives in `rules_default.yaml` (`country_aliases`). Short upper-case
aliases such as "US" or "UK" only count when written in capitals, so "join us" is not
the United States. Names from the profile are always recognised too.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Iterable

from getmeajob.models import Job
from getmeajob.textutil import norm_label


@functools.lru_cache(maxsize=1)
def _table() -> dict[str, list[str]]:
    from getmeajob.plan.rules import default_country_aliases

    return default_country_aliases()


@functools.lru_cache(maxsize=512)
def _alias_regex(alias: str) -> re.Pattern[str]:
    exact_case = alias.isupper() or "." in alias
    flags = 0 if exact_case else re.IGNORECASE
    return re.compile(r"(?<![A-Za-z])" + re.escape(alias) + r"(?![A-Za-z])", flags)


def canonical(name: str) -> str:
    """The table's name for a country ("USA" gives "United States"), else the name itself."""
    want = norm_label(name)
    for country, aliases in _table().items():
        if want == norm_label(country) or want in {norm_label(a) for a in aliases}:
            return country
    return name.strip()


def countries_in(text: str, extra_names: Iterable[str] = ()) -> list[str]:
    """Canonical names of the countries mentioned in `text`, in table order."""
    found: list[str] = []
    table = dict(_table())
    for name in extra_names:
        if name and canonical(name) not in table:
            table[canonical(name)] = [name]
    for country, aliases in table.items():
        names = [country, *aliases]
        if any(_alias_regex(a).search(text) for a in names if a) and country not in found:
            found.append(country)
    return found


def is_remote(job: Job) -> bool:
    if job.remote is True:
        return True
    words = f"{job.location or ''} {job.workplace or ''}".casefold()
    return re.search(r"\bremote\b", words) is not None
