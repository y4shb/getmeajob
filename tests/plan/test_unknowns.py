from __future__ import annotations

from pathlib import Path

from getmeajob.files import write_json_atomic
from getmeajob.models import Plan, PlannedAnswer, PlanStatus, QuestionType, UnknownQuestion
from getmeajob.plan.overrides import load_answers, merge_answers
from getmeajob.plan.planner import plan_run
from getmeajob.plan.unknowns import collect_unknowns, review_table, write_stub
from getmeajob.textutil import norm_label, options_hash
from getmeajob.workspace import Workspace
from getmeajob.yamlio import load_yaml


def _unknown(qid: str, label: str, options: list[str], required: bool = True) -> UnknownQuestion:
    qtype = QuestionType.select if options else QuestionType.textarea
    return UnknownQuestion(
        question_id=qid,
        label=label,
        type=qtype,
        required=required,
        options=options,
        reason="no rule fits this question",
        dedupe_key=f"{norm_label(label)}#{options_hash(options)}",
    )


def _plan(key: str, company: str, unknowns: list[UnknownQuestion]) -> Plan:
    ats = key.split(":")[0]
    answers = [
        PlannedAnswer("email", "Email", QuestionType.email, "alex@example.com", "rule:email")
    ]
    return Plan(
        job_key=key,
        ats=ats,
        company=company,
        title="Engineer",
        url="https://jobs.example.com/x",
        form_url="https://jobs.example.com/x/apply",
        status=PlanStatus.needs_answers if unknowns else PlanStatus.ready,
        answers=answers,
        unknowns=unknowns,
    )


def _write(ws: Workspace, plans: list[Plan]) -> None:
    for plan in plans:
        write_json_atomic(ws.plan_path(plan.job_key), plan.to_dict())


def test_dedupes_across_jobs(tmp_ws: Workspace) -> None:
    yn = ["Yes", "No"]
    _write(
        tmp_ws,
        [
            _plan(
                "greenhouse:examplecorp:1",
                "Example Corp",
                [
                    _unknown("q_10", "Were you referred by an employee?", yn),
                    _unknown("q_11", "Why do you want to join Example Corp?", []),
                ],
            ),
            _plan(
                "ashby:samplesystems:2",
                "Sample Systems",
                [
                    _unknown("uuid-1", "Were you referred by an employee? *", ["No", "Yes"]),
                    _unknown(
                        "uuid-2", "Were you referred by an employee?", ["Yes", "No", "Unsure"]
                    ),
                ],
            ),
            _plan(
                "greenhouse:examplecorp:3",
                "Example Corp",
                [
                    _unknown("q_12", "Why do you want to join Example Corp?", [], required=False),
                ],
            ),
        ],
    )
    groups = collect_unknowns(tmp_ws)
    referred = [g for g in groups if g.label.startswith("Were you referred")]
    assert len(referred) == 2  # same label, different option sets stay apart
    main = max(referred, key=lambda g: len(g.jobs))
    assert main.jobs == ["ashby:samplesystems:2", "greenhouse:examplecorp:1"]
    assert sorted(main.companies) == ["Example Corp", "Sample Systems"]
    why = next(g for g in groups if g.label.startswith("Why"))
    assert why.required and len(why.jobs) == 2
    assert groups[0] is main or len(groups[0].jobs) == 2


def test_stub_roundtrip(tmp_ws: Workspace, tmp_path: Path) -> None:
    _write(
        tmp_ws,
        [
            _plan(
                "greenhouse:examplecorp:1",
                "Example Corp",
                [
                    _unknown("q_11", "Why do you want to join Example Corp?", []),
                    _unknown("q_10", "Were you referred?", ["Yes", "No"]),
                ],
            ),
            _plan(
                "ashby:samplesystems:2",
                "Sample Systems",
                [
                    _unknown("u1", "Were you referred?", ["Yes", "No"]),
                ],
            ),
        ],
    )
    stub = tmp_path / "todo.yaml"
    assert write_stub(collect_unknowns(tmp_ws), stub) == 2
    text = stub.read_text(encoding="utf-8")
    assert "# options: Yes | No" in text
    data = load_yaml(stub)
    assert data["global"] == {"Were you referred?": ""}
    assert data["by_company"] == {"examplecorp": {"Why do you want to join Example Corp?": ""}}
    assert merge_answers(tmp_ws, data) == 0  # empty answers are not saved
    data["global"]["Were you referred?"] = "No"
    assert merge_answers(tmp_ws, data) == 1
    assert load_answers(tmp_ws).global_ == {"Were you referred?": "No"}


def test_review_table_dedupes_rows(planned_ws: Workspace) -> None:
    plan_run(
        planned_ws,
        ["greenhouse:examplecorp:1001", "ashby:samplesystems:5a1e0000-0000-4000-8000-000000000001"],
    )
    table = review_table(planned_ws, None)
    emails = [r for r in table.rows if r[0] == "Email"]
    assert emails == [("Email", "alex@example.com", "rule:email", 2)]
    assert [g.label for g in table.unknowns] == [
        "Why do you want to join Example Corp?",
        "Will you now or in the future require sponsorship for employment visa status?",
    ]
    assert table.skipped == 3 and table.needs_review == []
    only_ashby = review_table(
        planned_ws, ["ashby:samplesystems:5a1e0000-0000-4000-8000-000000000001"]
    )
    assert only_ashby.unknowns == [] and all(r[3] == 1 for r in only_ashby.rows)
