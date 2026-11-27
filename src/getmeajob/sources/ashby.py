"""Ashby job boards (`api.ashbyhq.com/posting-api`)."""

from __future__ import annotations

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
    clean_block,
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
    truncate_jd,
    valid_slug,
    workplace_of,
)

API = "https://api.ashbyhq.com/posting-api/job-board"


def _listed(item: Mapping[str, Any]) -> bool:
    return item.get("isListed") is not False


class AshbySource:
    name = "ashby"

    def list_jobs(self, board: Board, client: HttpClient) -> SourceResult:
        url = f"{API}/{quote(board.slug, safe='')}"
        resp, data = fetch_json(
            client, url, params={"includeCompensation": "true"}, ttl=LISTING_TTL
        )
        if resp.status == 404:
            return SourceResult(found=False, jobs=[])
        if resp.status != 200:
            return SourceResult(found=False, jobs=[], error=f"HTTP {resp.status}")
        items = as_dict(data).get("jobs")
        if not isinstance(items, list):
            return SourceResult(found=False, jobs=[], error="the reply has no 'jobs' list")
        listed = [i for i in items if not isinstance(i, Mapping) or _listed(i)]
        jobs, skipped = collect_jobs(board, listed, lambda item: self._job(board, item))
        hidden = len(items) - len(listed)
        if hidden:
            skipped.append(f"ashby:{board.slug}: {hidden} unlisted job(s) left out")
        return SourceResult(True, jobs, self._name(data), skipped=skipped)

    def probe(self, slug: str, client: HttpClient) -> ProbeResult:
        resp, data = fetch_json(client, f"{API}/{quote(slug, safe='')}", ttl=DISCOVERY_TTL)
        if resp.status != 200:
            return ProbeResult(found=False, board_name=None, count=0)
        items = as_list(as_dict(data).get("jobs"))
        count = sum(1 for i in items if isinstance(i, Mapping) and _listed(i))
        return ProbeResult(found=True, board_name=self._name(data), count=count)

    def parse_url(self, url: str) -> str | None:
        host, segments, _ = split_url(url)
        if host == "jobs.ashbyhq.com":
            return valid_slug(segment(segments, 0))
        if host == "api.ashbyhq.com" and segment(segments, 1) == "job-board":
            return valid_slug(segment(segments, 2))
        return None

    # ------------------------------------------------------------ helpers

    @staticmethod
    def _name(data: Any) -> str | None:
        # The public posting API usually has no board name; use one if it is there.
        info = as_dict(data)
        name = clean_text(info.get("organizationName") or info.get("name"))
        return name or None

    @staticmethod
    def _location(item: Mapping[str, Any], workplace: str | None) -> str:
        places = [as_location(item.get("location"))]
        places += [as_location(s) for s in as_list(item.get("secondaryLocations"))]
        location = join_unique(places)
        postal = as_dict(as_dict(item.get("address")).get("postalAddress"))
        country = clean_text(postal.get("addressCountry"))
        if country and country.casefold() not in location.casefold():
            location = f"{location}, {country}" if location else country
        return place_with_workplace(location, workplace)

    @classmethod
    def _job(cls, board: Board, item: Mapping[str, Any]) -> Job | str:
        job_id = clean_id(item.get("id"))
        if job_id is None:
            return bad_id(item.get("id"))
        title = clean_text(item.get("title"))
        if not title:
            return "no title"
        workplace = workplace_of(item.get("workplaceType"))
        if workplace is None and item.get("isRemote") is True:
            workplace = "remote"
        remote = None if workplace is None else workplace == "remote"
        url = clean_text(item.get("jobUrl")) or f"https://jobs.ashbyhq.com/{board.slug}/{job_id}"
        text = clean_block(item.get("descriptionPlain"))
        description = truncate_jd(text) if text else jd_from_html(item.get("descriptionHtml"))
        comp = as_dict(item.get("compensation"))
        summary = clean_text(
            comp.get("compensationTierSummary") or comp.get("scrapeableCompensationSalarySummary")
        )
        department = clean_text(item.get("department")) or clean_text(item.get("team"))
        return make_job(
            board,
            job_id,
            title,
            url,
            location=cls._location(item, workplace),
            remote=remote,
            workplace=workplace,
            apply_url=clean_text(item.get("applyUrl")) or None,
            posted=to_date(item.get("publishedAt")),
            department=department or None,
            comp=summary or None,
            description=description,
        )
