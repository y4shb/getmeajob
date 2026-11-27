"""Remote-job feeds: Remotive, RemoteOK and the HN "Who is hiring?" thread.

Feeds are leads, not boards. They run only when asked (`source --feeds ...`), send one
listing request per run (HN also looks up the current thread, cached for a day) and
cache replies for 6 hours. Each job keeps the feed's attribution link in `Job.source`
and links back to the feed's own page in `Job.url`, as the feeds ask.
`harvest_boards` pulls ATS board slugs out of feed job links.
"""

from __future__ import annotations

import dataclasses
import html
import re
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from getmeajob.errors import HttpError
from getmeajob.http import HttpClient
from getmeajob.models import Board, Job
from getmeajob.sources.boards import board_id
from getmeajob.sources.common import (
    FEED_TTL,
    as_dict,
    as_int,
    as_list,
    as_location,
    bad_id,
    clean_id,
    clean_text,
    collect_jobs,
    fetch_json,
    jd_from_html,
    make_job,
    place_with_workplace,
    to_date,
    truncate_jd,
)
from getmeajob.sources.discover import board_from_url
from getmeajob.textutil import html_to_text, truncate

FEED_ATTRIBUTION = {
    "remotive": "https://remotive.com",
    "remoteok": "https://remoteok.com",
    "hn": "https://news.ycombinator.com",
}
REMOTIVE_URL = "https://remotive.com/api/remote-jobs"
REMOTEOK_URL = "https://remoteok.com/api"
HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
HN_ITEM_URL = "https://hn.algolia.com/api/v1/items"
HN_THREAD_TTL = 86400.0

FeedFn = Callable[[HttpClient, "list[str] | None"], list[Job]]

_HREF = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_URL = re.compile(r"https?://[^\s<>\"'\])]+")
_ROLE = re.compile(
    r"engineer|developer|scientist|designer|architect|devops|\bsre\b|analyst|manager|"
    r"\blead\b|programmer|researcher|intern|product|full[ -]?stack|front[ -]?end|"
    r"back[ -]?end|\bml\b|\bcto\b|head of|director|specialist|consultant|administrator",
    re.IGNORECASE,
)
_PLACE = re.compile(
    r"remote|on-?site|on site|hybrid|in[- ]office|worldwide|anywhere|global|,", re.IGNORECASE
)


def _source(feed: str) -> str:
    return f"feed:{feed} ({FEED_ATTRIBUTION[feed]})"


def _feed_board(feed: str, company: str) -> Board:
    return Board(company=company, ats=feed, slug=feed, verified=False)


def _keep(skipped: list[str] | None, reasons: Iterable[str]) -> None:
    if skipped is not None:
        skipped.extend(reasons)


def _get(
    client: HttpClient, feed: str, url: str, params: Mapping[str, Any] | None, ttl: float
) -> Any:
    """Parsed JSON of a feed reply; any status but 200 is an error for the run summary."""
    resp, data = fetch_json(client, url, params=params, ttl=ttl)
    if resp.status != 200:
        raise HttpError(f"{feed} answered HTTP {resp.status}", url=url, status=resp.status)
    return data


def _remote_place(raw: Any) -> str:
    return place_with_workplace(as_location(raw) or "Worldwide", "remote")


# ------------------------------------------------------------------ Remotive


def _remotive_job(item: Mapping[str, Any]) -> Job | str:
    job_id = clean_id(item.get("id"))
    if job_id is None:
        return bad_id(item.get("id"))
    title, company = clean_text(item.get("title")), clean_text(item.get("company_name"))
    if not title or not company:
        return "no title or company"
    board = _feed_board("remotive", company)
    return make_job(
        board,
        job_id,
        title,
        clean_text(item.get("url")) or f"{FEED_ATTRIBUTION['remotive']}/remote-jobs",
        location=_remote_place(item.get("candidate_required_location")),
        remote=True,
        workplace="remote",
        posted=to_date(item.get("publication_date")),
        department=clean_text(item.get("category")) or None,
        comp=clean_text(item.get("salary")) or None,
        description=jd_from_html(item.get("description")),
        source=_source("remotive"),
    )


def remotive(client: HttpClient, skipped: list[str] | None = None) -> list[Job]:
    """Software jobs from Remotive (one request)."""
    params = {"category": "software-dev"}
    data = _get(client, "remotive", REMOTIVE_URL, params, FEED_TTL)
    items = as_list(as_dict(data).get("jobs"))
    jobs, reasons = collect_jobs(_feed_board("remotive", "Remotive"), items, _remotive_job)
    _keep(skipped, reasons)
    return jobs


# ------------------------------------------------------------------ RemoteOK


def _remoteok_job(item: Mapping[str, Any]) -> Job | str:
    job_id = clean_id(item.get("id"))
    if job_id is None:
        return bad_id(item.get("id"))
    title, company = clean_text(item.get("position")), clean_text(item.get("company"))
    if not title or not company:
        return "no title or company"
    low, high = as_int(item.get("salary_min")), as_int(item.get("salary_max"))
    comp = f"USD {low:,}-{high:,} a year" if low > 0 and high > 0 else None
    return make_job(
        _feed_board("remoteok", company),
        job_id,
        title,
        clean_text(item.get("url")) or f"{FEED_ATTRIBUTION['remoteok']}/remote-jobs/{job_id}",
        location=_remote_place(item.get("location")),
        remote=True,
        workplace="remote",
        apply_url=clean_text(item.get("apply_url")) or None,
        posted=to_date(item.get("date") or item.get("epoch")),
        comp=comp,
        description=jd_from_html(item.get("description")),
        source=_source("remoteok"),
    )


def remoteok(client: HttpClient, skipped: list[str] | None = None) -> list[Job]:
    """Jobs from RemoteOK (one request). Element 0 of the reply is a legal notice."""
    data = _get(client, "remoteok", REMOTEOK_URL, None, FEED_TTL)
    items = as_list(data)
    real = [
        item
        for index, item in enumerate(items)
        if not (
            isinstance(item, Mapping) and ("legal" in item or (index == 0 and "id" not in item))
        )
    ]
    jobs, reasons = collect_jobs(_feed_board("remoteok", "RemoteOK"), real, _remoteok_job)
    _keep(skipped, reasons)
    return jobs


# ------------------------------------------------------------------------ HN


def hn_thread_id(client: HttpClient) -> str | None:
    """The newest "Ask HN: Who is hiring?" story id."""
    params = {"tags": "story,author_whoishiring", "hitsPerPage": 6}
    data = _get(client, "hn", HN_SEARCH_URL, params, HN_THREAD_TTL)
    for hit in as_list(as_dict(data).get("hits")):
        hit = as_dict(hit)
        if "who is hiring" in clean_text(hit.get("title")).casefold():
            return clean_id(hit.get("objectID") or hit.get("story_id"))
    return None


def _links(raw_html: str) -> list[str]:
    links: list[str] = []
    for href in _HREF.findall(raw_html):
        url = html.unescape(href).strip()
        if url.startswith(("http://", "https://")) and url not in links:
            links.append(url)
    return links


def _pick(parts: list[str], pattern: re.Pattern[str], skip: str = "") -> str:
    return next((p for p in parts if p != skip and pattern.search(p)), "")


def hn_job(comment: Mapping[str, Any]) -> Job | str:
    """A job from one top-level comment that follows `Company | Role | Place | ...`."""
    job_id = clean_id(comment.get("id"))
    if job_id is None:
        return bad_id(comment.get("id"))
    raw = str(comment.get("text") or "")
    if not raw.strip() or comment.get("author") is None:
        return "deleted or empty comment"
    head = html_to_text(re.split(r"<p>", raw, maxsplit=1, flags=re.IGNORECASE)[0])
    head = head.splitlines()[0] if head else ""
    parts = [clean_text(p) for p in head.split("|") if clean_text(p)]
    if "|" not in head or len(parts) < 2:
        return "first line is not 'Company | Role | Place'"
    company, rest = truncate(parts[0], 80), parts[1:]
    title = truncate(_pick(rest, _ROLE) or rest[0], 120)
    place = _pick(rest, _PLACE, skip=title)
    remote = any("remote" in p.casefold() for p in parts)
    links = _links(raw)
    text = jd_from_html(raw)
    if links:
        text = truncate_jd(text + "\n\nLinks:\n" + "\n".join(f"- {u}" for u in links))
    ats_links = [u for u in links if _board_for(u, company) is not None]
    return make_job(
        _feed_board("hn", company),
        job_id,
        title,
        f"https://news.ycombinator.com/item?id={job_id}",
        location=place,
        remote=True if remote else None,
        workplace="remote" if remote else None,
        apply_url=next(iter(ats_links or links), None),
        posted=to_date(comment.get("created_at") or comment.get("created_at_i")),
        description=text,
        source=_source("hn"),
    )


def hn(client: HttpClient, skipped: list[str] | None = None) -> list[Job]:
    """Jobs from the top-level comments of the current HN hiring thread."""
    story = hn_thread_id(client)
    if story is None:
        _keep(skipped, ["hn: no 'Who is hiring?' thread found"])
        return []
    data = _get(client, "hn", f"{HN_ITEM_URL}/{story}", None, FEED_TTL)
    comments = [c for c in as_list(as_dict(data).get("children")) if isinstance(c, Mapping)]
    jobs, reasons = collect_jobs(_feed_board("hn", "HN"), comments, hn_job)
    _keep(skipped, reasons)
    return jobs


FEEDS: dict[str, FeedFn] = {"remotive": remotive, "remoteok": remoteok, "hn": hn}


# ------------------------------------------------------------------ harvest


def _board_for(url: str, company: str) -> Board | None:
    board = board_from_url(url, company)
    return None if board is None else dataclasses.replace(board, company=company, verified=False)


def harvest_boards(jobs: Iterable[Job]) -> list[Board]:
    """ATS boards linked from jobs (job URL, apply URL and links in the text), deduped."""
    found: dict[tuple[str, str], Board] = {}
    for job in jobs:
        urls = [job.url, job.apply_url or "", *_URL.findall(job.description)]
        for url in urls:
            board = _board_for(url.rstrip(".,;:"), job.company) if url else None
            if board is not None and board_id(board) not in found:
                board.notes = f"seen in the {job.ats} feed"
                found[board_id(board)] = board
    return list(found.values())
