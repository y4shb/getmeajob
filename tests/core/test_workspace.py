from __future__ import annotations

import re
from pathlib import Path

import pytest

from getmeajob.errors import WorkspaceMissing
from getmeajob.workspace import Workspace, key_to_filename


def test_resolve_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert Workspace.resolve().root == (tmp_path / "workspace").resolve()

    monkeypatch.setenv("GETMEAJOB_HOME", str(tmp_path / "from-env"))
    assert Workspace.resolve().root == (tmp_path / "from-env").resolve()

    assert Workspace.resolve(tmp_path / "from-arg").root == (tmp_path / "from-arg").resolve()
    assert Workspace.resolve(str(tmp_path / "s")).root == (tmp_path / "s").resolve()
    # An empty argument counts as "not given".
    assert Workspace.resolve("").root == (tmp_path / "from-env").resolve()


def test_key_to_filename_safe_and_capped() -> None:
    assert key_to_filename("greenhouse:examplecorp:1001") == "greenhouse__examplecorp__1001"
    weird = key_to_filename("ashby:sample systems:a/b\\c?*")
    assert re.fullmatch(r"[A-Za-z0-9._-]+", weird)
    assert "/" not in weird and "\\" not in weird
    assert key_to_filename("..") == "__"
    long_key = "lever:" + "x" * 300
    name = key_to_filename(long_key)
    assert len(name) == 150
    assert re.search(r"-[0-9a-f]{10}$", name)
    other = key_to_filename("lever:" + "x" * 299 + "y")
    assert other != name  # the hash keeps long keys apart


def test_require_missing_raises_with_hint(tmp_path: Path) -> None:
    ws = Workspace(tmp_path / "nothing-here")
    assert not ws.exists()
    with pytest.raises(WorkspaceMissing) as info:
        ws.require()
    assert info.value.hint is not None and "getmeajob init" in info.value.hint

    ws.root.mkdir()
    with pytest.raises(WorkspaceMissing) as info:
        ws.require()
    assert "profile.yaml" in info.value.message

    ws.profile_path.write_text("identity: {}\n", encoding="utf-8")
    assert ws.require() is ws


def test_paths_layout(tmp_ws: Workspace) -> None:
    root = tmp_ws.root
    assert tmp_ws.jobs_path == root / "data" / "jobs.jsonl"
    assert tmp_ws.resume_bank_path == root / "resume" / "bank.yaml"
    assert tmp_ws.http_cache_dir == root / "cache" / "http"
    assert tmp_ws.plan_path("a:b:c") == root / "data" / "plans" / "a__b__c.json"
    assert tmp_ws.jd_path("a:b:c").suffix == ".txt"
    assert tmp_ws.schema_path("a:b:c").parent == tmp_ws.schemas_dir
    for folder in (tmp_ws.jd_dir, tmp_ws.runs_dir, tmp_ws.llm_cache_dir, tmp_ws.exports_dir):
        assert folder.is_dir()
