"""Turn a role folder's resume into a one-page PDF with Playwright.

Playwright is optional (`pip install -e ".[browser]"` then `playwright install
chromium`) and is imported only when you render. The page is measured in the browser before
printing. If the resume is too long, your shorter wordings are tried first, then the
lowest-scoring bullets are dropped one at a time, keeping at least two per role.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from getmeajob.errors import GetmeajobError
from getmeajob.files import atomic_write_bytes
from getmeajob.resume.doc import DocRole, ResumeDoc, to_html, to_markdown, view
from getmeajob.resume.keywords import term_present
from getmeajob.resume.tailor import selected_ids, write_role_files

MIN_BULLETS_PER_ROLE = 2
PAGE_HEIGHT_PX = 960  # Letter paper (11 in) minus 0.5 in margins top and bottom, at 96 px per inch
MAX_ATTEMPTS = 80
_PAGE_COUNT = re.compile(rb"/Type\s*/Page(?![a-zA-Z])")
_MEASURE = "() => document.querySelector('.page').getBoundingClientRect().height"
_INSTALL_HINT = (
    'Install the browser extra with `pip install -e ".[browser]"` and then run '
    "`playwright install chromium`."
)


def count_pages(pdf: bytes) -> int:
    """How many pages a PDF has, counted from its page objects."""
    return len(_PAGE_COUNT.findall(pdf))


def _next_victim(doc: ResumeDoc, dropped: set[str]) -> str | None:
    """The lowest-scoring bullet that can go: later roles and later bullets go first."""
    best: tuple[float, int, int, str] | None = None
    groups: list[list[DocRole]] = [doc.experience, doc.projects]
    for g, roles in enumerate(groups):
        for r, role in enumerate(roles):
            live = [b for b in role.bullets if b.id not in dropped]
            if len(live) <= MIN_BULLETS_PER_ROLE:
                continue
            for i, bullet in enumerate(role.bullets):
                if bullet.id in dropped:
                    continue
                rank = (bullet.score, -(g * 1000 + r), -i, bullet.id)
                if best is None or rank < best:
                    best = rank
    return best[3] if best else None


def _launch(playwright: Any) -> Any:
    try:
        return playwright.chromium.launch()
    except Exception as exc:  # Playwright raises its own Error type
        raise GetmeajobError(
            f"Could not start the browser to make the PDF: {str(exc).splitlines()[0]}",
            hint=_INSTALL_HINT,
        ) from exc


def _read_doc(role_dir: Path) -> tuple[ResumeDoc | None, dict[str, Any]]:
    path = role_dir / "report.json"
    if not path.is_file():
        return None, {}
    report: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    raw = report.get("doc")
    return (ResumeDoc.from_dict(raw) if isinstance(raw, dict) else None), report


def _settle_report(
    report: dict[str, Any], final: ResumeDoc, dropped: list[str], use_short: bool
) -> dict[str, Any]:
    """Update the report after compaction: what was dropped, and which keywords moved."""
    text = to_markdown(final)
    keywords: list[str] = list(report.get("jd_keywords", []))
    still = [k for k in keywords if term_present(text, k)]
    lost = [k for k in report.get("matched_keywords", []) if k not in still]
    unused = set(report.get("unused_in_bank", [])) | set(lost)
    report = dict(report)
    report["matched_keywords"] = still
    report["unused_in_bank"] = [k for k in keywords if k in unused]
    report["bullets_selected"] = selected_ids(final)
    report["doc"] = final.to_dict()
    report["compaction"] = {"used_short_wording": use_short, "dropped": dropped}
    return report


def render_pdf(role_dir: Path, *, one_page: bool = True) -> Path:
    """Write `resume.pdf` in the role folder and return its path.

    With `one_page=True` the resume is shortened until it fits on one Letter page, or a
    `GetmeajobError` says how to shorten it yourself.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise GetmeajobError(
            "Making a PDF needs Playwright, which is not installed.", hint=_INSTALL_HINT
        ) from exc
    doc, report = _read_doc(role_dir)
    html_path = role_dir / "resume.html"
    if doc is None and not html_path.is_file():
        raise GetmeajobError(
            f"{role_dir} has no resume to render.",
            hint="Run `getmeajob resume tailor KEY` first.",
        )
    dropped: list[str] = []
    use_short = False
    pdf = b""
    with sync_playwright() as pw:
        browser = _launch(pw)
        try:
            page = browser.new_page()
            page.emulate_media(media="print")
            for _ in range(MAX_ATTEMPTS):
                current = view(doc, drop=set(dropped), use_short=use_short) if doc else None
                html = to_html(current) if current else html_path.read_text(encoding="utf-8")
                page.set_content(html)
                over = float(page.evaluate(_MEASURE)) - PAGE_HEIGHT_PX
                pdf = page.pdf(
                    format="Letter",
                    print_background=True,
                    margin={"top": "0.5in", "bottom": "0.5in", "left": "0.5in", "right": "0.5in"},
                )
                if not one_page or (over <= 0 and count_pages(pdf) <= 1):
                    break
                if doc is None:
                    raise GetmeajobError(
                        "The resume does not fit on one page and cannot be shortened "
                        "automatically.",
                        hint="Run `getmeajob resume tailor KEY` again to rebuild this folder.",
                    )
                if not use_short and any(
                    b.short for r in [*doc.experience, *doc.projects] for b in r.bullets
                ):
                    use_short = True
                    continue
                victim = _next_victim(doc, set(dropped))
                if victim is None:
                    raise GetmeajobError(
                        "The resume does not fit on one page, even with only two bullets per role.",
                        hint=(
                            "Add shorter `short:` wordings to your fact bank, remove a role "
                            "or project you do not need, or use --allow-multipage."
                        ),
                    )
                dropped.append(victim)
            else:
                raise GetmeajobError(
                    "Could not fit the resume on one page.",
                    hint="Shorten your fact bank text, or use --allow-multipage.",
                )
        finally:
            browser.close()
    if doc is not None and (dropped or use_short):
        final = view(doc, drop=set(dropped), use_short=use_short)
        write_role_files(role_dir, final, _settle_report(report, final, dropped, use_short))
    out = role_dir / "resume.pdf"
    atomic_write_bytes(out, pdf)
    return out
