"""`getmeajob agents list` and `getmeajob agents install --claude DIR [--flat]`."""

from __future__ import annotations

import json
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from getmeajob.agents import install
from getmeajob.agents.install import Assets, flatten_text, plugin_commands
from getmeajob.cli import main
from getmeajob.errors import GetmeajobError


def _json(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, dict)
    return data


def test_list_needs_no_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)  # no workspace here or anywhere it would look
    assert main(["agents", "list", "--json"]) == 0
    data = _json(capsys)
    names = [item["name"] for item in data["items"]]
    assert names[:3] == ["claude-plugin", "claude-flat", "mcp-server"]
    assert main(["agents", "list"]) == 0
    assert "getmeajob agents install --claude DIR --flat" in capsys.readouterr().out


def test_install_flat_copies_commands_and_skill(tmp_path: Path) -> None:
    assert main(["agents", "install", "--claude", str(tmp_path), "--flat", "--quiet"]) == 0
    commands = sorted(p.name for p in (tmp_path / ".claude" / "commands").iterdir())
    assert len(commands) == 10 and all(n.startswith("getmeajob-") for n in commands)
    assert "getmeajob-review-answers.md" in commands
    skill = tmp_path / ".claude" / "skills" / "getmeajob"
    assert {p.name for p in skill.iterdir()} == {"SKILL.md", "POLICY.md", "answer-review.md"}
    for path in [*(tmp_path / ".claude" / "commands").iterdir(), skill / "SKILL.md"]:
        text = path.read_text(encoding="utf-8")
        assert "/getmeajob:" not in text, path.name  # links point at the flat names
    plan = (tmp_path / ".claude" / "commands" / "getmeajob-plan.md").read_text(encoding="utf-8")
    assert "/getmeajob-review-answers" in plan


def test_install_flat_never_overwrites_without_force(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mine = tmp_path / ".claude" / "commands" / "getmeajob-status.md"
    mine.parent.mkdir(parents=True)
    mine.write_text("my own version\n", encoding="utf-8")
    assert main(["agents", "install", "--claude", str(tmp_path), "--flat"]) == 2
    err = capsys.readouterr().err
    assert "already there" in err and "--force" in err
    assert mine.read_text(encoding="utf-8") == "my own version\n"
    assert not (tmp_path / ".claude" / "commands" / "getmeajob-rank.md").exists()
    assert not (tmp_path / ".claude" / "skills").exists()  # nothing copied at all

    assert main(["agents", "install", "--claude", str(tmp_path), "--flat", "--force", "-q"]) == 0
    assert "getmeajob status" in mine.read_text(encoding="utf-8")


def test_install_flat_needs_an_existing_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["agents", "install", "--claude", str(tmp_path / "missing"), "--flat"]) == 2
    assert "does not exist" in capsys.readouterr().err


def test_install_without_flat_prints_the_plugin_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["agents", "install", "--claude", str(tmp_path), "--json"]) == 0
    data = _json(capsys)
    add, install = data["commands"]
    assert add.startswith("claude plugin marketplace add ")
    repo = Path(add.removeprefix("claude plugin marketplace add ").strip("'"))
    assert (repo / ".claude-plugin" / "marketplace.json").is_file()
    assert install == "claude plugin install getmeajob@getmeajob --scope project"
    assert not (tmp_path / ".claude").exists()  # printing only, nothing copied


def test_installed_wheel_names_the_repository_from_its_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta = Message()
    meta["Project-URL"] = "Homepage, https://example.com/getmeajob"
    meta["Project-URL"] = "Repository, https://github.com/example-org/getmeajob.git"
    monkeypatch.setattr(install.metadata, "metadata", lambda name: meta)
    wheel = Assets(tmp_path / "_agents")  # no .claude-plugin next to it, as in a wheel
    add = plugin_commands(wheel)[0]
    assert add == "claude plugin marketplace add example-org/getmeajob"
    monkeypatch.setattr(install.metadata, "metadata", lambda name: Message())
    with pytest.raises(GetmeajobError, match="does not name its repository"):
        plugin_commands(wheel)


def test_flatten_text_rewrites_plugin_links_only() -> None:
    text = "Next: /getmeajob:rank, then `getmeajob plan` or getmeajob_status."
    assert flatten_text(text) == "Next: /getmeajob-rank, then `getmeajob plan` or getmeajob_status."
