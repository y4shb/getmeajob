from __future__ import annotations

import argparse
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest
import yaml

from getmeajob import __version__, cli
from getmeajob.cli import Context, main
from getmeajob.errors import ConfigError
from getmeajob.settings import load_settings
from getmeajob.workspace import Workspace


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"getmeajob {__version__}"


def test_python_dash_m_version() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "getmeajob", "--version"], capture_output=True, text=True
    )
    assert proc.returncode == 0 and proc.stdout.strip() == f"getmeajob {__version__}"


def test_no_command_prints_short_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "init" in out and "getmeajob init --demo" in out
    assert len(out.splitlines()) < 40


def _needs_workspace_module() -> types.ModuleType:
    module = types.ModuleType("getmeajob_test_needs_ws")

    def handler(args: argparse.Namespace, ctx: Context) -> int:
        ctx.ws.require()
        ctx.out.emit({"ok": True, "json": ctx.out.json_mode})
        return 0

    def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
        sub.add_parser("needs-ws", help="test command").set_defaults(func=handler)

    module.register = register  # type: ignore[attr-defined]
    return module


def test_unknown_workspace_friendly_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _needs_workspace_module()
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(cli, "COMMAND_MODULES", [*cli.COMMAND_MODULES, module.__name__])
    missing = tmp_path / "no-workspace-here"
    code = main(["--home", str(missing), "needs-ws"])
    captured = capsys.readouterr()
    assert code == 2
    assert "error:" in captured.err and "hint:" in captured.err
    assert "getmeajob init" in captured.err
    assert "Traceback" not in captured.err + captured.out

    # Global options also work after the command name.
    Workspace(missing).root.mkdir()
    (missing / "profile.yaml").write_text("identity: {}\n", encoding="utf-8")
    assert main(["needs-ws", "--json", "--home", str(missing)]) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True, "json": True}


def test_init_demo_creates_workspace_and_pdf(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "ws"
    assert main(["--home", str(root), "init", "--demo"]) == 0
    assert "getmeajob source" in capsys.readouterr().out
    ws = Workspace(root)
    assert ws.exists()
    for path in (
        ws.profile_path,
        ws.preferences_path,
        ws.answers_path,
        ws.companies_path,
        ws.resume_bank_path,
        ws.settings_path,
    ):
        assert path.is_file(), path
    profile = yaml.safe_load(ws.profile_path.read_text(encoding="utf-8"))
    assert profile["identity"]["full_name"] == "Alex Example"
    pdf = (ws.resume_dir / "base.pdf").read_bytes()
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")
    assert b"Alex Example - synthetic resume for the getmeajob demo" in pdf
    settings = load_settings(ws)
    assert settings.offline and settings.fixtures is not None
    assert (settings.fixtures / "routes.json").is_file()
    assert (root / ".gitignore").read_text(encoding="utf-8").strip().endswith("*")

    # A second init refuses to overwrite, --force replaces.
    assert main(["--home", str(root), "init", "--demo"]) == 2
    assert "--force" in capsys.readouterr().err
    assert main(["--home", str(root), "init", "--demo", "--force", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["demo"] is True and "resume/base.pdf" in result["files"]


def test_init_without_demo_copies_templates(tmp_path: Path) -> None:
    root = tmp_path / "real"
    assert main(["--home", str(root), "init", "-q"]) == 0
    ws = Workspace(root)
    assert ws.exists() and ws.answers_path.is_file() and ws.companies_path.is_file()
    assert "fill in what is true for you" in ws.profile_path.read_text(encoding="utf-8")
    settings = load_settings(ws)
    assert not settings.offline and settings.fixtures is None


def test_demo_ws_fixture(demo_ws: Workspace) -> None:
    assert demo_ws.exists() and (demo_ws.resume_dir / "base.pdf").is_file()


def test_bad_settings_value_is_friendly(tmp_ws: Workspace) -> None:
    tmp_ws.settings_path.write_text("timeout: soon\n", encoding="utf-8")
    with pytest.raises(ConfigError) as info:
        load_settings(tmp_ws)
    assert "timeout" in info.value.message and info.value.hint
    tmp_ws.settings_path.write_text("timeout: [unclosed\n", encoding="utf-8")
    with pytest.raises(ConfigError) as info:
        load_settings(tmp_ws)
    assert "line" in info.value.message
