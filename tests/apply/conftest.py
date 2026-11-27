"""Fixtures for the apply tests.

- `ready_ws`: a copy of a demo workspace where both demo jobs have `ready` plans
  (built once per session with the real CLI: init --demo, source, rank, plan, answer).
- `use_forms(ws, greenhouse="captcha=1")`: point the demo form URLs at the local mock
  forms with a query-string variant.
- `set_apply(ws, **values)`: change the `apply:` block of preferences.yaml.
- `page`: a headless Chromium page (the test is skipped when Playwright or Chromium is
  missing). Tests that call `run_apply` must not also use `page`: one Playwright per thread.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from getmeajob.cli import main
from getmeajob.demo import examples_dir
from getmeajob.workspace import Workspace
from getmeajob.yamlio import dump_yaml, load_yaml

GH_URL = "https://job-boards.greenhouse.io/embed/job_app?for=examplecorp&token=1001"
ASHBY_URL = (
    "https://jobs.ashbyhq.com/samplesystems/5a1e0000-0000-4000-8000-000000000001/application"
)
ANSWER = "I like building reliable backend systems and the team works on problems I care about."


@pytest.fixture(scope="session")
def _template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("apply-template") / "ws"
    home = ["--home", str(root), "--quiet"]
    for words in (["init", "--demo"], ["source"], ["rank"], ["plan"]):
        assert main([*home, *words]) == 0, words
    todo = root.parent / "todo.yaml"
    todo.write_text(
        json.dumps(
            {"by_company": {"examplecorp": {"Why do you want to join Example Corp?": ANSWER}}}
        ),
        encoding="utf-8",
    )
    assert main([*home, "plan", "answer", str(todo)]) == 0
    assert main([*home, "plan"]) == 0
    return root


@pytest.fixture
def ready_ws(_template: Path, tmp_path: Path) -> Workspace:
    root = tmp_path / "ws"
    shutil.copytree(_template, root)
    for path in (root / "data" / "plans").glob("*.json"):
        text = path.read_text(encoding="utf-8").replace(str(_template), str(root))
        path.write_text(text, encoding="utf-8")
    return Workspace(root)


@pytest.fixture
def use_forms() -> Callable[..., None]:
    def apply(ws: Workspace, greenhouse: str = "", ashby: str = "") -> None:
        mocks = examples_dir() / "mock_forms"
        folder = ws.root / "fx"
        folder.mkdir(exist_ok=True)
        mapping = {
            GH_URL: str(mocks / "greenhouse.html") + (f"?{greenhouse}" if greenhouse else ""),
            ASHBY_URL: str(mocks / "ashby.html") + (f"?{ashby}" if ashby else ""),
        }
        (folder / "forms.json").write_text(json.dumps(mapping), encoding="utf-8")
        settings = load_yaml(ws.settings_path, required=False)
        settings["fixtures"] = "fx"
        dump_yaml(ws.settings_path, settings)

    return apply


@pytest.fixture
def set_apply() -> Callable[..., None]:
    def apply(ws: Workspace, **values: Any) -> None:
        prefs = load_yaml(ws.preferences_path)
        block = dict(prefs.get("apply") or {})
        block.update(values)
        prefs["apply"] = block
        dump_yaml(ws.preferences_path, prefs)

    return apply


@pytest.fixture
def page() -> Iterator[Any]:
    api = pytest.importorskip("playwright.sync_api")
    with api.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True)
        except api.Error as exc:  # pragma: no cover - depends on the machine
            pytest.skip(f"Chromium is not installed: {str(exc).splitlines()[0]}")
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        tab = context.new_page()
        tab.set_default_timeout(10_000)
        try:
            yield tab
        finally:
            browser.close()


@pytest.fixture
def open_mock(page: Any) -> Callable[..., Any]:
    def go(name: str, query: str = "") -> Any:
        uri = (examples_dir() / "mock_forms" / f"{name}.html").resolve().as_uri()
        page.goto(uri + (f"?{query}" if query else ""))
        return page

    return go
