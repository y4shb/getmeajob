"""MCP pieces that need no `mcp` package: the text guard, `mcp config` and the hint
printed when the package is missing."""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

import pytest

from getmeajob.cli import main
from getmeajob.errors import GetmeajobError
from getmeajob.mcp import server as server_module
from getmeajob.mcp.config import snippets
from getmeajob.mcp.specs import TOOL_SPECS
from getmeajob.mcp.text import MAX_CHARS, clip, guarded
from getmeajob.mcp.tools import Tools
from getmeajob.workspace import Workspace


def test_clip_keeps_short_text_and_cuts_long_text() -> None:
    assert clip("short") == "short"
    long = "\n".join(f"line {i} " + "x" * 50 for i in range(200))
    cut = clip(long)
    assert len(cut) <= MAX_CHARS and cut.endswith("--json)")


def test_guarded_turns_errors_into_text() -> None:
    @guarded
    def friendly() -> str:
        raise GetmeajobError("Something is off.", hint="Do this instead.")

    @guarded
    def crash() -> str:
        raise KeyError("x")

    assert friendly() == "error: Something is off.\nhint: Do this instead."
    text = crash()
    assert text.startswith("error: KeyError") and "hint:" in text


def test_every_spec_names_a_tool_method() -> None:
    tools = Tools(Workspace(Path("unused")))
    assert len({s.name for s in TOOL_SPECS}) == len(TOOL_SPECS) == 11
    for spec in TOOL_SPECS:
        assert spec.name == f"getmeajob_{spec.method}"
        assert callable(getattr(tools, spec.method))


def test_answer_needs_one_scope(demo_ws: Workspace) -> None:
    text = Tools(demo_ws).answer({"Q": "A"}, company="examplecorp", job_key="greenhouse:x:1")
    assert text.startswith("error: Give company or job_key, not both.")
    assert Tools(demo_ws).answer({"Q": ["", " "]}).startswith("error: Refused")


def test_config_snippets_parse(tmp_path: Path) -> None:
    data = snippets(tmp_path / "ws", python="/opt/py/bin/python3")
    server = data["claude-desktop"]["mcpServers"]["getmeajob"]
    assert server == {
        "command": "/opt/py/bin/python3",
        "args": ["-m", "getmeajob", "mcp"],
        "env": {"GETMEAJOB_HOME": str(tmp_path / "ws")},
    }
    codex = tomllib.loads(data["codex"])["mcp_servers"]["getmeajob"]
    assert codex["command"] == "/opt/py/bin/python3"
    assert codex["env"] == {"GETMEAJOB_HOME": str(tmp_path / "ws")}
    assert data["claude-code"].startswith("claude mcp add getmeajob -e ")
    assert data["claude-code"].endswith("-- /opt/py/bin/python3 -m getmeajob mcp")
    assert "remote MCP servers over HTTPS" in data["chatgpt"]


def test_mcp_config_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    home = tmp_path / "ws"
    assert main(["mcp", "config", "--home", str(home), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["workspace"] == str(home) and data["workspace_exists"] is False
    assert main(["mcp", "config", "--home", str(home), "--client", "codex"]) == 0
    out = capsys.readouterr().out
    assert "[mcp_servers.getmeajob]" in out and "Claude Desktop" not in out
    assert "getmeajob init" in out  # the workspace does not exist yet
    assert len(out.splitlines()) < 40


def test_missing_mcp_package_prints_an_install_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(sys.modules, "mcp.server.mcpserver", None)  # import now fails
    monkeypatch.setattr(server_module, "_mcp_version", lambda: None)
    assert main(["mcp", "--home", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "needs the optional `mcp` package" in err
    assert 'pip install "getmeajob[mcp]"' in err

    monkeypatch.setattr(server_module, "_mcp_version", lambda: "1.9.0")
    with pytest.raises(GetmeajobError, match="version 2 or newer"):
        server_module.build_server(Workspace(tmp_path))
