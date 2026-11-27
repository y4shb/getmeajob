"""Drafting with a fake provider only (no network, no model)."""

from __future__ import annotations

import sys

import pytest

from getmeajob.errors import GetmeajobError
from getmeajob.files import write_json_atomic
from getmeajob.models import Plan, PlanStatus, QuestionType, UnknownQuestion
from getmeajob.plan.draft import (
    ASK_HUMAN,
    CommandProvider,
    DraftResult,
    draft_unknowns,
    provider_named,
)
from getmeajob.plan.overrides import approve_job, load_answers
from getmeajob.plan.planner import plan_run
from getmeajob.workspace import Workspace

GH = "greenhouse:examplecorp:1001"


class FakeProvider:
    def __init__(self, reply: str = "I enjoy building reliable backend services.") -> None:
        self.reply = reply
        self.prompts: list[str] = []
        self.cache_id = "fake"

    def complete(self, prompt: str, max_tokens: int) -> DraftResult:
        self.prompts.append(prompt)
        return DraftResult(self.reply, 300, 60)


def _u(qid: str, label: str, qtype: QuestionType = QuestionType.textarea) -> UnknownQuestion:
    return UnknownQuestion(qid, label, qtype, True, [], "no rule fits", f"{label}#x")


def _plan_with(ws: Workspace, key: str, unknowns: list[UnknownQuestion]) -> None:
    plan = Plan(
        key,
        key.split(":")[0],
        "Example Corp",
        "Senior Backend Engineer",
        "https://jobs.example.com/1",
        "https://jobs.example.com/1/apply",
        PlanStatus.needs_answers,
        [],
        unknowns,
    )
    write_json_atomic(ws.plan_path(key), plan.to_dict())


def test_budget_stops_calls(demo_ws: Workspace) -> None:
    _plan_with(
        demo_ws,
        GH,
        [
            _u("a", "Why do you want to join Example Corp?"),
            _u("b", "What would you build first in this role?"),
        ],
    )
    fake = FakeProvider()
    report = draft_unknowns(demo_ws, fake, budget_tokens=900)
    assert len(fake.prompts) == 1 and report.calls == 1
    assert report.stopped_at_budget
    assert [s["reason"] for s in report.skipped] == ["token budget reached"]
    assert report.tokens_used == 360


def test_cache_hit_no_call(demo_ws: Workspace) -> None:
    _plan_with(demo_ws, GH, [_u("a", "Why do you want to join Example Corp?")])
    first = FakeProvider()
    draft_unknowns(demo_ws, first, budget_tokens=5000)
    second = FakeProvider()
    report = draft_unknowns(demo_ws, second, budget_tokens=5000)
    assert len(first.prompts) == 1 and second.prompts == []
    assert report.from_cache == 1 and report.calls == 0 and report.tokens_used == 0
    assert list(demo_ws.llm_cache_dir.glob("*.json"))


def test_factual_questions_never_drafted(demo_ws: Workspace) -> None:
    factual = [
        _u("s", "What are your salary expectations?"),
        _u("v", "Do you need a visa to work here?"),
        _u("y", "How many years have you used Go?"),
        _u("d", "Earliest start date"),
        _u("g", "Gender identity (optional)"),
        _u("e", "Alternative email"),
        _u("ai", "Describe how you use AI tools"),
        _u("sel", "Pick a team", QuestionType.select),
    ]
    _plan_with(demo_ws, GH, [*factual, _u("ok", "What would you build first in this role?")])
    fake = FakeProvider()
    report = draft_unknowns(demo_ws, fake, budget_tokens=10_000)
    assert [d["question_id"] for d in report.drafted] == ["ok"]
    assert len(fake.prompts) == 1 and len(report.skipped) == len(factual)
    prompt = fake.prompts[0]
    assert "What would you build first" in prompt and ASK_HUMAN in prompt
    assert "Initech Example Ltd" in prompt  # facts come from the profile only


def test_ask_human_reply_is_not_saved(demo_ws: Workspace) -> None:
    _plan_with(demo_ws, GH, [_u("a", "Tell us about your proudest project")])
    report = draft_unknowns(demo_ws, FakeProvider(ASK_HUMAN), budget_tokens=5000)
    assert report.drafted == [] and len(report.asked_human) == 1
    assert load_answers(demo_ws).by_job == {}


def test_drafts_marked_needs_review(planned_ws: Workspace) -> None:
    plan_run(planned_ws, [GH])
    report = draft_unknowns(planned_ws, FakeProvider(), budget_tokens=5000)
    assert [d["question_id"] for d in report.drafted] == ["question_2005"]
    entry = load_answers(planned_ws).by_job[GH]["question_2005"]
    assert entry["needs_review"] is True and entry["source"] == "draft"
    plan = plan_run(planned_ws, [GH]).plans[0]
    drafted = {a.question_id: a for a in plan.answers}["question_2005"]
    assert (drafted.source, drafted.needs_review) == ("draft", True)
    assert plan.status == PlanStatus.ready
    assert approve_job(planned_ws, GH) == 1
    plan = plan_run(planned_ws, [GH]).plans[0]
    assert {a.question_id: a for a in plan.answers}["question_2005"].needs_review is False


def test_command_provider_reads_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = CommandProvider([sys.executable, "-c", "import sys; print(sys.stdin.read()[::-1])"])
    result = provider.complete("olleh", 50)
    assert result.text == "hello" and result.input_tokens == 2
    with pytest.raises(GetmeajobError):
        CommandProvider([sys.executable, "-c", "import sys; sys.exit(3)"]).complete("x", 5)
    monkeypatch.setenv("GETMEAJOB_LLM_COMMAND", f"{sys.executable} -c 'print(1)'")
    assert isinstance(provider_named(None), CommandProvider)
    monkeypatch.delenv("GETMEAJOB_LLM_COMMAND")
    with pytest.raises(GetmeajobError):
        provider_named("command")
