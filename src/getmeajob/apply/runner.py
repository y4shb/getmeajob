"""`run_apply`: fill planned forms in one of three modes, one job at a time.

- dry: fill and screenshot. Never clicks Submit.
- hold: a visible window. Fill, click Submit once only with `click_submit`, then wait
  for the human to finish (fix a field, type the emailed code) or close the window.
- submit: only for boards listed in `apply.submit_boards`. Fill, click Submit once,
  then read the result (success, emailed code, bot check, validation errors).

Every job gets a fresh browser context. A closed window or a crashed page is recorded
for that job (closed_by_user in a hold run, else error) and the run goes on. Each
attempt adds one ledger entry; skipped jobs are reported but not written to the ledger.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from getmeajob.apply import policy
from getmeajob.apply.forms import form_target, is_local
from getmeajob.apply.guards import captcha_in, email_code_in, hard_stop, scan_page
from getmeajob.apply.record import Outcome, make_entry, new_run_id, write_attempt
from getmeajob.errors import GetmeajobError
from getmeajob.models import ApplyMode, ApplyStatus, LedgerEntry, Plan
from getmeajob.plan.plans import all_plans, load_plan
from getmeajob.plan.profile import Profile, load_profile
from getmeajob.settings import Settings, load_settings
from getmeajob.store import Ledger, StatusLog, now_iso
from getmeajob.workspace import Workspace, key_to_filename

if TYPE_CHECKING:
    from playwright.sync_api import Page

    from getmeajob.apply.base import Filler, FillReport
    from getmeajob.apply.browser import BrowserSession

FORM_ATS = ("greenhouse", "ashby")
HumanWait = Callable[["Page", float], ApplyStatus]
Notify = Callable[[str], None]


def _check_options(
    mode: ApplyMode,
    headed: bool,
    click_submit: bool,
    hold_timeout: float,
    limit: int | None,
    human: HumanWait | None,
) -> None:
    if mode == ApplyMode.hold and not headed and human is None:
        raise GetmeajobError(
            "A hold run needs a visible browser window, so you can finish the form yourself.",
            hint="Add --headed: getmeajob apply --mode hold --headed",
        )
    if click_submit and mode != ApplyMode.hold:
        raise GetmeajobError(
            "--click-submit only works with --mode hold.",
            hint="A submit run always clicks Submit once by itself; a dry run never does.",
        )
    if hold_timeout <= 0:
        raise GetmeajobError(
            "--hold-timeout must be more than 0 seconds.", hint="The default is 900."
        )
    if limit is not None and limit < 1:
        raise GetmeajobError("--limit must be 1 or more.", hint="Leave it out to try every job.")


def _no_plan(key: str, mode: ApplyMode, run_id: str) -> LedgerEntry:
    return LedgerEntry(
        ts=now_iso(),
        run_id=run_id,
        job_key=key,
        company="",
        title="",
        mode=mode,
        status=ApplyStatus.skipped_not_ready,
        detail=f"no plan yet; run: getmeajob plan {key}",
    )


def _select(
    ws: Workspace, keys: Sequence[str] | None, mode: ApplyMode, run_id: str
) -> tuple[list[Plan], list[LedgerEntry]]:
    if keys is None:
        return [p for p in all_plans(ws) if p.ats in FORM_ATS], []
    plans: list[Plan] = []
    missing: list[LedgerEntry] = []
    for key in dict.fromkeys(keys):
        plan = load_plan(ws, key)
        if plan is None:
            missing.append(_no_plan(key, mode, run_id))
        else:
            plans.append(plan)
    return plans, missing


class _Attempt:
    """Runs one job at a time in a shared browser, each in its own context."""

    def __init__(
        self,
        ws: Workspace,
        settings: Settings,
        profile: Profile,
        mode: ApplyMode,
        *,
        headed: bool,
        click_submit: bool,
        hold_timeout: float,
        human: HumanWait | None,
        notify: Notify,
    ) -> None:
        self.ws, self.settings, self.profile, self.mode = ws, settings, profile, mode
        self.headed, self.click_submit, self.hold_timeout = headed, click_submit, hold_timeout
        self.human = human
        self.notify = notify
        self.session: BrowserSession | None = None
        self.partial = Outcome(ApplyStatus.error)
        self.clicked = False

    def _session(self) -> BrowserSession:
        if self.session is None:
            from getmeajob.apply.browser import BrowserSession

            local = self.settings.fixtures is not None or self.settings.offline
            self.session = BrowserSession(headed=self.headed, local_only=local)
        return self.session

    def close(self) -> None:
        if self.session is not None:
            self.session.close()

    def _shot(self, page: Page, plan: Plan, status: ApplyStatus) -> Path | None:
        from getmeajob.apply.browser import screenshot

        name = f"{self.mode.value}-{key_to_filename(plan.job_key)}-{status.value}.png"
        return screenshot(page, self.ws.shots_dir / name)

    def _outcome(
        self,
        page: Page,
        plan: Plan,
        status: ApplyStatus,
        detail: str,
        problems: list[str] | None = None,
    ) -> Outcome:
        return Outcome(status, detail, list(problems or []), self._shot(page, plan, status))

    def run(self, plan: Plan) -> tuple[Outcome, bool]:
        """(outcome, whether a fill_problem queue item should be added next to it)."""
        from getmeajob.apply.base import filler_for
        from getmeajob.apply.browser import playwright_error

        error_cls = playwright_error()  # a missing Playwright stops the run with a hint
        try:
            target = form_target(plan.form_url, self.settings)
            filler = filler_for(plan.ats, fast=is_local(target))
        except GetmeajobError as exc:
            return Outcome(ApplyStatus.error, exc.message), False
        session = self._session()
        self.partial = Outcome(ApplyStatus.error)
        self.clicked = False
        context = page = None
        try:
            context, page = session.new_page()
            return self._steps(page, plan, filler, target)
        except error_cls as exc:
            return self._after_click(self._broken(page, exc)), self.mode == ApplyMode.hold
        except GetmeajobError as exc:
            failed = replace(self.partial, status=ApplyStatus.error, detail=exc.message)
            return self._after_click(failed), False
        except Exception as exc:  # one broken job never ends the run
            detail = f"{type(exc).__name__}: {str(exc).strip()[:150]}"
            failed = replace(self.partial, status=ApplyStatus.error, detail=detail)
            return self._after_click(failed), False
        finally:
            session.close_context(context)

    def _after_click(self, outcome: Outcome) -> Outcome:
        """An error after the Submit click may hide a sent application: record it as
        awaiting_human, so no later run clicks Submit again before the human checks."""
        if not self.clicked or outcome.status != ApplyStatus.error:
            return outcome
        detail = f"Submit was clicked once, then: {outcome.detail}"
        return replace(outcome, status=ApplyStatus.awaiting_human, detail=detail)

    def _broken(self, page: Page | None, exc: Exception) -> Outcome:
        from getmeajob.apply.browser import page_alive

        if not page_alive(page) and self.mode == ApplyMode.hold:
            detail = "the window was closed before the application was finished"
            return replace(self.partial, status=ApplyStatus.closed_by_user, detail=detail)
        text = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        if not page_alive(page):
            text = f"the browser window closed or crashed ({text[:100]})"
        return replace(self.partial, status=ApplyStatus.error, detail=text[:200])

    def _wait_ready(self, page: Page, plan: Plan, filler: Filler, fast: bool) -> Outcome | None:
        deadline = time.monotonic() + (8.0 if fast else 25.0)
        while True:
            try:
                scan = scan_page(page)
            except Exception:
                if page.is_closed():
                    raise
                scan = None
            stop = hard_stop(scan) if scan is not None else None
            if stop is not None:
                status, seen = stop
                return self._outcome(page, plan, ApplyStatus(status), seen)
            if page.locator(filler.ready_selector).count():
                return None
            if time.monotonic() >= deadline:
                return self._outcome(
                    page,
                    plan,
                    ApplyStatus.error,
                    "the form did not load (its first field never appeared)",
                )
            page.wait_for_timeout(250)

    def _steps(self, page: Page, plan: Plan, filler: Filler, target: str) -> tuple[Outcome, bool]:
        page.goto(target, wait_until="domcontentloaded", timeout=45_000)
        stop = self._wait_ready(page, plan, filler, is_local(target))
        if stop is not None:
            return stop, False
        notes = filler.prepare(page)
        report = filler.fill(page, plan, self.profile, self.ws)
        self.partial.problems = list(report.problems)
        seen = captcha_in(scan_page(page))
        if seen:
            return self._outcome(page, plan, ApplyStatus.captcha, seen, report.problems), False
        filled = f"filled {report.filled} field(s)" + (f"; {notes[0]}" if notes else "")
        if self.mode == ApplyMode.dry:
            status = ApplyStatus.fill_problem if report.problems else ApplyStatus.dry_ok
            return self._outcome(page, plan, status, filled, report.problems), False
        if self.mode == ApplyMode.submit:
            if report.problems:
                why = f"{filled}; Submit was not clicked"
                return self._outcome(
                    page, plan, ApplyStatus.fill_problem, why, report.problems
                ), False
            from getmeajob.apply.watch import watch_after_submit

            before = scan_page(page)
            self.clicked = True
            filler.submit(page)  # the one and only click
            status, detail = watch_after_submit(page, before)
            return self._outcome(page, plan, status, detail), False
        return self._hold(page, plan, filler, report, filled), True

    def _hold(
        self, page: Page, plan: Plan, filler: Filler, report: FillReport, filled: str
    ) -> Outcome:
        from getmeajob.apply.watch import wait_for_human

        reasons: list[str] = []
        if report.problems:
            reasons.append(
                f"{len(report.problems)} field(s) need you: " + "; ".join(report.problems[:3])
            )
        if any(a.needs_review for a in plan.answers):
            reasons.append("some answers are drafts you have not reviewed")
        prefill = self._shot(page, plan, ApplyStatus.awaiting_human)
        self.partial.screenshot = prefill
        clicked = False
        if self.click_submit and not reasons:
            self.clicked = clicked = True
            filler.submit(page)  # the one and only click
        lines = [f"{plan.job_key}: {filled}."]
        if clicked:
            lines.append(
                "getmeajob clicked Submit once. If the board emails you a code, type it in "
                "the window."
            )
        elif self.click_submit:
            lines.append("getmeajob did not click Submit: " + "; ".join(reasons) + ".")
        lines.append(
            "Your turn in the browser window: check the answers, click Submit, type any emailed "
            f"code. Waiting up to {self.hold_timeout:g} s; closing the window skips this job."
        )
        self.notify(" ".join(lines))
        status = (self.human or wait_for_human)(page, self.hold_timeout)
        detail = {
            ApplyStatus.submitted: "you finished it in the window",
            ApplyStatus.closed_by_user: "the window was closed before the application was finished",
            ApplyStatus.timeout: f"no confirmation within {self.hold_timeout:g} s",
            ApplyStatus.error: "the page crashed or stopped responding",
        }.get(status, status.value)
        if status in (ApplyStatus.captcha, ApplyStatus.timeout) and not page.is_closed():
            scan = scan_page(page)
            if status == ApplyStatus.captcha:
                detail = captcha_in(scan) or "a bot check appeared"
            elif email_code_in(scan):
                status, detail = (
                    ApplyStatus.needs_email_code,
                    "the emailed-code step was still open",
                )
        if clicked:
            detail += " (getmeajob clicked Submit once)"
        shot = self._shot(page, plan, status) if not page.is_closed() else None
        return Outcome(status, detail, list(report.problems), shot or prefill)


def run_apply(
    ws: Workspace,
    keys: Sequence[str] | None,
    *,
    mode: ApplyMode,
    headed: bool,
    click_submit: bool,
    hold_timeout: float,
    limit: int | None,
    wait_for_human: HumanWait | None = None,
    notify: Notify | None = None,
) -> list[LedgerEntry]:
    """Apply to planned jobs (all stored plans for Greenhouse and Ashby when `keys` is
    None). Returns one entry per job looked at; attempts are also written to the ledger.

    `wait_for_human(page, timeout)` replaces the human in a hold run (tests, embedding);
    with it, a hold run may run headless. `notify` receives the hold-run instructions.
    """
    ws = ws.require()
    mode = ApplyMode(mode)
    _check_options(mode, headed, click_submit, hold_timeout, limit, wait_for_human)
    settings = load_settings(ws)
    prefs = policy.load_apply_prefs(ws)
    run_id = new_run_id()
    plans, results = _select(ws, keys, mode, run_id)
    if mode == ApplyMode.submit:
        policy.require_opt_in(plans, prefs)
    history = Ledger(ws).entries()
    tracker = StatusLog(ws)
    offline = settings.fixtures is not None or settings.offline
    attempt: _Attempt | None = None
    attempted = 0
    try:
        for plan in plans:
            skip = policy.skip_reason(plan, mode, prefs, history, tracker)
            if skip is not None:
                results.append(make_entry(ws, plan, mode, Outcome(*skip), run_id))
                continue
            if limit is not None and attempted >= limit:
                break
            if attempt is None:
                attempt = _Attempt(
                    ws,
                    settings,
                    load_profile(ws),
                    mode,
                    headed=headed,
                    click_submit=click_submit,
                    hold_timeout=hold_timeout,
                    human=wait_for_human,
                    notify=notify or (lambda _: None),
                )
            elif not offline:
                time.sleep(random.uniform(4.0, 8.0))  # a pause between real jobs
            attempted += 1
            outcome, flag = attempt.run(plan)
            entry = make_entry(ws, plan, mode, outcome, run_id)
            write_attempt(ws, entry, extra_problems=flag)
            history.append(entry)
            results.append(entry)
    finally:
        if attempt is not None:
            attempt.close()
    return results
