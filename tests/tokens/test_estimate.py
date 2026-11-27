from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from getmeajob.cli import main
from getmeajob.tokens.estimate import estimate_tokens
from getmeajob.workspace import Workspace

Cli = Callable[..., tuple[int, str, str]]


def test_chars_over_four() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2
    assert estimate_tokens("é" * 8) == 2


def test_files_and_total_labelled_estimate(demo_ws: Workspace, cli: Cli) -> None:
    (demo_ws.root / "a.txt").write_text("x" * 400, encoding="utf-8")
    (demo_ws.root / "b.txt").write_text("y" * 41, encoding="utf-8")
    code, out, _ = cli(demo_ws, "tokens", "estimate", "a.txt", "b.txt")
    assert code == 0
    lines = out.splitlines()
    assert lines[0].split() == ["file", "chars", "tokens", "(estimate)"]
    assert "~100" in lines[1] and "~11" in lines[2]
    assert lines[-1].startswith("total: 441 chars, ~111 tokens") and "estimate" in lines[-1]
    data = json.loads(cli(demo_ws, "--json", "tokens", "estimate", "a.txt", "b.txt")[1])
    assert data["total_tokens_estimate"] == 111
    assert data["files"][0] == {"path": "a.txt", "chars": 400, "tokens_estimate": 100}
    assert "estimate" in data["method"]


def test_works_without_a_workspace(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    file = tmp_path / "prompt.md"
    file.write_text("hello world!", encoding="utf-8")
    code = main(["tokens", "estimate", str(file), "--home", str(tmp_path / "none")])
    assert code == 0 and "~3" in capsys.readouterr().out


def test_missing_file_is_friendly(demo_ws: Workspace, cli: Cli) -> None:
    code, out, err = cli(demo_ws, "tokens", "estimate", "nope.md")
    assert code == 2 and "There is no file" in err and "Traceback" not in out + err
