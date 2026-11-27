"""Reading a page for the signs that make getmeajob stop or finish.

One script collects what matters (visible text, iframes, password and code inputs,
error messages) and small functions read it: CAPTCHA or bot check, account wall,
"do not use automated tools", success, emailed-code step, validation errors. Bot check
and account wall texts count only inside a visible form, so a job description that
mentions bots does not stop a run; bot check frames and titles, and notices asking
applicants not to use automated tools, count anywhere on the page.

These only read the page. They never click, type or try to get past anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from getmeajob.apply.scripts import page_script
from getmeajob.textutil import refusal_in, sentence_at

if TYPE_CHECKING:
    from playwright.sync_api import Page

_SCAN_JS = page_script("scan")

_CAPTCHA_SRC = re.compile(
    r"recaptcha/(api2|enterprise)/(bframe|anchor)|hcaptcha\.com|challenges\.cloudflare\.com|"
    r"captcha-delivery|arkoselabs|funcaptcha",
    re.I,
)
_CAPTCHA_TEXT = re.compile(
    r"verify (that )?you(?:'re| are) (a )?human|are you a robot|i'?m not a robot|"
    r"(flagged|marked|detected) as (possible |potential |likely )?"
    r"(spam|suspicious|automated|a bot)|"
    r"suspicious activity|unusual traffic|complete the (security )?(check|challenge)|"
    r"checking (if the site connection is secure|your browser)|press (and|&) hold",
    re.I,
)
_ACCOUNT_TEXT = re.compile(
    r"create an account to (apply|continue)|(sign|log) ?in to (apply|continue)|"
    r"you (must|need to) (sign|log) ?in|(sign|log) ?in or create an account|"
    r"create (a|your) candidate account",
    re.I,
)
_SUCCESS_URL = re.compile(r"/confirmation|/thank|application[-_]?submitted", re.I)
_SUCCESS_TEXT = re.compile(
    r"thank(s| you) for (applying|your application)|application (has been |was )?"
    r"(submitted|received)|we(?:'ve| have) received your application|"
    r"has received your application|successfully submitted",
    re.I,
)
_CODE_TEXT = re.compile(
    r"(security|verification|confirmation) code|verify your email|code (was|has been) sent|"
    r"enter the code|check your email for a code",
    re.I,
)


@dataclass(slots=True)
class PageScan:
    url: str = ""
    title: str = ""
    body: str = ""
    form: str = ""
    frames: list[dict[str, Any]] = field(default_factory=list)
    password: bool = False
    otp: bool = False
    errors: list[str] = field(default_factory=list)


def scan_page(page: Page) -> PageScan:
    raw = page.evaluate(_SCAN_JS)
    data = raw if isinstance(raw, dict) else {}
    return PageScan(
        url=str(data.get("url") or ""),
        title=str(data.get("title") or ""),
        body=str(data.get("body") or ""),
        form=str(data.get("form") or ""),
        frames=[f for f in data.get("frames") or [] if isinstance(f, dict)],
        password=bool(data.get("password")),
        otp=bool(data.get("otp")),
        errors=[str(e) for e in data.get("errors") or []],
    )


def captcha_in(scan: PageScan) -> str | None:
    for frame in scan.frames:
        src = str(frame.get("src") or "")
        if not frame.get("visible") or frame.get("badge") or "size=invisible" in src:
            continue
        if _CAPTCHA_SRC.search(src) or re.search(
            r"captcha|challenge", str(frame.get("title")), re.I
        ):
            return "a visible bot check (CAPTCHA) window"
    if scan.title.strip().casefold().startswith("just a moment"):
        return "a browser check page"
    match = _CAPTCHA_TEXT.search(scan.form)
    return f"the page says: {sentence_at(scan.form, match)}" if match else None


def account_wall_in(scan: PageScan) -> str | None:
    match = _ACCOUNT_TEXT.search(scan.form)
    if match:
        return f"the page says: {sentence_at(scan.form, match)}"
    return "a password field" if scan.password else None


def success_in(scan: PageScan) -> bool:
    return bool(_SUCCESS_URL.search(scan.url) or _SUCCESS_TEXT.search(scan.body))


def email_code_in(scan: PageScan) -> bool:
    return scan.otp or bool(_CODE_TEXT.search(scan.body))


def hard_stop(scan: PageScan) -> tuple[str, str] | None:
    """(status, what was seen) for a reason to stop before filling, or None."""
    for status, check in (
        ("captcha", captcha_in),
        ("account_required", account_wall_in),
        ("automation_refused", lambda s: refusal_in(s.body)),
    ):
        seen = check(scan)
        if seen:
            return status, seen
    return None
