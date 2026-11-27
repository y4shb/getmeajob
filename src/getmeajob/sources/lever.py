"""Lever job boards (`api.lever.co`, and `api.eu.lever.co` for EU-hosted boards)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from getmeajob.http import HttpClient, Response
from getmeajob.models import Board, Job
from getmeajob.sources.base import ProbeResult, SourceResult
from getmeajob.sources.common import (
    DISCOVERY_TTL,
    LISTING_TTL,
    as_dict,
    as_list,
    as_location,
    as_str,
    bad_id,
    clean_block,
    clean_id,
    clean_text,
    collect_jobs,
    fetch_json,
    jd_from_html,
    jd_from_parts,
    join_unique,
    make_job,
    place_with_workplace,
    segment,
    split_url,
    to_date,
    valid_slug,
    workplace_of,
)

API_GLOBAL = "https://api.lever.co/v0/postings"
API_EU = "https://api.eu.lever.co/v0/postings"
BOARD_HOSTS = frozenset({"jobs.lever.co", "jobs.eu.lever.co"})
API_HOSTS = frozenset({"api.lever.co", "api.eu.lever.co"})
_PER = {"year": "a year", "month": "a month", "week": "a week", "day": "a day", "hour": "an hour"}


def api_bases(region: str | None) -> list[str]:
    """Hosts to try: EU only for `region: eu`, global then EU when no region is set."""
    wanted = (region or "").strip().casefold()
    if wanted == "eu":
        return [API_EU]
    if wanted:
        return [API_GLOBAL]
    return [API_GLOBAL, API_EU]


def lever_region(url: str) -> str | None:
    """ "eu" when a Lever URL is on the EU host."""
    host, _, _ = split_url(url)
    return "eu" if host in ("jobs.eu.lever.co", "api.eu.lever.co") else None


def _salary(item: Mapping[str, Any]) -> str | None:
    pay = as_dict(item.get("salaryRange"))
    low, high = pay.get("min"), pay.get("max")
    if isinstance(low, int | float) and isinstance(high, int | float):
        interval = clean_text(pay.get("interval")).casefold()
        per = next((word for unit, word in _PER.items() if unit in interval), "")
        parts = [clean_text(pay.get("currency")), f"{low:,.0f}-{high:,.0f}", per]
        return " ".join(p for p in parts if p)
    text = clean_text(item.get("salaryDescriptionPlain"))
    return text or None


class LeverSource:
    name = "lever"

    def _get(
        self, slug: str, region: str | None, client: HttpClient, ttl: float
    ) -> tuple[Response, Any, str]:
        bases = api_bases(region)
        for index, base in enumerate(bases):
            url = f"{base}/{quote(slug, safe='')}"
            resp, data = fetch_json(client, url, params={"mode": "json"}, ttl=ttl)
            if resp.status == 404 and index + 1 < len(bases):
                continue
            return resp, data, base
        raise AssertionError("unreachable")  # pragma: no cover

    def list_jobs(self, board: Board, client: HttpClient) -> SourceResult:
        resp, data, base = self._get(board.slug, board.region, client, LISTING_TTL)
        if resp.status == 404:
            return SourceResult(found=False, jobs=[])
        if resp.status != 200:
            return SourceResult(found=False, jobs=[], error=f"HTTP {resp.status}")
        if not isinstance(data, list):
            return SourceResult(found=False, jobs=[], error="the reply is not a list of jobs")
        notes: list[str] = []
        if base == API_EU and (board.region or "").casefold() != "eu":
            notes.append(
                f"lever:{board.slug} is on the EU host; add `region: eu` to skip a request"
            )
        jobs, skipped = collect_jobs(board, data, lambda item: self._job(board, item))
        return SourceResult(True, jobs, None, skipped=skipped, notes=notes)

    def probe(self, slug: str, client: HttpClient) -> ProbeResult:
        resp, data, _ = self._get(slug, None, client, DISCOVERY_TTL)
        if resp.status != 200 or not isinstance(data, list):
            return ProbeResult(found=False, board_name=None, count=0)
        return ProbeResult(found=True, board_name=None, count=len(data))

    def parse_url(self, url: str) -> str | None:
        host, segments, _ = split_url(url)
        if host in BOARD_HOSTS:
            return valid_slug(segment(segments, 0))
        if host in API_HOSTS and segment(segments, 1) == "postings":
            return valid_slug(segment(segments, 2))
        return None

    # ------------------------------------------------------------ helpers

    @staticmethod
    def _text(item: Mapping[str, Any]) -> str:
        parts = [clean_block(item.get("descriptionPlain")) or jd_from_html(item.get("description"))]
        for block in as_list(item.get("lists")):
            block = as_dict(block)
            heading = clean_text(block.get("text"))
            body = jd_from_html(block.get("content"))
            parts.append("\n".join(p for p in (heading, body) if p))
        parts.append(
            clean_block(item.get("additionalPlain")) or jd_from_html(item.get("additional"))
        )
        return jd_from_parts(parts)

    @classmethod
    def _job(cls, board: Board, item: Mapping[str, Any]) -> Job | str:
        job_id = clean_id(item.get("id"))
        if job_id is None:
            return bad_id(item.get("id"))
        title = clean_text(item.get("text") or item.get("title"))
        if not title:
            return "no title"
        cats = as_dict(item.get("categories"))
        places = as_list(cats.get("allLocations"))
        location = join_unique(as_location(p) for p in places) or as_location(cats.get("location"))
        workplace = workplace_of(item.get("workplaceType"))
        remote = None if workplace is None else workplace == "remote"
        slug = board.slug
        url = clean_text(item.get("hostedUrl")) or f"https://jobs.lever.co/{slug}/{job_id}"
        department = clean_text(cats.get("department")) or clean_text(cats.get("team"))
        return make_job(
            board,
            job_id,
            title,
            url,
            location=place_with_workplace(location, workplace),
            remote=remote,
            workplace=workplace,
            apply_url=clean_text(as_str(item.get("applyUrl"))) or None,
            posted=to_date(item.get("createdAt")),
            department=department or None,
            comp=_salary(item),
            description=cls._text(item),
        )
