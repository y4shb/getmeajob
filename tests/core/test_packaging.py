from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.mark.slow
def test_sdist_ships_the_plugin_docs_and_examples(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build = pytest.importorskip("hatchling.build")
    monkeypatch.chdir(REPO)
    name = build.build_sdist(str(tmp_path))
    with tarfile.open(tmp_path / name) as sdist:
        files = {n.split("/", 1)[1] for n in sdist.getnames() if "/" in n}
    for path in (
        ".claude-plugin/marketplace.json",
        "agents/claude-plugin/commands/tracker.md",
        "config/profile.example.yaml",
        "docs/SPEC.md",
        "examples/demo/profile.yaml",
        "examples/mock_forms/greenhouse.html",
        "scripts/scan_sensitive.py",
        "LICENSE",
        "NOTICE",
    ):
        assert path in files, path
