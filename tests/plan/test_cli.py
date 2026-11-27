from __future__ import annotations

import json
from pathlib import Path

import pytest

from getmeajob.cli import main
from getmeajob.workspace import Workspace

GH = "greenhouse:examplecorp:1001"
ASHBY = "ashby:samplesystems:5a1e0000-0000-4000-8000-000000000001"


@pytest.mark.parametrize(
    "words",
    [
        ["plan"],
        ["plan", GH],
        ["plan", "show", GH],
        ["plan", "unknowns"],
        ["plan", "answer", "x.yaml"],
        ["plan", "review"],
        ["plan", "draft"],
        ["plan", "approve", GH],
    ],
)
def test_missing_workspace_friendly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], words: list[str]
) -> None:
    code = main(["--home", str(tmp_path / "nowhere"), *words])
    err = capsys.readouterr().err
    assert code == 2
    assert "hint:" in err and "getmeajob init" in err
    assert "Traceback" not in err


def _json(capsys: pytest.CaptureFixture[str], argv: list[str]) -> object:
    capsys.readouterr()
    assert main(argv) == 0
    return json.loads(capsys.readouterr().out)


def test_quickstart_flow(
    planned_ws: Workspace, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = ["--home", str(planned_ws.root)]
    out = _json(capsys, [*home, "--json", "plan", GH, ASHBY])
    assert isinstance(out, dict)
    assert {p["key"]: p["status"] for p in out["plans"]} == {GH: "needs_answers", ASHBY: "ready"}

    capsys.readouterr()
    assert main([*home, "plan", "unknowns"]) == 0
    text = capsys.readouterr().out
    assert "Why do you want to join Example Corp?" in text and len(text.splitlines()) < 40

    stub = tmp_path / "todo.yaml"
    assert main([*home, "-q", "plan", "unknowns", "--stub", str(stub)]) == 0
    filled = stub.read_text(encoding="utf-8").replace('Corp?": ""', 'Corp?": "Synthetic answer."')
    stub.write_text(filled, encoding="utf-8")
    saved = _json(capsys, [*home, "--json", "plan", "answer", str(stub)])
    assert isinstance(saved, dict) and saved["saved"] == 1

    out = _json(capsys, [*home, "--json", "plan", GH, ASHBY])
    assert isinstance(out, dict)
    assert {p["status"] for p in out["plans"]} == {"ready"}
    assert out["reused"] == [ASHBY]

    review = _json(capsys, [*home, "--json", "plan", "review"])
    assert isinstance(review, dict) and review["unknowns"] == []
    assert any(r["answer"] == "Synthetic answer." for r in review["rows"])

    capsys.readouterr()
    assert main([*home, "plan", "review"]) == 0
    assert len(capsys.readouterr().out.splitlines()) < 40
    shown = _json(capsys, [*home, "--json", "plan", "show", GH])
    assert isinstance(shown, dict) and shown["status"] == "ready"


def test_plan_without_ranking_prints_hint(
    planned_ws: Workspace, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--home", str(planned_ws.root), "plan"]) == 0
    out = capsys.readouterr().out
    assert "getmeajob rank" in out


def test_usage_errors_are_friendly(
    planned_ws: Workspace, capsys: pytest.CaptureFixture[str]
) -> None:
    home = ["--home", str(planned_ws.root)]
    assert main([*home, "plan", "show"]) == 2
    assert main([*home, "plan", "show", GH]) == 2  # no plan yet
    assert main([*home, "plan", GH, "--stub", "x.yaml"]) == 2
    err = capsys.readouterr().err
    assert err.count("error:") == 3 and "Traceback" not in err
