"""Helpers the job sources share: messy ids, text, locations, dates, URLs and JSON."""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

from getmeajob.files import parse_ts
from getmeajob.http import HttpClient, Response
from getmeajob.models import Board, Job
from getmeajob.textutil import html_to_text, one_line, tidy_lines, truncate

LISTING_TTL = 6 * 3600.0  # board listings
DISCOVERY_TTL = 7 * 86400.0  # probes and careers pages during discovery
FEED_TTL = 6 * 3600.0  # remote-job feeds
DETAIL_TTL = 7 * 86400.0  # per-job detail pages (job text rarely changes)
JD_MAX_CHARS = 20_000

_BAD_IDS = frozenset({"", "none", "null", "undefined", "nan", "n/a"})
_DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})")
_SLUG_OK = re.compile(r"^[\w][\w .\-]{0,99}$")

# Path words that look like slugs in ATS URLs but never are.
GENERIC_TOKENS = frozenset(
    {
        "embed",
        "js",
        "job",
        "jobs",
        "careers",
        "career",
        "v0",
        "v1",
        "v2",
        "v3",
        "api",
        "www",
        "apply",
        "search",
        "login",
        "boards",
        "job_board",
        "job_app",
        "job-board",
        "posting-api",
        "postings",
        "companies",
        "widget",
        "accounts",
        "oneclick-ui",
        "app",
        "static",
        "assets",
        "home",
        "index",
        "j",
        "o",
        "p",
    }
)

# --------------------------------------------------------------- loose JSON


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def as_str(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, int | float):
        return str(value)
    return ""


def as_int(value: Any) -> int:
    """A whole number from a JSON value, 0 when it is missing or not a number."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value == value:
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return 0


def clean_text(value: Any) -> str:
    """One line of text: invisible characters gone, whitespace collapsed."""
    return one_line(as_str(value))


def clean_block(value: Any) -> str:
    """Plain text that keeps its lines (for job text that already arrives as text)."""
    return tidy_lines(as_str(value))


def clean_id(value: Any) -> str | None:
    """A usable job id, or None for empty, "None", "null" and similar placeholders."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float):
        if value != value:  # NaN
            return None
        value = int(value) if value.is_integer() else value
    text = clean_text(value)
    return None if text.casefold() in _BAD_IDS else text


def jd_from_html(html: Any) -> str:
    return html_to_text(as_str(html), JD_MAX_CHARS) if as_str(html).strip() else ""


def truncate_jd(text: str) -> str:
    return truncate(text, JD_MAX_CHARS)


def jd_from_parts(parts: Iterable[str]) -> str:
    return truncate_jd("\n\n".join(p for p in parts if p.strip()))


# --------------------------------------------------------------- locations


def join_unique(parts: Iterable[str], sep: str = " | ") -> str:
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        text = clean_text(part)
        if text and text.casefold() not in seen:
            seen.add(text.casefold())
            out.append(text)
    return sep.join(out)


def _parse_listish(text: str) -> list[Any] | None:
    """A list from a stringified list such as "['Toronto', 'Remote']"."""
    if len(text) > 4000:
        return None
    for loader in (json.loads, ast.literal_eval):
        try:
            parsed = loader(text)
        except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
            continue
        if isinstance(parsed, list | tuple):
            return list(parsed)
    inner = text[1:-1].strip()
    return [part.strip().strip("'\"") for part in inner.split(",")] if inner else []


def as_location(value: Any) -> str:
    """A location string from a string, a list, a stringified list or a mapping."""
    if isinstance(value, Mapping):
        for key in ("name", "location", "label", "fullLocation", "text"):
            if value.get(key):
                return as_location(value[key])
        return join_unique(
            (as_str(value.get(k)) for k in ("city", "region", "state", "country")), ", "
        )
    if isinstance(value, list | tuple):
        return join_unique(as_location(v) for v in value)
    text = clean_text(value)
    if len(text) >= 2 and text[0] == "[" and text[-1] == "]":
        parsed = _parse_listish(text)
        if parsed is not None:
            return as_location(parsed)
    return text


def workplace_of(value: Any) -> str | None:
    """ "remote", "hybrid", "onsite" or None from an ATS workplace value."""
    text = re.sub(r"[\s_\-]", "", clean_text(value).casefold())
    if not text:
        return None
    if "remote" in text:
        return "remote"
    if "hybrid" in text:
        return "hybrid"
    if text in ("onsite", "inoffice", "office", "onpremise", "inperson"):
        return "onsite"
    return None


def workplace_from_text(location: str) -> tuple[bool | None, str | None]:
    """(remote, workplace) guessed from a free-text location."""
    low = location.casefold()
    if "hybrid" in low:
        return False, "hybrid"
    if "remote" in low:
        return True, "remote"
    return None, None


def place_with_workplace(location: str, workplace: str | None) -> str:
    """Fold the workplace type into the location text when it is not there yet."""
    low = location.casefold()
    if workplace == "remote" and "remote" not in low:
        return f"Remote - {location}" if location else "Remote"
    if workplace == "hybrid" and "hybrid" not in low:
        return f"{location} (Hybrid)" if location else "Hybrid"
    return location


# ------------------------------------------------------------------- dates


def to_date(value: Any) -> str | None:
    """YYYY-MM-DD from an ISO string or epoch seconds or milliseconds."""
    if value is None or isinstance(value, bool):
        return None
    number: float | None = None
    if isinstance(value, int | float):
        number = float(value)
    elif isinstance(value, str) and value.strip().isdigit():
        number = float(value.strip())
    if number is not None:
        if number <= 0:
            return None
        seconds = number / 1000.0 if number > 1e11 else number
        try:
            return datetime.fromtimestamp(seconds, UTC).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    text = clean_text(value)
    stamp = parse_ts(text)
    if stamp is not None:
        return stamp.date().isoformat()
    match = _DATE_PREFIX.match(text)
    return match.group(1) if match else None


# -------------------------------------------------------------------- URLs


def split_url(url: str) -> tuple[str, list[str], dict[str, str]]:
    """(host, path segments, query) of a URL; the scheme may be missing."""
    text = url.strip().strip("<>\"'")
    if "://" not in text:
        text = "https://" + text.lstrip("/")
    try:
        parts = urlsplit(text)
        host = (parts.hostname or "").lower()
    except ValueError:
        return "", [], {}
    segments = [unquote(s) for s in parts.path.split("/") if s]
    query = {k: v for k, v in parse_qsl(parts.query)}
    return host, segments, query


def valid_slug(token: str | None) -> str | None:
    if not token:
        return None
    token = token.strip()
    if token.casefold() in GENERIC_TOKENS or not _SLUG_OK.match(token):
        return None
    return token


def segment(segments: list[str], index: int) -> str | None:
    return segments[index] if len(segments) > index else None


# -------------------------------------------------------------------- jobs


def fetch_json(
    client: HttpClient,
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    ttl: float | None = None,
) -> tuple[Response, Any]:
    """GET and parse JSON. The data is None unless the status is 200."""
    resp = client.get(url, params=params, ttl=ttl)
    if resp.status != 200:
        return resp, None
    return resp, resp.json()


def make_job(board: Board, job_id: str, title: str, url: str, **fields: Any) -> Job:
    return Job(
        key=Job.make_key(board.ats, board.slug, job_id),
        ats=board.ats,
        board=board.slug,
        job_id=job_id,
        company=board.company,
        title=title,
        url=url,
        **fields,
    )


ParseItem = Callable[[Mapping[str, Any]], "Job | str"]


def collect_jobs(board: Board, items: list[Any], parse: ParseItem) -> tuple[list[Job], list[str]]:
    """Parse each item; a broken item is skipped with a reason, never a crash."""
    where = f"{board.ats}:{board.slug}"
    jobs: list[Job] = []
    skipped: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(items, start=1):
        if not isinstance(item, Mapping):
            skipped.append(f"{where} item {index}: not a job record")
            continue
        try:
            outcome = parse(item)
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            outcome = f"could not be read ({type(exc).__name__})"
        if isinstance(outcome, str):
            skipped.append(f"{where} item {index}: {outcome}")
        elif outcome.key in seen:
            skipped.append(f"{where} item {index}: duplicate id {outcome.job_id}")
        else:
            seen.add(outcome.key)
            jobs.append(outcome)
    return jobs, skipped


def bad_id(raw: Any) -> str:
    shown = repr(raw) if raw is None or isinstance(raw, str) else type(raw).__name__
    return f"no usable job id ({truncate(shown, 30)})"
