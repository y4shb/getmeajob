from __future__ import annotations

import io
import json
import socket
from pathlib import Path

import pytest

from getmeajob.errors import ConfigError
from getmeajob.models import AppStatus, Flag
from getmeajob.output import Output
from getmeajob.settings import load_settings
from getmeajob.workspace import Workspace
from getmeajob.yamlio import dump_yaml, get_path, load_yaml


def test_output_human_and_json_modes() -> None:
    human = io.StringIO()
    out = Output(json_mode=False, quiet=False, stream=human)
    rows = [{"key": "a:b:1", "score": 88, "ok": True}, {"key": "a:b:2", "score": None}]
    out.table(rows, ["key", "score", "ok"])
    out.line("hello")
    out.done("2 jobs", next_step="getmeajob plan")
    lines = human.getvalue().splitlines()
    assert lines[0].split() == ["key", "score", "ok"]
    assert lines[1].split() == ["a:b:1", "88", "yes"]
    assert lines[-2:] == ["2 jobs", "next: getmeajob plan"]

    machine = io.StringIO()
    out = Output(json_mode=True, quiet=False, stream=machine)
    out.table(rows, ["key"])
    out.line("ignored")
    out.done("ignored")
    out.emit({"status": AppStatus.applied, "flags": [Flag("x", "y")], "path": Path("a")})
    assert json.loads(machine.getvalue()) == {
        "status": "applied",
        "flags": [{"code": "x", "reason": "y", "hard": True}],
        "path": "a",
    }

    quiet = io.StringIO()
    Output(json_mode=False, quiet=True, stream=quiet).done("nothing")
    assert quiet.getvalue() == ""


def test_output_truncates_cells() -> None:
    stream = io.StringIO()
    Output(stream=stream).table([{"title": "x" * 100}], ["title"], max_col=10)
    assert stream.getvalue().splitlines()[1] == "x" * 9 + "…"


def test_yaml_roundtrip_and_errors(tmp_path: Path) -> None:
    path = tmp_path / "a.yaml"
    dump_yaml(path, {"name": "Café", "list": [1, 2], "nested": {"k": [{"x": 1}]}})
    data = load_yaml(path)
    assert data["name"] == "Café" and list(data) == ["name", "list", "nested"]
    assert get_path(data, "nested.k.0.x") == 1
    assert get_path(data, "nested.missing") is None and get_path(data, "list.9") is None
    assert load_yaml(tmp_path / "none.yaml", required=False) == {}
    with pytest.raises(ConfigError) as info:
        load_yaml(tmp_path / "none.yaml")
    assert "getmeajob init" in (info.value.hint or "")
    path.write_text("a: 1\n b: [\n", encoding="utf-8")
    with pytest.raises(ConfigError) as info:
        load_yaml(path)
    assert "line" in info.value.message and str(path) in info.value.message
    path.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_yaml(path)


def test_settings_defaults_file_and_env(
    tmp_ws: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = load_settings(tmp_ws)
    assert settings.fixtures is None and not settings.offline and settings.retries == 3
    tmp_ws.settings_path.write_text("offline: true\n", encoding="utf-8")
    assert not load_settings(tmp_ws).offline  # only fixtures switch getmeajob offline
    tmp_ws.settings_path.write_text("fixtures: fx\nmin_interval: 0\n", encoding="utf-8")
    settings = load_settings(tmp_ws)
    assert settings.fixtures == tmp_ws.root / "fx" and settings.min_interval == 0.0
    monkeypatch.setenv("GETMEAJOB_FIXTURES", str(tmp_path / "elsewhere"))
    settings = load_settings(tmp_ws)
    assert settings.offline and settings.fixtures == (tmp_path / "elsewhere").resolve()


def test_network_is_blocked_in_tests() -> None:
    with pytest.raises(RuntimeError, match="network"):
        socket.create_connection(("192.0.2.1", 9), timeout=0.1)
    with pytest.raises(RuntimeError, match="network"):
        socket.getaddrinfo("example.com", 443)
