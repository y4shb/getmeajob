from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from getmeajob.demo import examples_dir
from getmeajob.http import HttpClient
from getmeajob.models import Job, Question, QuestionType
from getmeajob.plan.ashby_page import questions_from_page_fields
from getmeajob.plan.schema import (
    SchemaUnavailable,
    fetch_schema,
    form_url,
    parse_ashby,
    parse_greenhouse,
)
from getmeajob.workspace import Workspace

FIXTURES = examples_dir() / "fixtures"


def _by_id(questions: list[Question]) -> dict[str, Question]:
    return {q.id: q for q in questions}


def test_greenhouse_questions_fixture(
    tmp_ws: Workspace, demo_jobs: list[Job], fixture_client: Callable[[Path], HttpClient]
) -> None:
    job = demo_jobs[0]
    questions = fetch_schema(tmp_ws, fixture_client(FIXTURES), job)
    qs = _by_id(questions)
    assert qs["first_name"].required and qs["email"].type == QuestionType.email
    assert qs["resume"].type == QuestionType.file  # the paste-text twin is ignored
    assert "resume_text" not in qs
    assert qs["question_2002"].type == QuestionType.select
    assert [(o.label, o.value) for o in qs["question_2002"].options] == [("Yes", "1"), ("No", "0")]
    assert [o.label for o in qs["question_2004"].options] == ["0-2", "3-5", "6-9", "10+"]
    assert qs["question_2005"].type == QuestionType.textarea
    assert qs["question_2005"].description == "A few sentences are enough."
    assert qs["question_2006[]"].type == QuestionType.multiselect
    assert qs["candidate-location"].type == QuestionType.location
    assert qs["candidate-location"].section == "location"
    gender = qs["demographic_4001"]
    assert gender.section == "demographic" and "Decline to self-identify" in [
        o.label for o in gender.options
    ]
    assert qs["education"].type == QuestionType.education_history
    assert not qs["education"].required
    assert tmp_ws.schema_path(job.key).is_file()
    assert form_url(job) == (
        "https://job-boards.greenhouse.io/embed/job_app?for=examplecorp&token=1001"
    )


def test_ashby_graphql_fixture(
    tmp_ws: Workspace, demo_jobs: list[Job], fixture_client: Callable[[Path], HttpClient]
) -> None:
    job = demo_jobs[1]
    questions = fetch_schema(tmp_ws, fixture_client(FIXTURES), job, page_reader=None)
    qs = _by_id(questions)
    assert list(qs)[:3] == ["_systemfield_name", "_systemfield_email", "_systemfield_resume"]
    sponsor = qs["c0ffee00-0000-4000-8000-0000000000a2"]
    assert sponsor.type == QuestionType.boolean and [o.label for o in sponsor.options] == [
        "Yes",
        "No",
    ]
    assert qs["c0ffee00-0000-4000-8000-0000000000a3"].type == QuestionType.location
    assert qs["c0ffee00-0000-4000-8000-0000000000a4"].type == QuestionType.number
    arrangement = qs["c0ffee00-0000-4000-8000-0000000000a5"]
    assert not arrangement.required and [o.label for o in arrangement.options] == [
        "Remote",
        "Hybrid",
        "Onsite",
    ]
    assert qs["c0ffee00-0000-4000-8000-0000000000a6"].type == QuestionType.textarea
    assert form_url(job).endswith("/samplesystems/5a1e0000-0000-4000-8000-000000000001/application")


def test_ashby_falls_back_when_request_fails(
    tmp_ws: Workspace,
    tmp_path: Path,
    demo_jobs: list[Job],
    fixture_client: Callable[[Path], HttpClient],
) -> None:
    empty = tmp_path / "no-fixtures"
    empty.mkdir()
    seen: list[str] = []

    def reader(url: str) -> list[Question]:
        seen.append(url)
        return questions_from_page_fields(
            [{"id": "name", "label": "Name*", "kind": "text", "required": False}]
        )

    job = demo_jobs[1]
    questions = fetch_schema(tmp_ws, fixture_client(empty), job, page_reader=reader)
    assert seen == [form_url(job)]
    assert questions[0].label == "Name" and questions[0].required
    with pytest.raises(SchemaUnavailable) as info:
        fetch_schema(tmp_ws, fixture_client(empty), job, page_reader=None, refresh=True)
    assert "Playwright" in info.value.message


def test_offline_demo_never_opens_a_browser(demo_ws: Workspace) -> None:
    from getmeajob.plan.schema import default_page_reader

    assert default_page_reader(demo_ws) is None


def test_messy_payload_degrades() -> None:
    zw = "​"
    data = {
        "questions": [
            {
                "label": None,
                "required": True,
                "fields": [{"name": "question_9", "type": "input_text"}],
            },
            {
                "label": f"Pre{zw}ferred name",
                "fields": [{"name": "preferred_name", "type": "input_text"}],
            },
            {
                "label": "Signature",
                "required": True,
                "fields": [{"name": "sig", "type": "signature_pad"}],
            },
            {
                "label": "Mood",
                "required": False,
                "fields": [{"name": "mood", "type": "emoji_picker"}],
            },
            {
                "label": "Pick one",
                "required": True,
                "fields": [
                    {
                        "name": "pick",
                        "type": "multi_value_single_select",
                        "values": [
                            "Red",
                            {"label": "Green", "value": 2},
                            {"name": "Blue"},
                            None,
                            7,
                            [],
                        ],
                    }
                ],
            },
            {"label": "No fields at all", "required": True},
            "not a question",
            None,
            {"label": "Duplicate", "fields": [{"name": "pick", "type": "input_text"}]},
        ],
        "location_questions": None,
        "compliance": [{"questions": [{"label": "Disability", "fields": "oops"}]}, "junk"],
        "demographic_questions": [
            {"questions": [{"id": 5, "label": "Age", "answer_options": "x"}]}
        ],
    }
    qs = _by_id(parse_greenhouse(data))
    assert qs["question_9"].label == "question_9"  # null label falls back to the field name
    assert qs["preferred_name"].label == "Preferred name"  # invisible character removed
    assert qs["sig"].type == QuestionType.unknown and qs["sig"].board_type == "signature_pad"
    assert qs["mood"].type == QuestionType.unknown
    assert [o.label for o in qs["pick"].options] == ["Red", "Green", "Blue", "7"]
    assert "pick-2" in qs  # duplicate ids are kept apart
    assert any(
        q.label == "No fields at all" and q.type == QuestionType.unknown for q in qs.values()
    )
    assert any(q.label == "Disability" for q in qs.values())
    assert "demographic_5" in qs

    ashby = {
        "data": {
            "jobPosting": {
                "applicationForm": {
                    "sections": [
                        None,
                        {
                            "fieldEntries": [
                                {
                                    "field": json.dumps(
                                        {"path": "p1", "type": "Mystery", "title": None}
                                    ),
                                    "isRequired": True,
                                },
                                {"field": "{not json", "id": "e2"},
                                {
                                    "field": {
                                        "path": "p3",
                                        "type": "ValueSelect",
                                        "title": "T",
                                        "selectableValues": [{"label": None, "value": "v"}],
                                    }
                                },
                                "junk",
                            ]
                        },
                    ]
                }
            }
        }
    }
    aq = _by_id(parse_ashby(ashby))
    assert aq["p1"].type == QuestionType.unknown and aq["p1"].label == "p1" and aq["p1"].required
    assert aq["e2"].type == QuestionType.unknown
    assert [o.label for o in aq["p3"].options] == ["v"]
    with pytest.raises(SchemaUnavailable):
        parse_ashby({"data": None, "errors": [{"message": "nope"}]})
    with pytest.raises(SchemaUnavailable):
        parse_ashby(["not", "a", "mapping"])


def test_schema_cache_is_fresh_for_24_hours(
    tmp_ws: Workspace,
    tmp_path: Path,
    demo_jobs: list[Job],
    fixture_client: Callable[[Path], HttpClient],
) -> None:
    job = demo_jobs[0]
    first = fetch_schema(tmp_ws, fixture_client(FIXTURES), job)
    empty = tmp_path / "empty"
    empty.mkdir()
    again = fetch_schema(tmp_ws, fixture_client(empty), job)  # served from data/schemas
    assert again == first
    path = tmp_ws.schema_path(job.key)
    record = json.loads(path.read_text(encoding="utf-8"))
    record["fetched_ts"] = time.time() - 25 * 3600
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(SchemaUnavailable):
        fetch_schema(tmp_ws, fixture_client(empty), job)
    assert os.path.getsize(path) > 0


def test_page_fields_parse() -> None:
    qs = questions_from_page_fields(
        [
            {"id": "a", "label": "Email *", "kind": "email"},
            {"id": "b", "label": "Do you need a visa?", "kind": "yesno", "options": ["Yes", "No"]},
            {"id": "c", "label": "Location", "kind": "combobox"},
            {"id": "d", "label": "Fancy", "kind": "slider", "required": True},
            "junk",
        ]
    )
    assert [q.type for q in qs] == [
        QuestionType.email,
        QuestionType.boolean,
        QuestionType.location,
        QuestionType.unknown,
    ]
    assert qs[0].required and qs[0].label == "Email"
