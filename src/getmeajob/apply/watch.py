"""Watching a page after Submit: in a hold run (the human finishes) and in a submit run.

Both only read the page. Neither clicks anything, so Submit is never pressed twice.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from getmeajob.apply.guards import (
    PageScan,
    captcha_in,
    email_code_in,
    scan_page,
    success_in,
)
from getmeajob.models import ApplyStatus

if TYPE_CHECKING:
    from playwright.sync_api import Page

HOLD_POLL = 1.0
SUBMIT_POLL = 0.5
SUBMIT_WATCH = 30.0
ERROR_GRACE = 1.5


def _scan(page: Page) -> PageScan | None:
    """A scan, or None while the page is between two documents (navigation)."""
    try:
        return scan_page(page)
    except Exception:
        if page.is_closed():
            raise
        return None


def _gone(page: Page) -> bool:
    try:
        return (
            page.is_closed() or not page.context.browser or not page.context.browser.is_connected()
        )
    except Exception:
        return True


def _ended(page: Page, exc: Exception) -> ApplyStatus:
    """A closed window is the human's choice; a crashed page is an error."""
    if "crash" in str(exc).casefold() and not page.is_closed():
        return ApplyStatus.error
    return ApplyStatus.closed_by_user


def wait_for_human(page: Page, timeout: float) -> ApplyStatus:
    """Wait while the human finishes in the window: check the form, click Submit, type the
    emailed code. Ends with submitted, captcha, closed_by_user, timeout, or error when
    the page crashed."""
    deadline = time.monotonic() + timeout
    while True:
        if _gone(page):
            return ApplyStatus.closed_by_user
        try:
            scan = _scan(page)
        except Exception as exc:
            return _ended(page, exc)
        if scan is not None:
            if success_in(scan):
                return ApplyStatus.submitted
            if captcha_in(scan):
                return ApplyStatus.captcha
        if time.monotonic() >= deadline:
            return ApplyStatus.timeout
        try:
            page.wait_for_timeout(HOLD_POLL * 1000)
        except Exception as exc:
            return _ended(page, exc)


def watch_after_submit(
    page: Page, before: PageScan, timeout: float = SUBMIT_WATCH
) -> tuple[ApplyStatus, str]:
    """After the one Submit click: success, the emailed-code step, a bot check, or
    validation errors. `before` is the page as it was just before the click, so text
    that was already there (an error, a mention of codes) does not count. Errors count
    only when still there after a short grace period. Nothing conclusive within
    `timeout` gives awaiting_human."""
    start = time.monotonic()
    old_errors = set(before.errors)
    code_text_before = email_code_in(PageScan(body=before.body))
    success_before = success_in(before)
    while True:
        if _gone(page):
            return ApplyStatus.error, "the page closed right after Submit"
        scan = _scan(page)
        if scan is not None:
            if success_in(scan) and (not success_before or scan.url != before.url):
                return ApplyStatus.submitted, "the form showed its confirmation"
            if scan.otp or (email_code_in(scan) and not code_text_before):
                return ApplyStatus.needs_email_code, "the form asks for a code sent to your email"
            seen = captcha_in(scan)
            if seen:
                return ApplyStatus.captcha, seen
            errors = [e for e in scan.errors if e not in old_errors]
            if errors and time.monotonic() - start >= ERROR_GRACE:
                return ApplyStatus.validation_error, "; ".join(errors[:6])
        if time.monotonic() - start >= timeout:
            return (
                ApplyStatus.awaiting_human,
                f"clicked Submit once; no confirmation, error or code step within {timeout:g} s",
            )
        page.wait_for_timeout(SUBMIT_POLL * 1000)
