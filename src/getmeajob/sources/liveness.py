"""`check_live`: is a stored job still open?

1. Board first: if the job's board answers in full and the job is not on it, it is
   closed; if it is on it, it is open.
2. Page second (feed jobs, or when the board did not answer): 404 or 410 is closed,
   a redirect from a job page back to the board is closed, and so is a page whose text
   says the job is closed (with no apply button text).
403, 406, 429, bot checks, robots.txt refusals and network errors are `unknown`, never
closed. Closed jobs are marked in `jobs.jsonl` and get a `closed` status event.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from getmeajob.errors import BotWallError, GetmeajobError, HttpError, RobotsDisallowed
from getmeajob.files import now_iso
from getmeajob.http import HttpClient, Response
from getmeajob.models import AppStatus, Board, Job
from getmeajob.sources.boards import board_id, load_boards
from getmeajob.sources.common import split_url
from getmeajob.sources.registry import all_sources
from getmeajob.store import JobStore, StatusLog
from getmeajob.textutil import html_to_text
from getmeajob.workspace import Workspace

LiveState = Literal["open", "closed", "unknown"]

_CLOSED_TEXT = re.compile(
    r"no longer (?:available|accepting|open|active)|position has been filled|"
    r"(?:job|position|posting|role|vacancy) (?:is |has )?(?:been )?(?:closed|expired|filled)|"
    r"this job (?:has|was) (?:been )?(?:closed|removed)|job not found|page not found|"
    r"applications? (?:are|is) (?:now )?closed",
    re.IGNORECASE,
)
_APPLY_TEXT = re.compile(r"apply now|apply for this job|submit (?:your )?application", re.I)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TITLE_GONE = re.compile(r"\b404\b|not found", re.IGNORECASE)
_GREENHOUSE_JOB = re.compile(r"/jobs/\d+")


@dataclass
class LiveResult:
    key: str
    state: LiveState
    why: str


def _redirected_to_board(job: Job, resp: Response) -> str | None:
    final = resp.url
    host, segments, _ = split_url(final)
    _, start_segments, _ = split_url(job.url)
    if "greenhouse.io" in host:
        if "error=true" in final:
            return "the job page now shows an error"
        if _GREENHOUSE_JOB.search(job.url) and not _GREENHOUSE_JOB.search(final):
            return "the job page now sends you to the board"
    lever = host in ("jobs.lever.co", "jobs.eu.lever.co")
    if lever and len(start_segments) >= 2 and len(segments) < 2:
        return "the job page now sends you to the board"
    return None


def judge_page(job: Job, resp: Response) -> LiveResult:
    """Open, closed or unknown from a fetched job page."""
    if resp.status in (404, 410):
        return LiveResult(job.key, "closed", f"the job page answered HTTP {resp.status}")
    if resp.status >= 400:
        return LiveResult(job.key, "unknown", f"HTTP {resp.status}, not judged")
    redirect = _redirected_to_board(job, resp)
    if redirect:
        return LiveResult(job.key, "closed", redirect)
    head = resp.text[:20000]
    title = _TITLE.search(head)
    if title and _TITLE_GONE.search(html_to_text(title.group(1))):
        return LiveResult(job.key, "closed", "the page title says not found")
    text = html_to_text(resp.text[:300_000])
    marker = _CLOSED_TEXT.search(text)
    if marker and not _APPLY_TEXT.search(text):
        return LiveResult(job.key, "closed", f'the page says "{marker.group(0)}"')
    return LiveResult(job.key, "open", "the job page loads")


def check_page(job: Job, client: HttpClient) -> LiveResult:
    try:
        resp = client.get(job.url, check_robots=True)
    except BotWallError:
        return LiveResult(job.key, "unknown", "the site showed a bot check")
    except RobotsDisallowed:
        return LiveResult(job.key, "unknown", "robots.txt asks tools not to read the page")
    except HttpError as exc:
        reason = f"HTTP {exc.status}" if exc.status else "the page could not be reached"
        return LiveResult(job.key, "unknown", f"{reason}, not judged")
    return judge_page(job, resp)


def _board_check(
    jobs: list[Job], boards: dict[tuple[str, str], Board], client: HttpClient
) -> dict[str, LiveResult]:
    """Results for jobs whose board answered in full; the rest are left out."""
    sources = all_sources()
    groups: dict[tuple[str, str], list[Job]] = {}
    for job in jobs:
        if job.ats in sources:
            groups.setdefault((job.ats.casefold(), job.board.casefold()), []).append(job)
    out: dict[str, LiveResult] = {}
    for gid, members in groups.items():
        first = members[0]
        board = boards.get(gid) or Board(company=first.company, ats=first.ats, slug=first.board)
        try:
            result = sources[first.ats].list_jobs(board, client)
        except GetmeajobError:
            continue
        if not result.found or result.error is not None or result.partial:
            continue
        present = {j.key for j in result.jobs}
        for job in members:
            if job.key in present:
                out[job.key] = LiveResult(job.key, "open", "still on the board")
            else:
                out[job.key] = LiveResult(job.key, "closed", "no longer on the board")
    return out


def check_live(ws: Workspace, client: HttpClient, keys: list[str] | None) -> list[LiveResult]:
    """Check the given jobs (default: every job not yet closed) and record closures."""
    store = JobStore(ws)
    stored = store.load()
    results: dict[str, LiveResult] = {}
    if keys:
        targets = [stored[k] for k in keys if k in stored]
        for key in keys:
            if key not in stored:
                results[key] = LiveResult(key, "unknown", "not in data/jobs.jsonl")
    else:
        targets = [j for j in stored.values() if j.status != "closed"]
    boards = {board_id(b): b for b in load_boards(ws)}
    results.update(_board_check(targets, boards, client))
    rest = [job for job in targets if job.key not in results]
    for job, outcome in zip(rest, client.map(lambda j: check_page(j, client), rest), strict=True):
        if isinstance(outcome, Exception):
            outcome = LiveResult(job.key, "unknown", f"check failed: {outcome}")
        results[job.key] = outcome
    closed = [r for r in results.values() if r.state == "closed"]
    if closed:
        store.mark_closed([r.key for r in closed], now_iso())
        events = StatusLog(ws)
        for item in closed:
            events.record(item.key, AppStatus.closed, "liveness", note=item.why)
    order = list(keys) if keys else [j.key for j in targets]
    return [results[k] for k in order if k in results]
