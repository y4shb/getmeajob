"""`scripts/quickstart.sh` runs the README quick start end to end on the demo.

It runs the real script in a subprocess with the `getmeajob` installed next to the
Python running pytest, in a fresh folder under `tmp_path`. The demo is offline: board
replies come from recorded files and the forms are local mock pages.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.browser, pytest.mark.slow]

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "quickstart.sh"
GH_KEY = "greenhouse:examplecorp:1001"
ASHBY_KEY = "ashby:samplesystems:5a1e0000-0000-4000-8000-000000000001"


def _getmeajob() -> str:
    found = shutil.which("getmeajob", path=str(Path(sys.executable).parent))
    found = found or shutil.which("getmeajob")
    if found is None:
        pytest.skip("the getmeajob command is not installed (pip install -e .)")
    return found


def _require_chromium() -> None:
    api = pytest.importorskip("playwright.sync_api")
    with api.sync_playwright() as pw:
        try:
            pw.chromium.launch(headless=True).close()
        except api.Error as exc:  # pragma: no cover - depends on the machine
            pytest.skip(f"Chromium is not installed: {str(exc).splitlines()[0]}")


def _dry_ok_line(out: str, key: str) -> bool:
    return any(line.startswith(key) and " dry_ok " in line for line in out.splitlines())


def test_quickstart_runs_the_demo_end_to_end(tmp_path: Path) -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is not available")
    _require_chromium()
    env = {k: v for k, v in os.environ.items() if not k.startswith("GETMEAJOB_")}
    env["GETMEAJOB"] = _getmeajob()
    home = tmp_path / "demo"

    proc = subprocess.run(
        [bash, str(SCRIPT), str(home)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    out = proc.stdout
    assert _dry_ok_line(out, GH_KEY), out[-2000:]
    assert _dry_ok_line(out, ASHBY_KEY), out[-2000:]
    assert "dry run: 2 dry_ok." in out
    assert (home / "exports" / "tracker.xlsx").is_file()
    assert list((home / "shots").glob("dry-*-dry_ok.png"))


def test_quickstart_refuses_a_folder_that_is_not_empty(tmp_path: Path) -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is not available")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GETMEAJOB_")}
    env["GETMEAJOB"] = _getmeajob()
    home = tmp_path / "workspace"
    home.mkdir()
    (home / "profile.yaml").write_text("identity: {}\n", encoding="utf-8")

    proc = subprocess.run(
        [bash, str(SCRIPT), str(home)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert proc.returncode == 2
    assert "is not empty" in proc.stderr
    assert (home / "profile.yaml").read_text(encoding="utf-8") == "identity: {}\n"
