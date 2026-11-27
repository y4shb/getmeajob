"""Workable job boards (`apply.workable.com/api/v1/widget/accounts/<slug>`)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

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
    place_with_workplace,
    segment,
    split_url,
    to_date,
    valid_slug,
)

API = "https://apply.workable.com/api/v1/widget/accounts"
_SHORTCODE = re.compile(r"/j/([A-Za-z0-9]+)")
_NOT_ACCOUNTS = frozenset({"www", "apply", "jobs", "api", "help", "resources"})


class WorkableSource:
    name = "workable"

    def list_jobs(self, board: Board, client: HttpClient) -> SourceResult:
        resp, data = fetch_json(client, f"{API}/{quote(board.slug, safe='')}", ttl=LISTING_TTL)
        if resp.status == 404:
            return SourceResult(found=False, jobs=[])
        if resp.status != 200:
            return SourceResult(found=False, jobs=[], error=f"HTTP {resp.status}")
        info = as_dict(data)
        items = info.get("jobs")
        if not isinstance(items, list):
            return SourceResult(found=False, jobs=[], error="the reply has no 'jobs' list")
        jobs, skipped = collect_jobs(board, items, lambda item: self._job(board, item))
        name = clean_text(info.get("name")) or None
        return SourceResult(True, jobs, name, skipped=skipped)

    def probe(self, slug: str, client: HttpClient) -> ProbeResult:
        resp, data = fetch_json(client, f"{API}/{quote(slug, safe='')}", ttl=DISCOVERY_TTL)
        if resp.status != 200:
            return ProbeResult(found=False, board_name=None, count=0)
        info = as_dict(data)
        name = clean_text(info.get("name")) or None
        return ProbeResult(found=True, board_name=name, count=len(as_list(info.get("jobs"))))

    def parse_url(self, url: str) -> str | None:
        host, segments, _ = split_url(url)
        if host == "apply.workable.com":
            if segment(segments, 0) == "api":
                return valid_slug(
                    segment(segments, 4) if segment(segments, 2) == "widget" else None
                )
            return valid_slug(segment(segments, 0))
        if host.endswith(".workable.com") and host.count(".") == 2:
            account = host.split(".")[0]
            return None if account in _NOT_ACCOUNTS else valid_slug(account)
        return None

    @staticmethod
    def _job(board: Board, item: Mapping[str, Any]) -> Job | str:
        url = clean_text(item.get("url") or item.get("shortlink"))
        raw_id = item.get("shortcode") or item.get("code")
        job_id = clean_id(raw_id)
        if job_id is None and (match := _SHORTCODE.search(url)):
            job_id = match.group(1)
        if job_id is None:
            return bad_id(raw_id)
        title = clean_text(item.get("title"))
        if not title:
            return "no title"
        city = clean_text(item.get("city"))
        country = clean_text(item.get("country"))
        place = join_unique([city, clean_text(item.get("state")), country], ", ")
        if not place:
            place = join_unique(as_location(p) for p in as_list(item.get("locations")))
        remote = item.get("telecommuting") is True
        if remote and not city and country:
            place = f"Remote - {country}"
        workplace = "remote" if remote else None
        return make_job(
            board,
            job_id,
            title,
            url or f"https://apply.workable.com/{board.slug}/j/{job_id}/",
            location=place_with_workplace(place, workplace),
            remote=True if remote else None,
            workplace=workplace,
            apply_url=clean_text(item.get("application_url")) or None,
            posted=to_date(item.get("published_on") or item.get("created_at")),
            department=clean_text(item.get("department")) or None,
            description=jd_from_html(item.get("description")),
        )
