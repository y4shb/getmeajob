"""The ledger and queue never hold answer text (no browser needed)."""

from __future__ import annotations

import dataclasses

from getmeajob.apply.record import Outcome, answers_digest, make_entry, write_attempt
from getmeajob.models import ApplyMode, ApplyStatus, QueueKind
from getmeajob.plan.plans import load_plan
from getmeajob.store import Ledger, QueueLog
from getmeajob.workspace import Workspace

GH = "greenhouse:examplecorp:1001"


def test_ledger_has_no_answer_text(ready_ws: Workspace) -> None:
    plan = load_plan(ready_ws, GH)
    assert plan is not None
    public = f"{plan.company} {plan.title} {plan.form_url}"
    values = [
        a.value
        for a in plan.answers
        if isinstance(a.value, str) and len(a.value) >= 4 and a.value not in public
    ]
    assert {"alex@example.com", "+1 555 0100", "Springfield, Ontario, Canada"} <= set(values)
    essay = next(a.value for a in plan.answers if a.question_id == "question_2005")
    outcome = Outcome(
        ApplyStatus.fill_problem,
        detail=f"filled 3 field(s); typed {essay}",
        problems=[
            "email (Email): the field did not keep alex@example.com",
            f"question_2005: rejected '{essay}'",
        ],
        screenshot=ready_ws.shots_dir / "dry-x-fill_problem.png",
    )
    entry = make_entry(ready_ws, plan, ApplyMode.dry, outcome, "run-1")
    write_attempt(ready_ws, entry)

    stored = ready_ws.ledger_path.read_text(encoding="utf-8")
    queued = ready_ws.queue_path.read_text(encoding="utf-8")
    for value in values:
        assert value not in stored
        assert value.casefold() not in queued.casefold()
    assert entry.answers_digest and entry.answers_digest.startswith("sha256:")
    assert entry.plan_path == "data/plans/greenhouse__examplecorp__1001.json"
    assert entry.screenshot == "shots/dry-x-fill_problem.png"
    assert [i.kind for i in QueueLog(ready_ws).open_items() if i.job_key == GH] == [
        QueueKind.fill_problem
    ]
    assert Ledger(ready_ws).last_status(GH) == ApplyStatus.fill_problem


def test_digest_changes_with_answers_only(ready_ws: Workspace) -> None:
    plan = load_plan(ready_ws, GH)
    assert plan is not None
    first = answers_digest(plan)
    assert answers_digest(dataclasses.replace(plan, created_at="later")) == first
    plan.answers[0].value = "Alexandra"
    assert answers_digest(plan) != first


def test_dry_ok_resolves_fill_problem_and_submitted_resolves_all(ready_ws: Workspace) -> None:
    plan = load_plan(ready_ws, GH)
    assert plan is not None
    queue = QueueLog(ready_ws)
    for status in (ApplyStatus.fill_problem, ApplyStatus.dry_ok):
        entry = make_entry(ready_ws, plan, ApplyMode.dry, Outcome(status, problems=["x"]), "r")
        write_attempt(ready_ws, entry)
    assert not [i for i in queue.open_items() if i.job_key == GH]
    write_attempt(
        ready_ws,
        make_entry(ready_ws, plan, ApplyMode.submit, Outcome(ApplyStatus.needs_email_code), "r"),
    )
    assert [i.kind for i in queue.open_items() if i.job_key == GH] == [QueueKind.needs_email_code]
    write_attempt(
        ready_ws, make_entry(ready_ws, plan, ApplyMode.hold, Outcome(ApplyStatus.submitted), "r")
    )
    assert not [i for i in queue.open_items() if i.job_key == GH]
