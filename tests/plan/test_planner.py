from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from getmeajob.demo import examples_dir
from getmeajob.files import write_jsonl_atomic
from getmeajob.models import AppStatus, Job, Plan, PlanStatus, QueueKind
from getmeajob.plan.overrides import merge_answers
from getmeajob.plan.planner import load_plan, plan_run
from getmeajob.store import JobStore, QueueLog, StatusLog
from getmeajob.workspace import Workspace
from getmeajob.yamlio import dump_yaml, load_yaml

GH = "greenhouse:examplecorp:1001"
ASHBY = "ashby:samplesystems:5a1e0000-0000-4000-8000-000000000001"
WHY = "Why do you want to join Example Corp?"
SPONSOR = "Will you now or in the future require sponsorship for employment visa status?"


def _snapshot(ws: Workspace) -> dict[str, int]:
    return {
        str(p.relative_to(ws.root)): p.stat().st_mtime_ns
        for p in sorted(ws.root.rglob("*"))
        if p.is_file()
    }


def test_demo_plan_needs_answers_then_ready_after_answer(planned_ws: Workspace) -> None:
    run = plan_run(planned_ws, [GH, ASHBY])
    plans = {p.job_key: p for p in run.plans}
    gh = plans[GH]
    assert gh.status == PlanStatus.needs_answers
    assert [u.question_id for u in gh.unknowns] == ["question_2003", "question_2005"]
    assert "says which country" in gh.unknowns[0].reason  # remote, no country: never inferred
    answers = {a.question_id: a for a in gh.answers}
    assert answers["question_2002"].value == "Yes"
    assert answers["question_2004"].value == "3-5"
    assert answers["demographic_4001"].value == "Decline to self-identify"
    assert answers["cover_letter"].source == "skip"
    assert answers["question_2006[]"].source == "skip"
    assert answers["resume"].source == "file" and str(answers["resume"].value).endswith("base.pdf")
    assert gh.resume_path == "resume/base.pdf"  # relative, so moving the workspace is fine
    ashby = plans[ASHBY]
    assert ashby.status == PlanStatus.ready
    arrangement = {a.question_id: a for a in ashby.answers}["c0ffee00-0000-4000-8000-0000000000a5"]
    assert (arrangement.value, arrangement.source) == ("Hybrid", "override:global")
    stored = json.loads(planned_ws.plan_path(GH).read_text(encoding="utf-8"))
    assert stored["status"] == "needs_answers" and stored["inputs_hash"]

    merge_answers(
        planned_ws, {"by_company": {"examplecorp": {WHY: "Synthetic answer.", SPONSOR: "No"}}}
    )
    again = plan_run(planned_ws, [GH, ASHBY])
    gh = {p.job_key: p for p in again.plans}[GH]
    assert gh.status == PlanStatus.ready and not gh.unknowns
    why = {a.question_id: a for a in gh.answers}["question_2005"]
    assert (why.value, why.source) == ("Synthetic answer.", "override:company")
    assert again.reused == [ASHBY]


def test_second_plan_run_uses_cache(planned_ws: Workspace) -> None:
    first = plan_run(planned_ws, [GH, ASHBY])
    before = _snapshot(planned_ws)
    second = plan_run(planned_ws, [GH, ASHBY])
    assert sorted(second.reused) == sorted([GH, ASHBY])
    assert [p.to_dict() for p in second.plans] == [p.to_dict() for p in first.plans]
    assert _snapshot(planned_ws) == before  # touched no file at all
    refreshed = plan_run(planned_ws, [GH], refresh=True)
    assert refreshed.reused == []


def test_blocked_on_automation_refusal(
    planned_ws: Workspace, tmp_path: Path, make_job: Callable[..., Job]
) -> None:
    fixtures = tmp_path / "fx"
    shutil.copytree(examples_dir() / "fixtures", fixtures)
    target = fixtures / "http/boards-api.greenhouse.io/v1/boards/examplecorp/jobs/1009.json"
    data = json.loads((target.parent / "1001.json").read_text(encoding="utf-8"))
    data["questions"][10]["description"] = (
        "<p>Please do not use automated tools or AI agents to complete this application.</p>"
    )
    target.write_text(json.dumps(data), encoding="utf-8")
    (planned_ws.root / "settings.yaml").write_text(f"fixtures: {fixtures}\n", encoding="utf-8")
    key = "greenhouse:examplecorp:1009"
    JobStore(planned_ws).upsert([make_job(key, "Example Corp", "X", "Remote")], "2026-11-27T00:00Z")
    plan = plan_run(planned_ws, [key]).plans[0]
    assert plan.status == PlanStatus.blocked
    assert plan.blocked_reason == "automation_refused"
    assert plan.answers == [] and plan.unknowns == []
    items = [i for i in QueueLog(planned_ws).open_items() if i.job_key == key]
    assert [i.kind for i in items] == [QueueKind.automation_refused]
    assert "automated tools" in items[0].detail
    assert StatusLog(planned_ws).current(key) is None


def test_job_text_refusing_tools_blocks_the_plan(
    planned_ws: Workspace, make_job: Callable[..., Job]
) -> None:
    def plan_with(text: str) -> Plan:
        job = make_job(GH, "Example Corp", "Senior Backend Engineer", "Remote - Worldwide")
        job.description = text
        JobStore(planned_ws).upsert([job], "2026-11-27T00:00:00Z")
        return plan_run(planned_ws, [GH]).plans[0]

    harmless = "We never use automated tools to screen candidates. A person reads each one."
    assert plan_with(harmless).status == PlanStatus.needs_answers
    refusal = "Please do not use AI tools or automated tools to apply for this role."
    plan = plan_with(f"{harmless}\n{refusal}")
    assert (plan.status, plan.blocked_reason) == (PlanStatus.blocked, "automation_refused")
    (item,) = [i for i in QueueLog(planned_ws).open_items() if i.job_key == GH]
    assert item.kind == QueueKind.automation_refused and f'"{refusal}"' in item.detail


def test_queue_item_added_and_resolved(planned_ws: Workspace) -> None:
    plan_run(planned_ws, [GH])
    queue = QueueLog(planned_ws)
    open_items = [i for i in queue.open_items() if i.job_key == GH]
    assert [i.kind for i in open_items] == [QueueKind.needs_answers]
    assert WHY in open_items[0].detail
    status = StatusLog(planned_ws)
    assert status.current(GH) == AppStatus.planned
    answers = {"question_2005": "Synthetic answer.", "question_2003": "No"}
    merge_answers(planned_ws, {"by_job": {GH: answers}})
    plan_run(planned_ws, [GH])
    assert [i for i in QueueLog(planned_ws).open_items() if i.job_key == GH] == []
    history = [(e.status, e.source) for e in StatusLog(planned_ws).history(GH)]
    assert history == [(AppStatus.planned, "plan"), (AppStatus.ready, "plan")]


def test_saved_answer_must_match_options(planned_ws: Workspace) -> None:
    merge_answers(planned_ws, {"global": {"Preferred work arrangement": "Four-day week"}})
    plan = plan_run(planned_ws, [ASHBY]).plans[0]
    arrangement = {a.question_id: a for a in plan.answers}["c0ffee00-0000-4000-8000-0000000000a5"]
    assert arrangement.source == "skip" and "not one of the options" in arrangement.note
    merge_answers(planned_ws, {"by_job": {GH: {"question_2004": "7"}}})
    gh = plan_run(planned_ws, [GH]).plans[0]
    assert {u.question_id for u in gh.unknowns} == {
        "question_2003",
        "question_2004",
        "question_2005",
    }


def test_default_selection_reads_ranked_shortlist(planned_ws: Workspace) -> None:
    run = plan_run(planned_ws, None)
    assert run.ranked_missing and run.plans == []
    rows = [
        {"key": GH, "eligible": True, "score": 90},
        {"key": "greenhouse:examplecorp:1002", "eligible": False, "score": 95},
        {"key": ASHBY, "eligible": True, "score": 70},
        {
            "key": "lever:demowidgets:7c0de000-0000-4000-8000-000000000001",
            "eligible": True,
            "score": 55,
        },
        {"key": "ashby:samplesystems:low", "eligible": True, "score": 10},
    ]
    write_jsonl_atomic(planned_ws.ranked_path, rows)
    run = plan_run(planned_ws, None)
    assert [p.job_key for p in run.plans] == [GH, ASHBY]
    assert [k for k, _ in run.skipped] == ["lever:demowidgets:7c0de000-0000-4000-8000-000000000001"]
    assert "lever" in run.skipped[0][1]
    assert [p.job_key for p in plan_run(planned_ws, None, min_score=80).plans] == [GH]


def test_role_resume_wins_and_missing_resume_is_unknown(planned_ws: Workspace) -> None:
    role = planned_ws.roles_dir / "example-corp-senior-backend-engineer"
    role.mkdir(parents=True)
    (role / "meta.yaml").write_text(f"job_keys: ['{GH}']\n", encoding="utf-8")
    (role / "resume.pdf").write_bytes(b"%PDF-1.4 synthetic")
    plan = plan_run(planned_ws, [GH]).plans[0]
    assert plan.resume_path == "roles/example-corp-senior-backend-engineer/resume.pdf"
    (role / "resume.pdf").unlink()
    (planned_ws.root / "resume" / "base.pdf").unlink()
    plan = plan_run(planned_ws, [GH]).plans[0]
    assert plan.resume_path is None
    assert "resume" in {u.question_id for u in plan.unknowns}


def test_schema_unavailable_and_unknown_key(planned_ws: Workspace) -> None:
    key = "ashby:samplesystems:5a1e0000-0000-4000-8000-000000000002"
    JobStore(planned_ws).upsert(
        [
            Job(
                key,
                "ashby",
                "samplesystems",
                key.split(":")[2],
                "Sample Systems",
                "Data Analyst",
                "https://jobs.example.com/x",
            )
        ],
        "2026-11-27T00:00:00Z",
    )
    run = plan_run(planned_ws, [key, "greenhouse:nobody:1"])
    assert run.plans[0].status == PlanStatus.schema_unavailable
    assert run.plans[0].blocked_reason
    assert load_plan(planned_ws, key) is not None
    assert run.skipped == [("greenhouse:nobody:1", "not in data/jobs.jsonl (run getmeajob source)")]


def test_file_answers_stay_inside_the_workspace(
    planned_ws: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("synthetic", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert planned_ws.root.parent == tmp_path
    for name in (str(secret), "~/secret.txt", "../secret.txt"):
        merge_answers(planned_ws, {"by_job": {GH: {"resume": name}}})
        plan = plan_run(planned_ws, [GH]).plans[0]
        resume = next(u for u in plan.unknowns if u.question_id == "resume")
        assert "outside the workspace" in resume.reason, name
    profile = load_yaml(planned_ws.profile_path)
    profile["files"]["cover_letter"] = "~/secret.txt"  # your own choice in profile.yaml
    dump_yaml(planned_ws.profile_path, profile)
    merge_answers(planned_ws, {"by_job": {GH: {"cover_letter": "~/secret.txt"}}})
    plan = plan_run(planned_ws, [GH]).plans[0]
    cover = next(a for a in plan.answers if a.question_id == "cover_letter")
    assert cover.value == str(secret.resolve())
