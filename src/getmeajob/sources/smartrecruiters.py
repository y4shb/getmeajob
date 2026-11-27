"""SmartRecruiters job boards (`api.smartrecruiters.com/v1/companies/<id>/postings`).

The list has no job text, so each job's detail record is fetched too. Details are
cached for 7 days, and at most `DETAIL_FETCH_LIMIT` are fetched from the network per
board per run; the rest keep their stored text and are fetched on a later run.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from getmeajob.errors import BotWallError, HttpError
from getmeajob.http import HttpClient
from getmeajob.models import Board, Job
from getmeajob.sources.base import ProbeResult, SourceResult
from getmeajob.sources.common import (
    DETAIL_TTL,
    DISCOVERY_TTL,
    LISTING_TTL,
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
    jd_from_parts,
    join_unique,
    make_job,
    place_with_workplace,
    segment,
    split_url,
    to_date,
    valid_slug,
)
from getmeajob.sources.geo import country_name

API = "https://api.smartrecruiters.com/v1/companies"
PAGE_SIZE = 100
MAX_JOBS = 1000
DETAIL_FETCH_LIMIT = 25
SECTION_ORDER = ("companyDescription", "jobDescription", "qualifications", "additionalInformation")


def _location(raw: Any) -> tuple[str, bool | None, str | None]:
    if not isinstance(raw, Mapping):
        location = as_location(raw)
        return location, None, None
    city = clean_text(raw.get("city"))
    country = country_name(clean_text(raw.get("country")))
    place = clean_text(raw.get("fullLocation")) or join_unique(
        [city, clean_text(raw.get("region")), country], ", "
    )
    if raw.get("remote") is True:
        location = f"Remote - {country}" if not city and country else place
        return place_with_workplace(location, "remote"), True, "remote"
    if raw.get("hybrid") is True:
        return place_with_workplace(place, "hybrid"), False, "hybrid"
    return place, (False if "remote" in raw else None), None


class SmartRecruitersSource:
    name = "smartrecruiters"

    def _postings(self, slug: str) -> str:
        return f"{API}/{quote(slug, safe='')}/postings"

    def list_jobs(self, board: Board, client: HttpClient) -> SourceResult:
        items: list[Any] = []
        seen: set[str] = set()
        total = 0
        name: str | None = None
        offset = 0
        while offset < MAX_JOBS:
            params = {"limit": PAGE_SIZE, "offset": offset}
            resp, data = fetch_json(
                client, self._postings(board.slug), params=params, ttl=LISTING_TTL
            )
            if resp.status == 404 and offset == 0:
                return SourceResult(found=False, jobs=[])
            if resp.status != 200:
                return SourceResult(found=False, jobs=[], error=f"HTTP {resp.status}")
            page = as_dict(data)
            content = as_list(page.get("content"))
            total = max(total, as_int(page.get("totalFound")))
            fresh = [c for c in content if self._raw_id(c) not in seen]
            seen.update(self._raw_id(c) for c in fresh)
            items += fresh
            name = name or self._company_name(content)
            if not fresh or len(content) < PAGE_SIZE or (total and len(items) >= total):
                break
            offset += PAGE_SIZE
        jobs, skipped = collect_jobs(board, items, lambda item: self._job(board, item))
        notes: list[str] = []
        partial = len(items) < total
        if partial:
            notes.append(f"smartrecruiters:{board.slug}: read {len(items)} of {total} jobs")
        jobs = self._add_details(board, jobs, client, notes)
        return SourceResult(True, jobs, name, skipped=skipped, notes=notes, partial=partial)

    def probe(self, slug: str, client: HttpClient) -> ProbeResult:
        params = {"limit": 1, "offset": 0}
        resp, data = fetch_json(client, self._postings(slug), params=params, ttl=DISCOVERY_TTL)
        if resp.status != 200:
            return ProbeResult(found=False, board_name=None, count=0)
        page = as_dict(data)
        content = as_list(page.get("content"))
        count = as_int(page.get("totalFound")) or len(content)
        return ProbeResult(found=True, board_name=self._company_name(content), count=count)

    def parse_url(self, url: str) -> str | None:
        host, segments, _ = split_url(url)
        if host in ("jobs.smartrecruiters.com", "careers.smartrecruiters.com"):
            if segment(segments, 0) == "oneclick-ui" and segment(segments, 1) == "company":
                return valid_slug(segment(segments, 2))
            return valid_slug(segment(segments, 0))
        if host == "api.smartrecruiters.com" and segment(segments, 1) == "companies":
            return valid_slug(segment(segments, 2))
        return None

    # ------------------------------------------------------------ helpers

    @staticmethod
    def _raw_id(item: Any) -> str:
        return clean_text(as_dict(item).get("id")) or repr(item)[:80]

    @staticmethod
    def _company_name(content: list[Any]) -> str | None:
        for item in content:
            name = clean_text(as_dict(as_dict(item).get("company")).get("name"))
            if name:
                return name
        return None

    @staticmethod
    def _job(board: Board, item: Mapping[str, Any]) -> Job | str:
        job_id = clean_id(item.get("id"))
        if job_id is None:
            return bad_id(item.get("id"))
        title = clean_text(item.get("name") or item.get("title"))
        if not title:
            return "no title"
        location, remote, workplace = _location(item.get("location"))
        company_id = clean_text(as_dict(item.get("company")).get("identifier")) or board.slug
        department = clean_text(as_dict(item.get("department")).get("label"))
        return make_job(
            board,
            job_id,
            title,
            f"https://jobs.smartrecruiters.com/{company_id}/{job_id}",
            location=location,
            remote=remote,
            workplace=workplace,
            posted=to_date(item.get("releasedDate")),
            department=department or None,
        )

    def _add_details(
        self, board: Board, jobs: list[Job], client: HttpClient, notes: list[str]
    ) -> list[Job]:
        out: list[Job] = []
        fetched = failed = waiting = 0
        for job in jobs:
            if fetched >= DETAIL_FETCH_LIMIT:
                waiting += 1
                out.append(job)
                continue
            url = f"{self._postings(board.slug)}/{quote(job.job_id, safe='')}"
            try:
                resp, data = fetch_json(client, url, ttl=DETAIL_TTL)
            except BotWallError:
                raise
            except HttpError:
                failed += 1
                out.append(job)
                continue
            fetched += 0 if resp.from_cache else 1
            out.append(self._with_detail(job, as_dict(data)) if data is not None else job)
        if failed:
            notes.append(f"smartrecruiters:{board.slug}: job text failed to load for {failed}")
        if waiting:
            notes.append(f"smartrecruiters:{board.slug}: job text for {waiting} left for next run")
        return out

    @staticmethod
    def _with_detail(job: Job, detail: Mapping[str, Any]) -> Job:
        sections = as_dict(as_dict(detail.get("jobAd")).get("sections"))
        parts: list[str] = []
        for key in SECTION_ORDER:
            section = as_dict(sections.get(key))
            heading = clean_text(section.get("title"))
            body = jd_from_html(section.get("text"))
            if body:
                parts.append(f"{heading}\n{body}" if heading else body)
        apply_url = clean_text(detail.get("applyUrl")) or job.apply_url
        url = clean_text(detail.get("postingUrl")) or job.url
        return dataclasses.replace(
            job, description=jd_from_parts(parts), apply_url=apply_url or None, url=url
        )
