"""`getmeajob apply` and `getmeajob inspect` from the command line."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from getmeajob.cli import main
from getmeajob.workspace import Workspace

GH_URL = "https://job-boards.greenhouse.io/embed/job_app?for=examplecorp&token=1001"


@pytest.mark.parametrize(
    "words",
    [
        ["apply"],
        ["apply", "--mode", "submit"],
        ["apply", "greenhouse:examplecorp:1001", "--mode", "hold", "--headed"],
        ["inspect", GH_URL],
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


def _fails(capsys: pytest.CaptureFixture[str], argv: list[str]) -> str:
    capsys.readouterr()
    assert main(argv) == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err
    return err


def test_submit_refused_hold_needs_headed(
    ready_ws: Workspace, capsys: pytest.CaptureFixture[str]
) -> None:
    home = ["--home", str(ready_ws.root)]
    err = _fails(capsys, [*home, "apply", "--mode", "submit"])
    assert "submit_boards" in err and "hint:" in err
    err = _fails(capsys, [*home, "apply", "--mode", "hold"])
    assert "--headed" in err
    err = _fails(capsys, [*home, "apply", "--click-submit"])
    assert "--mode hold" in err


def test_playwright_missing_hint(
    ready_ws: Workspace, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    err = _fails(capsys, ["--home", str(ready_ws.root), "apply", "--mode", "dry"])
    assert 'pip install -e ".[browser]"' in err and "playwright install chromium" in err


def test_skips_print_without_a_browser(
    ready_ws: Workspace, capsys: pytest.CaptureFixture[str], set_apply: Callable[..., None]
) -> None:
    set_apply(ready_ws, exclude=["examplecorp", "samplesystems"])
    capsys.readouterr()
    assert main(["--home", str(ready_ws.root), "--json", "apply"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["mode"] == "dry"
    assert {r["status"] for r in data["results"]} == {"skipped_excluded"}
    assert main(["--home", str(ready_ws.root), "apply"]) == 0
    out = capsys.readouterr().out
    assert "dry run: 2 skipped_excluded." in out and len(out.splitlines()) < 10


@pytest.mark.browser
def test_inspect_lists_fields_and_options(
    ready_ws: Workspace, capsys: pytest.CaptureFixture[str]
) -> None:
    pytest.importorskip("playwright.sync_api")
    capsys.readouterr()
    assert main(["--home", str(ready_ws.root), "--json", "inspect", GH_URL]) == 0
    data = json.loads(capsys.readouterr().out)
    fields = {f["field"]: f for f in data["fields"]}
    assert fields["question_2004"]["kind"] == "react-select"
    assert fields["question_2004"]["options"] == ["0-2", "3-5", "6-9", "10+"]
    assert fields["question_2004"]["required"] is True
    assert fields["question_2006[]"]["options"] == ["Python", "Go", "Kubernetes", "Rust"]
    assert fields["first_name"]["label"].startswith("First Name")
    assert data["signals"] == []
    assert main(["--home", str(ready_ws.root), "inspect", GH_URL, "--limit", "5"]) == 0
    out = capsys.readouterr().out
    assert "more (use --limit or --json)" in out and len(out.splitlines()) <= 9
