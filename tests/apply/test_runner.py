"""`run_apply`: guards, modes, the hold handoff and crash isolation."""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable
from typing import Any

import pytest

from getmeajob.apply.runner import run_apply
from getmeajob.errors import GetmeajobError
from getmeajob.models import ApplyMode, ApplyStatus, AppStatus, LedgerEntry, QueueKind
from getmeajob.store import Ledger, QueueLog, StatusLog, now_iso
from getmeajob.workspace import Workspace

GH = "greenhouse:examplecorp:1001"
ASHBY = "ashby:samplesystems:5a1e0000-0000-4000-8000-000000000001"
browser = pytest.mark.browser


def _run(ws: Workspace, keys: list[str] | None, mode: ApplyMode, **kw: Any) -> list[LedgerEntry]:
    options: dict[str, Any] = {
        "headed": False,
        "click_submit": False,
        "hold_timeout": 30,
        "limit": None,
    }
    options.update(kw)
    return run_apply(ws, keys, mode=mode, **options)


def _count_submits(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    from getmeajob.apply.ashby import AshbyFiller
    from getmeajob.apply.greenhouse import GreenhouseFiller

    clicks: dict[str, int] = {}
    for cls in (GreenhouseFiller, AshbyFiller):
        real = cls.submit

        def counted(self: Any, page: Any, real: Any = real) -> None:
            clicks[self.ats] = clicks.get(self.ats, 0) + 1
            real(self, page)

        monkeypatch.setattr(cls, "submit", counted)
    return clicks


# ------------------------------------------------------------- no browser needed


def test_submit_refused_without_opt_in(ready_ws: Workspace) -> None:
    with pytest.raises(GetmeajobError, match="submit_boards") as err:
        _run(ready_ws, None, ApplyMode.submit)
    assert err.value.hint and "preferences.yaml" in err.value.hint
    assert not ready_ws.ledger_path.exists()


def test_submit_refused_with_unreviewed_draft(
    ready_ws: Workspace, set_apply: Callable[..., None]
) -> None:
    set_apply(ready_ws, submit_boards=["greenhouse"])
    path = ready_ws.plan_path(GH)
    data = json.loads(path.read_text(encoding="utf-8"))
    for answer in data["answers"]:
        if answer["question_id"] == "question_2005":
            answer.update(source="draft", needs_review=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    (entry,) = _run(ready_ws, [GH], ApplyMode.submit)
    assert entry.status == ApplyStatus.skipped_not_ready
    assert f"plan approve {GH}" in entry.detail
    assert not ready_ws.ledger_path.exists()  # a skip is not an attempt


def test_hold_needs_a_window_and_click_submit_needs_hold(ready_ws: Workspace) -> None:
    with pytest.raises(GetmeajobError, match="visible browser window"):
        _run(ready_ws, None, ApplyMode.hold)
    with pytest.raises(GetmeajobError, match="--click-submit"):
        _run(ready_ws, None, ApplyMode.dry, click_submit=True)


def test_exclusion_list(ready_ws: Workspace, set_apply: Callable[..., None]) -> None:
    set_apply(ready_ws, exclude=["examplecorp", "sample sys"])
    entries = _run(ready_ws, None, ApplyMode.dry)
    assert {(e.job_key, e.status) for e in entries} == {
        (GH, ApplyStatus.skipped_excluded),
        (ASHBY, ApplyStatus.skipped_excluded),
    }
    assert not ready_ws.ledger_path.exists()


def test_per_company_cap(ready_ws: Workspace, set_apply: Callable[..., None]) -> None:
    set_apply(ready_ws, submit_boards=["greenhouse"], per_company_cap=2)
    ledger = Ledger(ready_ws)
    for key in ("greenhouse:examplecorp:1002", "greenhouse:examplecorp:1003"):
        ledger.append(
            LedgerEntry(
                now_iso(), "old", key, "Example Corp", "t", ApplyMode.submit, ApplyStatus.submitted
            )
        )
    (entry,) = _run(ready_ws, [GH], ApplyMode.submit)
    assert entry.status == ApplyStatus.skipped_cap
    assert "cap 2" in entry.detail


def test_missing_plan_is_reported(ready_ws: Workspace) -> None:
    (entry,) = _run(
        ready_ws, ["lever:demowidgets:7c0de000-0000-4000-8000-000000000001"], ApplyMode.dry
    )
    assert entry.status == ApplyStatus.skipped_not_ready and "getmeajob plan" in entry.detail


# ------------------------------------------------------------------- browser


@browser
def test_idempotent_second_run_skips(
    ready_ws: Workspace, set_apply: Callable[..., None], monkeypatch: pytest.MonkeyPatch
) -> None:
    set_apply(ready_ws, submit_boards=["greenhouse", "ashby"])
    clicks = _count_submits(monkeypatch)
    first = _run(ready_ws, [GH, ASHBY], ApplyMode.submit)
    assert [e.status for e in first] == [ApplyStatus.submitted] * 2, [e.detail for e in first]
    assert clicks == {"greenhouse": 1, "ashby": 1}
    assert StatusLog(ready_ws).current(GH) == AppStatus.applied
    for mode in (ApplyMode.submit, ApplyMode.dry):
        again = _run(ready_ws, [GH, ASHBY], mode)
        assert [e.status for e in again] == [ApplyStatus.skipped_duplicate] * 2
    assert clicks == {"greenhouse": 1, "ashby": 1}
    assert len(Ledger(ready_ws).entries()) == 2


@browser
def test_dry_runs_do_not_block_later_runs(ready_ws: Workspace) -> None:
    first = _run(ready_ws, [ASHBY], ApplyMode.dry)
    second = _run(ready_ws, [ASHBY], ApplyMode.dry)
    assert [e.status for e in first + second] == [ApplyStatus.dry_ok] * 2


@browser
def test_submit_results_code_spam_and_fill_problem(
    ready_ws: Workspace,
    set_apply: Callable[..., None],
    use_forms: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_apply(ready_ws, submit_boards=["greenhouse", "ashby"])
    use_forms(ready_ws, greenhouse="code=1", ashby="spam=1")
    clicks = _count_submits(monkeypatch)
    code, spam = _run(ready_ws, [GH, ASHBY], ApplyMode.submit)
    assert code.status == ApplyStatus.needs_email_code
    assert spam.status == ApplyStatus.captcha and "spam" in spam.detail
    assert clicks == {"greenhouse": 1, "ashby": 1}
    kinds = {(i.job_key, i.kind) for i in QueueLog(ready_ws).open_items()}
    assert kinds == {(GH, QueueKind.needs_email_code), (ASHBY, QueueKind.captcha)}
    later = _run(ready_ws, [GH], ApplyMode.dry)
    assert later[0].status == ApplyStatus.skipped_duplicate and "hold" in later[0].detail

    use_forms(ready_ws)
    path = ready_ws.plan_path(GH)
    data = json.loads(path.read_text(encoding="utf-8"))
    for answer in data["answers"]:
        if answer["question_id"] == "question_2004":
            answer["value"] = "Fifteen"
    path.write_text(json.dumps(data), encoding="utf-8")
    Ledger(ready_ws).path.unlink()
    (problem,) = _run(ready_ws, [GH], ApplyMode.submit)
    assert problem.status == ApplyStatus.fill_problem and "not clicked" in problem.detail
    assert any(p.startswith("question_2004") for p in problem.problems)
    assert clicks == {"greenhouse": 1, "ashby": 1}  # never submitted with a problem


@browser
def test_hold_code_flow_with_injected_human(
    ready_ws: Workspace, use_forms: Callable[..., None], monkeypatch: pytest.MonkeyPatch
) -> None:
    from getmeajob.apply.guards import detect_email_code
    from getmeajob.apply.watch import wait_for_human

    use_forms(ready_ws, greenhouse="code=1")
    clicks = _count_submits(monkeypatch)
    seen: list[str] = []

    def human(page: Any, timeout: float) -> ApplyStatus:
        assert detect_email_code(page)  # getmeajob clicked Submit once; the code step is up
        page.fill("input[autocomplete=one-time-code]", "ABCD1234")
        page.click("#verify-code")
        return wait_for_human(page, timeout)

    (entry,) = _run(
        ready_ws, [GH], ApplyMode.hold, click_submit=True, wait_for_human=human, notify=seen.append
    )
    assert entry.status == ApplyStatus.submitted, entry.detail
    assert "clicked Submit once" in entry.detail and clicks == {"greenhouse": 1}
    assert any("Your turn" in line for line in seen)
    assert StatusLog(ready_ws).current(GH) == AppStatus.applied
    assert not QueueLog(ready_ws).open_items()
    assert (ready_ws.shots_dir / "hold-greenhouse__examplecorp__1001-submitted.png").is_file()


@browser
def test_window_closed_continues_next_job(ready_ws: Workspace) -> None:
    from getmeajob.apply.watch import wait_for_human

    def human(page: Any, timeout: float) -> ApplyStatus:
        if "greenhouse" in page.url:
            page.context.browser.close()  # the human quits the whole browser mid-hold
            return wait_for_human(page, timeout)
        page.get_by_role("button", name="Submit Application").click()
        return wait_for_human(page, timeout)

    entries = _run(ready_ws, [GH, ASHBY], ApplyMode.hold, wait_for_human=human)
    assert [e.status for e in entries] == [ApplyStatus.closed_by_user, ApplyStatus.submitted]
    assert entries[0].screenshot  # the shot taken before the handoff is kept
    assert [e.status for e in Ledger(ready_ws).entries()] == [
        ApplyStatus.closed_by_user,
        ApplyStatus.submitted,
    ]


@browser
def test_page_crash_is_an_error_and_the_run_goes_on(ready_ws: Workspace) -> None:
    from getmeajob.apply.watch import wait_for_human

    def human(page: Any, timeout: float) -> ApplyStatus:
        if "greenhouse" in page.url:
            with contextlib.suppress(Exception):
                page.goto("chrome://crash")  # a real renderer crash, not a closed window
            return wait_for_human(page, timeout)
        if "ashby" in page.url:
            raise RuntimeError("an unexpected bug in this job")
        return wait_for_human(page, 1)

    entries = _run(ready_ws, [GH, ASHBY], ApplyMode.hold, wait_for_human=human)
    assert [e.status for e in entries] == [ApplyStatus.error, ApplyStatus.error]
    assert "crashed" in entries[0].detail and "RuntimeError" in entries[1].detail
    again = _run(ready_ws, [ASHBY], ApplyMode.dry)  # errors never block a later run
    assert again[0].status == ApplyStatus.dry_ok


@browser
def test_limit_counts_only_attempted_jobs(
    ready_ws: Workspace, set_apply: Callable[..., None]
) -> None:
    set_apply(ready_ws, exclude=["sample systems"])
    entries = _run(ready_ws, None, ApplyMode.dry, limit=1)
    assert sorted(e.status.value for e in entries) == ["dry_ok", "skipped_excluded"]


@browser
def test_error_after_the_click_never_clicks_again(
    ready_ws: Workspace, set_apply: Callable[..., None], monkeypatch: pytest.MonkeyPatch
) -> None:
    from playwright.sync_api import Error

    from getmeajob.apply.ashby import AshbyFiller

    set_apply(ready_ws, submit_boards=["ashby"])
    real = AshbyFiller.submit
    clicks: list[int] = []

    def click_then_fail(self: AshbyFiller, page: Any) -> None:
        clicks.append(1)
        real(self, page)
        raise Error("Timeout 10000ms exceeded while waiting for the page")

    monkeypatch.setattr(AshbyFiller, "submit", click_then_fail)
    (entry,) = _run(ready_ws, [ASHBY], ApplyMode.submit)
    assert entry.status == ApplyStatus.awaiting_human
    assert entry.detail.startswith("Submit was clicked once")
    assert [i.kind for i in QueueLog(ready_ws).open_items()] == [QueueKind.manual]
    (again,) = _run(ready_ws, [ASHBY], ApplyMode.submit)
    assert again.status == ApplyStatus.skipped_duplicate and clicks == [1]
