"""Fixtures: the demo workspace after `source`, `rank` and `plan` (all offline), and a
helper that runs the CLI and returns (exit code, stdout, stderr)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from getmeajob.cli import main
from getmeajob.workspace import Workspace

RunCli = Callable[..., tuple[int, str, str]]


@pytest.fixture
def pipeline_ws(demo_ws: Workspace) -> Workspace:
    for command in (["source"], ["rank"], ["plan"]):
        assert main([*command, "--home", str(demo_ws.root), "--quiet"]) == 0
    return demo_ws


@pytest.fixture
def cli(capsys: pytest.CaptureFixture[str]) -> RunCli:
    def run(ws: Workspace, *args: str) -> tuple[int, str, str]:
        capsys.readouterr()
        code = main([*args, "--home", str(ws.root)])
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return run
