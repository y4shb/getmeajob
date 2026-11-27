"""Reading a page for the signs that make getmeajob stop or finish.

One script collects what matters (visible text, iframes, password and code inputs,
error messages) and small functions read it: CAPTCHA or bot check, account wall,
"do not use automated tools", success, emailed-code step, validation errors.

These only read the page. They never click, type or try to get past anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from getmeajob.apply.scripts import page_script

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
_STOP = r"(do not|don'?t|must not|may not|should not|cannot|can'?t|never|refrain from|"
_STOP += r"not (?:allowed|permitted) to|(?:is|are) prohibited from|please avoid)"
_BOTS = r"(automated|automation|bots?|scripts?|ai agents?|ai tools?|ai assistants?|autofill|"
_BOTS += r"auto-fill|crawlers?|scrapers?)"
_REFUSAL = (
    re.compile(rf"\b{_STOP}\b[^.!?\n]{{0,60}}\b{_BOTS}\b", re.I),
    re.compile(
        rf"\b{_BOTS}\b[^.!?\n]{{0,80}}\b(will be|are|is) (rejected|disqualified|discarded|"
        r"not (accepted|considered|allowed|permitted)|prohibited)",
        re.I,
    ),
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
        frames=[f for f in data.get("frames") or [] if isinstance(f, dict)],
        password=bool(data.get("password")),
        otp=bool(data.get("otp")),
        errors=[str(e) for e in data.get("errors") or []],
    )


def _sentence(text: str, match: re.Match[str]) -> str:
    start = max(text.rfind(".", 0, match.start()), text.rfind("\n", 0, match.start())) + 1
    stops = [i for i in (text.find(".", match.end()), text.find("\n", match.end())) if i != -1]
    end = min(stops) + 1 if stops else len(text)
    return " ".join(text[start:end].split())[:200]


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
    match = _CAPTCHA_TEXT.search(scan.body)
    return f"the page says: {_sentence(scan.body, match)}" if match else None


def account_wall_in(scan: PageScan) -> str | None:
    match = _ACCOUNT_TEXT.search(scan.body)
    if match:
        return f"the page says: {_sentence(scan.body, match)}"
    return "a password field" if scan.password else None


def refusal_in(text: str) -> str | None:
    for pattern in _REFUSAL:
        match = pattern.search(text)
        if match:
            return _sentence(text, match)
    return None


def success_in(scan: PageScan) -> bool:
    return bool(_SUCCESS_URL.search(scan.url) or _SUCCESS_TEXT.search(scan.body))


def email_code_in(scan: PageScan) -> bool:
    return scan.otp or bool(_CODE_TEXT.search(scan.body))


def detect_captcha(page: Page) -> str | None:
    """What bot check is showing (a visible CAPTCHA window, a browser check, a spam flag)."""
    return captcha_in(scan_page(page))


def detect_account_wall(page: Page) -> str | None:
    """Why the form looks like it needs an account, or None."""
    return account_wall_in(scan_page(page))


def detect_automation_refusal(page: Page) -> str | None:
    """The sentence asking people not to use automated tools or AI agents, or None."""
    return refusal_in(scan_page(page).body)


def detect_success(page: Page) -> bool:
    return success_in(scan_page(page))


def detect_email_code(page: Page) -> bool:
    return email_code_in(scan_page(page))


def collect_errors(page: Page) -> list[str]:
    """Visible validation messages and fields marked invalid (at most 12)."""
    return scan_page(page).errors


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
