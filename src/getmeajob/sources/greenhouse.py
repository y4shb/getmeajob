"""Greenhouse job boards (`boards-api.greenhouse.io`)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from getmeajob.errors import BotWallError, HttpError
from getmeajob.http import HttpClient
from getmeajob.models import Board, Job
from getmeajob.sources.base import ProbeResult, SourceResult
from getmeajob.sources.common import (
    DISCOVERY_TTL,
    LISTING_TTL,
    as_dict,
    as_list,
    as_location,
    bad_id,
    clean_id,
    clean_text,
    collect_jobs,
    fetch_json,
    jd_from_html,
    join_unique,
    make_job,
    segment,
    split_url,
    to_date,
    valid_slug,
    workplace_from_text,
)

API = "https://boards-api.greenhouse.io/v1/boards"
BOARD_HOSTS = frozenset(
    {
        "boards.greenhouse.io",
        "boards.eu.greenhouse.io",
        "job-boards.greenhouse.io",
        "job-boards.eu.greenhouse.io",
    }
)
API_HOSTS = frozenset({"boards-api.greenhouse.io", "api.greenhouse.io"})


class GreenhouseSource:
    name = "greenhouse"

    def list_jobs(self, board: Board, client: HttpClient) -> SourceResult:
        url = f"{API}/{quote(board.slug, safe='')}/jobs"
        notes: list[str] = []
        try:
            resp, data = fetch_json(client, url, params={"content": "true"}, ttl=LISTING_TTL)
        except BotWallError:
            raise
        except HttpError as exc:
            # Big boards can time out or send broken JSON with the full text included.
            notes.append(f"the full job text did not load ({exc.message}); listed jobs only")
            resp, data = fetch_json(client, url, ttl=LISTING_TTL)
        if resp.status == 404:
            return SourceResult(found=False, jobs=[])
        if resp.status != 200:
            return SourceResult(found=False, jobs=[], error=f"HTTP {resp.status}")
        items = as_dict(data).get("jobs")
        if not isinstance(items, list):
            return SourceResult(found=False, jobs=[], error="the reply has no 'jobs' list")
        jobs, skipped = collect_jobs(board, items, lambda item: self._job(board, item))
        name = self._board_name(board.slug, client, LISTING_TTL)
        return SourceResult(True, jobs, name, skipped=skipped, notes=notes)

    def probe(self, slug: str, client: HttpClient) -> ProbeResult:
        resp, data = fetch_json(client, f"{API}/{quote(slug, safe='')}/jobs", ttl=DISCOVERY_TTL)
        if resp.status != 200:
            return ProbeResult(found=False, board_name=None, count=0)
        count = len(as_list(as_dict(data).get("jobs")))
        name = self._board_name(slug, client, DISCOVERY_TTL) if count else None
        return ProbeResult(found=True, board_name=name, count=count)

    def parse_url(self, url: str) -> str | None:
        host, segments, query = split_url(url)
        if host in API_HOSTS and segment(segments, 1) == "boards":
            return valid_slug(segment(segments, 2))
        if host in BOARD_HOSTS:
            if segment(segments, 0) == "embed":
                return valid_slug(query.get("for"))
            return valid_slug(segment(segments, 0))
        return None

    # ------------------------------------------------------------ helpers

    @staticmethod
    def _board_name(slug: str, client: HttpClient, ttl: float) -> str | None:
        try:
            resp, data = fetch_json(client, f"{API}/{quote(slug, safe='')}", ttl=ttl)
        except BotWallError:
            raise
        except HttpError:
            return None
        name = clean_text(as_dict(data).get("name"))
        return name or None

    @staticmethod
    def _job(board: Board, item: Mapping[str, Any]) -> Job | str:
        job_id = clean_id(item.get("id"))
        if job_id is None:
            return bad_id(item.get("id"))
        title = clean_text(item.get("title"))
        if not title:
            return "no title"
        location = as_location(item.get("location"))
        if not location:
            location = join_unique(as_location(o) for o in as_list(item.get("offices")))
        url = clean_text(item.get("absolute_url"))
        if not url:
            url = f"https://job-boards.greenhouse.io/{board.slug}/jobs/{job_id}"
        remote, workplace = workplace_from_text(location)
        department = join_unique(as_location(d) for d in as_list(item.get("departments")))
        return make_job(
            board,
            job_id,
            title,
            url,
            location=location,
            remote=remote,
            workplace=workplace,
            posted=to_date(item.get("first_published") or item.get("updated_at")),
            department=department or None,
            description=jd_from_html(item.get("content")),
        )
