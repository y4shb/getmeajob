"""Form questions per job: fetched from the board, normalised into `Question`s, cached.

- Greenhouse: the public job board API with `questions=true`. `questions`,
  `location_questions`, `compliance`, `demographic_questions` and the education block
  all become questions (sections application, location, compliance, demographic,
  education).
- Ashby: the posting page's own form request (`non-user-graphql`, op ApiJobPosting).
  When it fails, the rendered page is read in Chromium (`ashby_page`), but only when
  Playwright is installed and getmeajob is not in offline mode.
- Schemas are cached in `data/schemas/<key>.json` and reused for 24 hours.

Messy payloads never crash the planner: null labels fall back to the field name,
options may be objects or strings, unknown field types become `QuestionType.unknown`.
"""

from __future__ import annotations

import importlib.util
import json
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import quote

from getmeajob.errors import GetmeajobError, HttpError
from getmeajob.files import now_iso, read_json, write_json_atomic
from getmeajob.http import HttpClient
from getmeajob.models import Job, Option, Question, QuestionType
from getmeajob.settings import load_settings
from getmeajob.sources.registry import ATS_FOR_FORMS
from getmeajob.textutil import html_to_text, short_hash, strip_invisible
from getmeajob.workspace import Workspace

SCHEMA_TTL = 24 * 3600.0
GREENHOUSE_JOB = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}"
ASHBY_GRAPHQL = "https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobPosting"
ASHBY_QUERY = (
    "query ApiJobPosting($organizationHostedJobsPageName: String!, $jobPostingId: String!) "
    "{ jobPosting(organizationHostedJobsPageName: $organizationHostedJobsPageName, "
    "jobPostingId: $jobPostingId) { id title applicationForm { id sections { title "
    "fieldEntries { ... on FormFieldEntry { id field isRequired descriptionHtml } } } } } }"
)

GREENHOUSE_TYPES = {
    "input_text": QuestionType.text,
    "textarea": QuestionType.textarea,
    "input_file": QuestionType.file,
    "input_hidden": QuestionType.hidden,
    "multi_value_single_select": QuestionType.select,
    "multi_value_multi_select": QuestionType.multiselect,
}
ASHBY_TYPES = {
    "String": QuestionType.text,
    "Email": QuestionType.email,
    "Phone": QuestionType.phone,
    "Number": QuestionType.number,
    "SocialLink": QuestionType.url,
    "Url": QuestionType.url,
    "LongText": QuestionType.textarea,
    "Boolean": QuestionType.boolean,
    "ValueSelect": QuestionType.select,
    "MultiValueSelect": QuestionType.multiselect,
    "File": QuestionType.file,
    "Location": QuestionType.location,
    "Date": QuestionType.date,
    "EducationHistory": QuestionType.education_history,
}

PageReader = Callable[[str], list[Question]]


class SchemaUnavailable(GetmeajobError):
    """The form questions for a job could not be read."""


class AshbySchemaUnavailable(SchemaUnavailable):
    """Ashby's form request failed or returned no posting."""


def form_url(job: Job) -> str:
    """Where the application form lives (Greenhouse embed form, Ashby application page)."""
    if job.ats == "greenhouse":
        return (
            "https://job-boards.greenhouse.io/embed/job_app"
            f"?for={quote(job.board)}&token={quote(job.job_id)}"
        )
    if job.ats == "ashby":
        return f"https://jobs.ashbyhq.com/{quote(job.board)}/{quote(job.job_id)}/application"
    return job.apply_url or job.url


# ------------------------------------------------------------------- helpers


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else []


def clean_label(value: Any) -> str:
    if value is None or isinstance(value, Mapping | list):
        return ""
    return " ".join(html_to_text(strip_invisible(str(value))).split())


def _options(raw: Any) -> list[Option]:
    """Options from a list of {label, value}, {name, id}, plain strings or numbers."""
    out: list[Option] = []
    for item in _list(raw):
        if isinstance(item, Mapping):
            label = clean_label(item.get("label") or item.get("name") or item.get("text"))
            value = item.get("value", item.get("id"))
            if not label and value is not None:
                label = clean_label(value)
            if label:
                out.append(Option(label=label, value=None if value is None else str(value)))
        elif item is not None and not isinstance(item, list):
            label = clean_label(item)
            if label:
                out.append(Option(label=label, value=label))
    return out


def _unique_id(wanted: str, label: str, seen: set[str]) -> str:
    base = wanted.strip() or f"q_{short_hash(label or str(len(seen)))}"
    qid, n = base, 2
    while qid in seen:
        qid, n = f"{base}-{n}", n + 1
    seen.add(qid)
    return qid


# ----------------------------------------------------------------- Greenhouse


def _gh_field(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    fields = [f for f in _list(raw.get("fields")) if isinstance(f, Mapping)]
    if not fields:
        return raw  # the demographic shape keeps type and options on the question itself
    for f in fields:
        if f.get("type") == "input_file":
            return f  # a "paste instead" textarea twin is ignored
    visible = [f for f in fields if f.get("type") != "input_hidden"]
    return visible[0] if visible else fields[0]


def _gh_question(raw: Mapping[str, Any], section: str, seen: set[str]) -> Question:
    fld = _gh_field(raw)
    name = clean_label(fld.get("name") or raw.get("name") or raw.get("id"))
    if name.isdigit():
        name = f"{section}_{name}"  # demographic questions carry only a number
    board_type = clean_label(fld.get("type"))
    label = clean_label(raw.get("label")) or name
    qtype = GREENHOUSE_TYPES.get(board_type, QuestionType.unknown)
    if qtype == QuestionType.text:
        low = name.casefold()
        if section == "location":
            qtype = QuestionType.location
        elif low == "email":
            qtype = QuestionType.email
        elif low == "phone":
            qtype = QuestionType.phone
    return Question(
        id=_unique_id(name, label, seen),
        label=label,
        type=qtype,
        required=raw.get("required") is True,
        options=_options(fld.get("values") or raw.get("answer_options") or fld.get("options")),
        description=html_to_text(str(raw.get("description") or ""), max_chars=1000),
        section=section,
        board_type=board_type or None,
    )


def parse_greenhouse(data: Mapping[str, Any]) -> list[Question]:
    seen: set[str] = set()
    out: list[Question] = []
    for raw in _list(data.get("questions")):
        if isinstance(raw, Mapping):
            out.append(_gh_question(raw, "application", seen))
    for raw in _list(data.get("location_questions")):
        if isinstance(raw, Mapping):
            out.append(_gh_question(raw, "location", seen))
    for block in _list(data.get("compliance")):
        if isinstance(block, Mapping):
            for raw in _list(block.get("questions")):
                if isinstance(raw, Mapping):
                    out.append(_gh_question(raw, "compliance", seen))
    demographic = data.get("demographic_questions")
    blocks = _list(demographic) if isinstance(demographic, list) else [demographic]
    for block in blocks:
        if isinstance(block, Mapping):
            for raw in _list(block.get("questions")):
                if isinstance(raw, Mapping):
                    out.append(_gh_question(raw, "demographic", seen))
    education = str(data.get("education") or "")
    if education in ("education_required", "education_optional"):
        out.append(
            Question(
                id=_unique_id("education", "Education", seen),
                label="Education",
                type=QuestionType.education_history,
                required=education == "education_required",
                section="education",
                board_type=education,
            )
        )
    return out


# ---------------------------------------------------------------------- Ashby


def parse_ashby(data: Any) -> list[Question]:
    inner = data.get("data") if isinstance(data, Mapping) else None
    posting = inner.get("jobPosting") if isinstance(inner, Mapping) else None
    if not isinstance(posting, Mapping):
        errors = data.get("errors") if isinstance(data, Mapping) else None
        why = "it returned errors" if errors else "it returned no posting"
        raise AshbySchemaUnavailable(f"Ashby's form request did not work: {why}.")
    form = posting.get("applicationForm")
    sections = _list(form.get("sections")) if isinstance(form, Mapping) else []
    seen: set[str] = set()
    out: list[Question] = []
    for section in sections:
        if not isinstance(section, Mapping):
            continue
        title = clean_label(section.get("title")) or None
        for entry in _list(section.get("fieldEntries")):
            if not isinstance(entry, Mapping):
                continue
            fld: Any = entry.get("field")
            if isinstance(fld, str):
                try:
                    fld = json.loads(fld)
                except json.JSONDecodeError:
                    fld = {}
            fld = fld if isinstance(fld, Mapping) else {}
            path = clean_label(fld.get("path") or entry.get("id"))
            board_type = clean_label(fld.get("type"))
            label = clean_label(fld.get("title")) or path
            qtype = ASHBY_TYPES.get(board_type, QuestionType.unknown)
            options = _options(fld.get("selectableValues"))
            if qtype == QuestionType.boolean and not options:
                options = [Option("Yes", "true"), Option("No", "false")]
            out.append(
                Question(
                    id=_unique_id(path, label, seen),
                    label=label,
                    type=qtype,
                    required=entry.get("isRequired") is True,
                    options=options,
                    description=html_to_text(str(entry.get("descriptionHtml") or ""), 1000),
                    section=title,
                    board_type=board_type or None,
                )
            )
    return out


# ---------------------------------------------------------------- fetching


def _greenhouse(client: HttpClient, job: Job) -> list[Question]:
    url = GREENHOUSE_JOB.format(board=quote(job.board), job_id=quote(job.job_id))
    try:
        resp = client.get(url, params={"questions": "true"})
    except HttpError as exc:
        raise SchemaUnavailable(f"Could not read the Greenhouse form: {exc.message}") from exc
    if resp.status != 200:
        gone = " (the job may be closed)" if resp.status in (404, 410) else ""
        raise SchemaUnavailable(f"Greenhouse answered HTTP {resp.status}{gone}.")
    data = resp.json()
    if not isinstance(data, Mapping):
        raise SchemaUnavailable("Greenhouse sent something that is not a job record.")
    return parse_greenhouse(data)


def _ashby_request(client: HttpClient, job: Job) -> list[Question]:
    payload = {
        "operationName": "ApiJobPosting",
        "variables": {"organizationHostedJobsPageName": job.board, "jobPostingId": job.job_id},
        "query": ASHBY_QUERY,
    }
    try:
        resp = client.post_json(ASHBY_GRAPHQL, payload)
    except HttpError as exc:
        raise AshbySchemaUnavailable(f"Ashby's form request failed: {exc.message}") from exc
    if resp.status != 200:
        raise AshbySchemaUnavailable(f"Ashby's form request answered HTTP {resp.status}.")
    return parse_ashby(resp.json())


def default_page_reader(ws: Workspace) -> PageReader | None:
    """The Chromium page reader, or None in offline mode or without Playwright."""
    if load_settings(ws).fixtures is not None:
        return None
    if importlib.util.find_spec("playwright") is None:
        return None
    from getmeajob.plan.ashby_page import schema_from_page

    return schema_from_page


def _ashby(client: HttpClient, job: Job, reader: PageReader | None) -> list[Question]:
    try:
        return _ashby_request(client, job)
    except AshbySchemaUnavailable as first:
        if reader is None:
            raise SchemaUnavailable(
                f"{first.message} Reading the page instead needs Playwright and the network.",
                hint="Install the browser extra (pip install -e '.[browser]') or try later.",
            ) from first
        url = form_url(job)
        try:
            client.get(url, check_robots=True)
        except HttpError as exc:
            raise SchemaUnavailable(f"{first.message} {exc.message}") from first
        try:
            return reader(url)
        except GetmeajobError:
            raise
        except Exception as exc:  # a browser crash must not stop the whole run
            raise SchemaUnavailable(f"Reading the Ashby page failed: {exc}") from exc


def _cached(ws: Workspace, job: Job) -> list[Question] | None:
    path = ws.schema_path(job.key)
    try:
        record = read_json(path, default=None)
    except GetmeajobError:
        return None
    if not isinstance(record, Mapping):
        return None
    fetched = record.get("fetched_ts")
    if not isinstance(fetched, int | float) or time.time() - fetched >= SCHEMA_TTL:
        return None
    try:
        return [Question.from_dict(q) for q in _list(record.get("questions"))]
    except GetmeajobError:
        return None


def fetch_schema(
    ws: Workspace,
    client: HttpClient,
    job: Job,
    *,
    refresh: bool = False,
    page_reader: PageReader | None | bool = True,
) -> list[Question]:
    """The form questions for `job`, from `data/schemas/` when younger than 24 hours.

    `page_reader` is the Ashby fallback: True picks the default (Chromium when allowed),
    None or False turns it off, a callable replaces it (tests). Raises SchemaUnavailable.
    """
    if job.ats not in ATS_FOR_FORMS:
        raise SchemaUnavailable(f"getmeajob cannot read {job.ats} forms yet.")
    if not refresh:
        cached = _cached(ws, job)
        if cached is not None:
            return cached
    if job.ats == "greenhouse":
        questions = _greenhouse(client, job)
    else:
        reader = default_page_reader(ws) if page_reader is True else page_reader or None
        questions = _ashby(client, job, reader if callable(reader) else None)
    record = {
        "job_key": job.key,
        "ats": job.ats,
        "fetched_at": now_iso(),
        "fetched_ts": time.time(),
        "questions": [q.to_dict() for q in questions],
    }
    write_json_atomic(ws.schema_path(job.key), record)
    return questions


def schema_hash(questions: list[Question]) -> str:
    return short_hash(json.dumps([q.to_dict() for q in questions], sort_keys=True))
