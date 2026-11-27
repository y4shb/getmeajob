from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from getmeajob.cli import main
from getmeajob.workspace import Workspace

COMMANDS = [
    ["source"],
    ["boards"],
    ["discover", "names.txt"],
    ["import-portals", "portals.yml"],
    ["check-live"],
    ["jd", "greenhouse:examplecorp:1001"],
]


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


@pytest.mark.parametrize("command", COMMANDS, ids=lambda c: c[0])
def test_missing_workspace_friendly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: list[str]
) -> None:
    code, out, err = _run(capsys, "--home", str(tmp_path / "nowhere"), *command)
    assert code == 2 and out == ""
    assert "getmeajob init" in err and "hint:" in err and "Traceback" not in err


def test_source_demo_offline_prints_diff(
    demo_ws: Workspace, capsys: pytest.CaptureFixture[str]
) -> None:
    home = str(demo_ws.root)
    code, out, _ = _run(capsys, "--home", home, "source")
    assert code == 0
    lines = out.splitlines()
    assert lines[0] == "4 boards: 8 new, 0 changed, 0 closed, 0 unchanged."
    assert lines[1].split() == ["change", "company", "title", "location", "key"]
    assert (
        "greenhouse:examplecorp:1001" in out
        and "smartrecruiters:PlaceholderLabs:744000000000001" in out
    )
    assert "ashby:samplesystems:5a1e0000-0000-4000-8000-000000000001" in out  # keys never cut
    assert len(lines) < 40

    code, out, _ = _run(capsys, "--home", home, "source")
    assert code == 0 and out.splitlines()[0] == "4 boards: no changes (8 unchanged)."
    assert "greenhouse:examplecorp:1001" not in out

    code, out, _ = _run(capsys, "--home", home, "--json", "source", "--limit", "2")
    data = json.loads(out)
    assert (data["new"], data["changed"], data["closed"], data["unchanged"]) == (0, 0, 0, 8)
    assert data["rows"] == [] and data["errors"] == []


def test_source_limit_and_json_rows(demo_ws: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(capsys, "--home", str(demo_ws.root), "--json", "source", "--limit", "3")
    data = json.loads(out)
    assert code == 0 and data["new"] == 8 and len(data["rows"]) == 3 and data["more"] == 5
    assert data["rows"][0] == {
        "change": "new",
        "company": "Example Corp",
        "title": "Senior Backend Engineer",
        "location": "Remote - Worldwide",
        "key": "greenhouse:examplecorp:1001",
    }


def test_source_one_board_and_bad_spec(
    demo_ws: Workspace, capsys: pytest.CaptureFixture[str]
) -> None:
    home = str(demo_ws.root)
    code, out, _ = _run(capsys, "--home", home, "source", "--board", "lever:demowidgets")
    assert code == 0 and out.startswith("1 board: 1 new")
    code, _, err = _run(capsys, "--home", home, "source", "--board", "demowidgets")
    assert code == 2 and "ats:slug" in err
    code, _, err = _run(capsys, "--home", home, "source", "--feeds", "nosuchfeed")
    assert code == 2 and "Unknown feed" in err


def test_boards_jd_and_check_live(demo_ws: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    home = str(demo_ws.root)
    assert main(["--home", home, "--quiet", "source"]) == 0
    capsys.readouterr()
    code, out, _ = _run(capsys, "--home", home, "boards")
    assert code == 0 and out.startswith("4 boards in companies.yaml (4 enabled).")
    assert "PlaceholderLabs" in out

    code, out, _ = _run(capsys, "--home", home, "jd", "greenhouse:examplecorp:1001")
    assert code == 0 and out.splitlines()[0] == "Senior Backend Engineer at Example Corp"
    assert len(out.splitlines()) <= 12 and "skills you have: python" in out

    code, out, _ = _run(
        capsys, "--home", home, "jd", "greenhouse:examplecorp:1001", "--grep", "years"
    )
    assert code == 0 and "3-5 years of professional experience" in out

    code, out, _ = _run(
        capsys, "--home", home, "--json", "jd", "greenhouse:examplecorp:1003", "--full"
    )
    assert "unable to sponsor visas" in json.loads(out)["text"]

    code, _, err = _run(capsys, "--home", home, "jd", "greenhouse:examplecorp:1009")
    assert code == 2 and "Did you mean" in err
    code, out, _ = _run(capsys, "--home", home, "jd", "1002")  # a unique part of a key
    assert code == 0 and out.startswith("Staff Platform Engineer at Example Corp")
    code, _, err = _run(capsys, "--home", home, "jd", "examplecorp")
    assert code == 2 and "Did you mean greenhouse:examplecorp:" in err

    code, out, _ = _run(
        capsys, "--home", home, "--json", "check-live", "greenhouse:examplecorp:1001"
    )
    data = json.loads(out)
    assert data["results"] == [
        {"key": "greenhouse:examplecorp:1001", "state": "open", "why": "still on the board"}
    ]


def test_discover_writes_only_with_flag(
    demo_ws: Workspace, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = str(demo_ws.root)
    names = tmp_path / "names.txt"
    names.write_text("Euro Widgets, https://jobs.eu.lever.co/eurowidgets\n", encoding="utf-8")
    before = demo_ws.companies_path.read_text(encoding="utf-8")
    code, out, _ = _run(capsys, "--home", home, "discover", str(names))
    assert code == 0 and "lever:eurowidgets" in out and "--write" in out
    assert demo_ws.companies_path.read_text(encoding="utf-8") == before

    code, out, _ = _run(capsys, "--home", home, "discover", str(names), "--write")
    assert code == 0
    text = demo_ws.companies_path.read_text(encoding="utf-8")
    assert text.startswith("# Demo companies.")  # the comment block is kept
    entries = yaml.safe_load(text)["companies"]
    assert entries[-1] == {
        "name": "Euro Widgets",
        "ats": "lever",
        "slug": "eurowidgets",
        "region": "eu",
    }
    assert len(entries) == 5

    code, out, _ = _run(capsys, "--home", home, "discover", str(names), "--write")
    assert len(yaml.safe_load(demo_ws.companies_path.read_text())["companies"]) == 5
    code, _, err = _run(capsys, "--home", home, "discover", str(tmp_path / "missing.txt"))
    assert code == 2 and "does not exist" in err


def test_import_portals_cli(demo_ws: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    fixture = Path(__file__).parent / "fixtures" / "portals.yml"
    code, out, _ = _run(capsys, "--home", str(demo_ws.root), "import-portals", str(fixture))
    assert code == 0 and "Read 3 boards (0 new to companies.yaml)" in out
    assert "unsupported:" in out and "Nothing written." in out
