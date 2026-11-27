from __future__ import annotations

import json
from collections.abc import Callable

from getmeajob.cli import main
from getmeajob.files import read_jsonl, write_json_atomic, write_jsonl_atomic
from getmeajob.models import Plan, QuestionType, UnknownQuestion
from getmeajob.plan.plans import load_plan
from getmeajob.tokens.context import context_for
from getmeajob.workspace import Workspace

Cli = Callable[..., tuple[int, str, str]]
GH = "greenhouse:examplecorp:1001"


def test_context_under_2000_chars(pipeline_ws: Workspace, cli: Cli) -> None:
    assert main(["resume", "tailor", GH, "--home", str(pipeline_ws.root), "-q"]) == 0
    code, out, _ = cli(pipeline_ws, "context", "1001")
    assert code == 0
    assert len(out) < 2000
    for part in (
        "job: Senior Backend Engineer at Example Corp",
        "url: https://job-boards.greenhouse.io/examplecorp/jobs/1001",
        "where: Remote - Worldwide",
        "experience: ",
        "rank: 99/100, eligible",
        "plan: needs_answers, 2 unknown(s)",
        "? Why do you want to join Example Corp?",
        "resume: roles/example-corp-senior-backend-engineer",
        "keyword gaps: none",
    ):
        assert part in out, part


def test_context_stays_small_for_a_messy_job(pipeline_ws: Workspace, cli: Cli) -> None:
    ranked = read_jsonl(pipeline_ws.ranked_path)
    for row in ranked:
        if row["key"] == GH:
            row["reasons"] = ["a very long reason " * 30] * 12
            row["flags"] = [{"code": "x", "reason": "long flag " * 40, "hard": True}] * 10
    write_jsonl_atomic(pipeline_ws.ranked_path, ranked)
    plan = load_plan(pipeline_ws, GH)
    assert isinstance(plan, Plan)
    plan.unknowns = [
        UnknownQuestion(
            f"q{n}", "Tell us everything " * 20, QuestionType.textarea, True, [], "", f"d{n}"
        )
        for n in range(30)
    ]
    write_json_atomic(pipeline_ws.plan_path(GH), plan.to_dict())
    code, out, _ = cli(pipeline_ws, "context", GH)
    assert code == 0 and len(out) < 2000
    data = json.loads(cli(pipeline_ws, "--json", "context", GH)[1])
    assert len(data["text"]) < 2000 and data["rank"]["score"] == 99


def test_context_for_unranked_job(demo_ws: Workspace, cli: Cli) -> None:
    assert main(["source", "--home", str(demo_ws.root), "-q"]) == 0
    code, out, _ = cli(demo_ws, "context", GH)
    assert code == 0
    assert "rank: not ranked yet" in out and "plan: none yet" in out


def test_unknown_key_is_friendly(pipeline_ws: Workspace, cli: Cli) -> None:
    code, out, err = cli(pipeline_ws, "context", "no-such-job")
    assert code == 2 and "hint:" in err and "Traceback" not in out + err


def test_context_for_is_the_same_text(pipeline_ws: Workspace, cli: Cli) -> None:
    text = context_for(pipeline_ws, "1001")
    assert cli(pipeline_ws, "context", GH)[1] == text + "\n"
