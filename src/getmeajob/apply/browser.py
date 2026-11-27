"""Starting Chromium with Playwright, one fresh context per job, and recovering from a
closed window or a crashed browser.

Playwright is optional (`pip install -e ".[browser]"`), so it is imported only
when a browser is really needed, with a plain-language hint when it is missing.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from getmeajob.errors import GetmeajobError

if TYPE_CHECKING:
    from playwright.sync_api import Browser, BrowserContext, Page, Playwright, Route, ViewportSize

INSTALL_HINT = 'Install it with: pip install -e ".[browser]"  then: playwright install chromium'
VIEWPORT: ViewportSize = {"width": 1280, "height": 900}


def require_playwright() -> Any:
    """The `playwright.sync_api` module, or a friendly error when it is not installed."""
    try:
        import playwright.sync_api as api
    except ImportError as exc:
        raise GetmeajobError(
            "Filling forms needs Playwright, which is not installed.", hint=INSTALL_HINT
        ) from exc
    return api


def playwright_error() -> type[Exception]:
    """Playwright's base error class (so callers can catch it without importing it)."""
    api = require_playwright()
    error: type[Exception] = api.Error
    return error


def _launch_error(exc: Exception) -> GetmeajobError:
    text = str(exc)
    if "Executable doesn't exist" in text or "playwright install" in text:
        return GetmeajobError(
            "Playwright is installed but its Chromium browser is not.",
            hint="Run: playwright install chromium",
        )
    if "XServer" in text or "headed browser" in text or "DISPLAY" in text:
        return GetmeajobError(
            "Could not open a browser window on this machine.",
            hint="Hold runs need a screen. Use --mode dry, or run on a desktop session.",
        )
    return GetmeajobError(f"Could not start Chromium: {text.splitlines()[0] if text else exc}")


class BrowserSession:
    """One Chromium for a run. `new_page()` gives each job its own fresh context.

    If the browser went away (the human quit it, or it crashed), the next `new_page()`
    starts a new one, so one closed window never ends the whole run.
    Offline (`local_only=True`) every request that is not a local file is blocked.
    """

    def __init__(self, *, headed: bool, local_only: bool = False) -> None:
        self.headed = headed
        self.local_only = local_only
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self.relaunches = 0

    def __enter__(self) -> BrowserSession:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _start(self) -> Browser:
        api = require_playwright()
        if self._pw is None:
            self._pw = api.sync_playwright().start()
        assert self._pw is not None
        try:
            browser = self._pw.chromium.launch(headless=not self.headed)
        except api.Error as exc:
            raise _launch_error(exc) from exc
        self._browser = browser
        return browser

    def browser(self) -> Browser:
        if self._browser is not None and self._browser.is_connected():
            return self._browser
        if self._browser is not None:
            self.relaunches += 1
            with contextlib.suppress(Exception):
                self._browser.close()
        return self._start()

    def new_page(self) -> tuple[BrowserContext, Page]:
        """A page in a new, empty context (no cookies from earlier jobs)."""
        api = require_playwright()
        try:
            context = self.browser().new_context(viewport=VIEWPORT, accept_downloads=False)
        except api.Error:
            self._browser = None  # the browser died between jobs: start a new one
            context = self.browser().new_context(viewport=VIEWPORT, accept_downloads=False)
        if self.local_only:
            context.route("**/*", _local_only)
        page = context.new_page()
        page.set_default_timeout(10_000)
        return context, page

    def close_context(self, context: BrowserContext | None) -> None:
        if context is not None:
            with contextlib.suppress(Exception):
                context.close()

    def close(self) -> None:
        if self._browser is not None:
            with contextlib.suppress(Exception):
                self._browser.close()
            self._browser = None
        if self._pw is not None:
            with contextlib.suppress(Exception):
                self._pw.stop()
            self._pw = None


def _local_only(route: Route) -> None:
    url = route.request.url
    if url.startswith(("file:", "data:", "about:", "blob:")):
        route.continue_()
    else:
        route.abort()


def screenshot(page: Page, path: Path) -> Path | None:
    """Save a full-page screenshot. Returns the path, or None when the page is gone."""
    try:
        if page.is_closed():
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(path), full_page=True, timeout=15_000)
        return path
    except Exception:
        return None


def page_alive(page: Page | None) -> bool:
    if page is None:
        return False
    try:
        return (
            not page.is_closed()
            and page.context.browser is not None
            and page.context.browser.is_connected()
        )
    except Exception:
        return False
