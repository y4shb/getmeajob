"""Hard stops: a bot check, an account wall, a refusal of automated tools.

Each stops before anything is typed, takes a screenshot, queues a task for the human,
and is never tried again by a later run.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from getmeajob.models import ApplyMode, ApplyStatus, QueueKind
from getmeajob.store import Ledger, QueueLog
from getmeajob.workspace import Workspace

pytestmark = pytest.mark.browser
pytest.importorskip("playwright.sync_api")

GH = "greenhouse:examplecorp:1001"
ASHBY = "ashby:samplesystems:5a1e0000-0000-4000-8000-000000000001"


def _no_filling(monkeypatch: pytest.MonkeyPatch) -> None:
    from getmeajob.apply.ashby import AshbyFiller
    from getmeajob.apply.greenhouse import GreenhouseFiller

    def never(*args: Any) -> Any:
        raise AssertionError("a form behind a hard stop was filled")

    monkeypatch.setattr(GreenhouseFiller, "fill", never)
    monkeypatch.setattr(AshbyFiller, "fill", never)


def _dry(ws: Workspace, keys: list[str]) -> list[Any]:
    from getmeajob.apply.runner import run_apply

    return run_apply(
        ws, keys, mode=ApplyMode.dry, headed=False, click_submit=False, hold_timeout=900, limit=None
    )


def test_captcha_variant_stops_and_queues(
    ready_ws: Workspace, use_forms: Callable[..., None], monkeypatch: pytest.MonkeyPatch
) -> None:
    use_forms(ready_ws, greenhouse="captcha=1", ashby="captcha=1")
    _no_filling(monkeypatch)
    entries = _dry(ready_ws, [GH, ASHBY])
    assert [e.status for e in entries] == [ApplyStatus.captcha, ApplyStatus.captcha]
    assert "bot check" in entries[0].detail
    for entry in entries:
        assert (ready_ws.root / (entry.screenshot or "")).is_file()
    items = QueueLog(ready_ws).open_items()
    assert sorted((i.job_key, i.kind) for i in items) == [
        (ASHBY, QueueKind.captcha),
        (GH, QueueKind.captcha),
    ]
    assert all(i.url and "never solves" in i.detail for i in items)

    use_forms(ready_ws)  # even when the check is gone, the job is not tried again
    again = _dry(ready_ws, [GH, ASHBY])
    assert [e.status for e in again] == [ApplyStatus.skipped_duplicate] * 2
    assert len(Ledger(ready_ws).entries()) == 2


def test_account_variant_stops(
    ready_ws: Workspace, use_forms: Callable[..., None], monkeypatch: pytest.MonkeyPatch
) -> None:
    use_forms(ready_ws, greenhouse="account=1")
    _no_filling(monkeypatch)
    (entry,) = _dry(ready_ws, [GH])
    assert entry.status == ApplyStatus.account_required
    assert "Create an account to apply" in entry.detail
    (item,) = QueueLog(ready_ws).open_items()
    assert item.kind == QueueKind.account_required and "never creates accounts" in item.detail


def test_noauto_variant_stops(
    ready_ws: Workspace, use_forms: Callable[..., None], monkeypatch: pytest.MonkeyPatch
) -> None:
    use_forms(ready_ws, greenhouse="noauto=1", ashby="noauto=1")
    _no_filling(monkeypatch)
    entries = _dry(ready_ws, [GH, ASHBY])
    assert [e.status for e in entries] == [ApplyStatus.automation_refused] * 2
    assert "automated tools" in entries[0].detail and "AI agents" in entries[1].detail
    kinds = {i.kind for i in QueueLog(ready_ws).open_items()}
    assert kinds == {QueueKind.automation_refused}


def test_detectors_stay_quiet_on_plain_forms(open_mock: Callable[..., Any]) -> None:
    from getmeajob.apply import guards

    for name in ("greenhouse", "ashby"):
        page = open_mock(name)
        assert guards.detect_captcha(page) is None  # "protected by reCAPTCHA" is not a check
        assert guards.detect_account_wall(page) is None
        assert guards.detect_automation_refusal(page) is None
        assert guards.detect_success(page) is False
        assert guards.detect_email_code(page) is False
        assert guards.collect_errors(page) == []


def test_errors_success_and_code_are_read(open_mock: Callable[..., Any]) -> None:
    from getmeajob.apply import guards

    page = open_mock("greenhouse", "code=1")
    page.click("#submit-app")
    errors = guards.collect_errors(page)
    assert any("First Name is required" in e for e in errors)
    assert any(e.startswith("field marked invalid") for e in errors)
    page = open_mock("ashby")
    page.evaluate("document.getElementById('app').innerHTML = '<h1>Application submitted</h1>'")
    assert guards.detect_success(page)
