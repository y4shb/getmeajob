"""Recruitee job boards (`<slug>.recruitee.com/api/offers/`)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

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
    jd_from_parts,
    join_unique,
    make_job,
    place_with_workplace,
    split_url,
    to_date,
)

_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_NOT_ACCOUNTS = frozenset({"www", "app", "api", "careers", "blog", "support", "help"})


def _api(slug: str) -> str | None:
    label = slug.strip().casefold()
    return f"https://{label}.recruitee.com/api/offers/" if _LABEL.match(label) else None


def _published(item: Mapping[str, Any]) -> bool:
    status = item.get("status")
    return status is None or clean_text(status).casefold() == "published"


class RecruiteeSource:
    name = "recruitee"

    def list_jobs(self, board: Board, client: HttpClient) -> SourceResult:
        url = _api(board.slug)
        if url is None:
            return SourceResult(found=False, jobs=[], error="the slug is not a valid host name")
        resp, data = fetch_json(client, url, ttl=LISTING_TTL)
        if resp.status == 404:
            return SourceResult(found=False, jobs=[])
        if resp.status != 200:
            return SourceResult(found=False, jobs=[], error=f"HTTP {resp.status}")
        items = as_dict(data).get("offers")
        if not isinstance(items, list):
            return SourceResult(found=False, jobs=[], error="the reply has no 'offers' list")
        live = [i for i in items if not isinstance(i, Mapping) or _published(i)]
        jobs, skipped = collect_jobs(board, live, lambda item: self._job(board, item))
        if len(live) < len(items):
            skipped.append(f"recruitee:{board.slug}: {len(items) - len(live)} unpublished left out")
        return SourceResult(True, jobs, self._name(live), skipped=skipped)

    def probe(self, slug: str, client: HttpClient) -> ProbeResult:
        url = _api(slug)
        if url is None:
            return ProbeResult(found=False, board_name=None, count=0)
        resp, data = fetch_json(client, url, ttl=DISCOVERY_TTL)
        if resp.status != 200:
            return ProbeResult(found=False, board_name=None, count=0)
        live = [i for i in as_list(as_dict(data).get("offers")) if isinstance(i, Mapping)]
        live = [i for i in live if _published(i)]
        return ProbeResult(found=True, board_name=self._name(live), count=len(live))

    def parse_url(self, url: str) -> str | None:
        host, _, _ = split_url(url)
        if host.endswith(".recruitee.com") and host.count(".") == 2:
            label = host.split(".")[0]
            return None if label in _NOT_ACCOUNTS or not _LABEL.match(label) else label
        return None

    @staticmethod
    def _name(items: list[Any]) -> str | None:
        for item in items:
            name = clean_text(as_dict(item).get("company_name"))
            if name:
                return name
        return None

    @staticmethod
    def _job(board: Board, item: Mapping[str, Any]) -> Job | str:
        job_id = clean_id(item.get("id"))
        if job_id is None:
            return bad_id(item.get("id"))
        title = clean_text(item.get("title"))
        if not title:
            return "no title"
        place = as_location(item.get("location"))
        if not place:
            place = join_unique(
                [clean_text(item.get("city")), clean_text(item.get("country"))], ", "
            )
        if item.get("remote") is True:
            workplace: str | None = "remote"
        elif item.get("hybrid") is True:
            workplace = "hybrid"
        elif item.get("on_site") is True:
            workplace = "onsite"
        else:
            workplace = None
        offer = clean_text(item.get("slug"))
        url = clean_text(item.get("careers_url"))
        if not url:
            url = f"https://{board.slug.casefold()}.recruitee.com/o/{offer or job_id}"
        text = jd_from_parts(
            [jd_from_html(item.get("description")), jd_from_html(item.get("requirements"))]
        )
        return make_job(
            board,
            job_id,
            title,
            url,
            location=place_with_workplace(place, workplace),
            remote=None if workplace is None else workplace == "remote",
            workplace=workplace,
            apply_url=clean_text(item.get("careers_apply_url")) or None,
            posted=to_date(item.get("published_at") or item.get("created_at")),
            department=clean_text(item.get("department")) or None,
            description=text,
        )
