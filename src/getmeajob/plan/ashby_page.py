"""Fallback for Ashby: read the questions from the rendered application page in Chromium.

Used only when Ashby's own form request fails, Playwright is installed, and getmeajob
is online. It only reads the page (no clicks, no typing). Playwright is imported
lazily so the rest of getmeajob works without it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from getmeajob.errors import GetmeajobError
from getmeajob.http import USER_AGENT
from getmeajob.models import Option, Question, QuestionType
from getmeajob.textutil import short_hash, strip_invisible

# Collects form controls with their label, kind, required flag and options.
_COLLECT_JS = r"""
() => {
  const text = (el) =>
    (el ? (el.innerText || el.textContent || '') : '').replace(/\s+/g, ' ').trim();
  const labelOf = (el) => {
    if (el.id) {
      const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (l) return text(l);
    }
    const by = el.getAttribute('aria-labelledby');
    if (by) {
      const t = by.split(/\s+/).map((id) => text(document.getElementById(id))).join(' ').trim();
      if (t) return t;
    }
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
    const fs = el.closest('fieldset');
    if (fs && fs.querySelector('legend')) return text(fs.querySelector('legend'));
    let node = el.parentElement;
    for (let i = 0; node && i < 5; i += 1, node = node.parentElement) {
      const l = node.querySelector('label');
      if (l && !l.contains(el)) return text(l);
    }
    return el.getAttribute('placeholder') || el.name || '';
  };
  const out = [];
  const groups = new Map();
  for (const el of document.querySelectorAll('input, textarea, select, [role="combobox"]')) {
    const tag = el.tagName.toLowerCase();
    let kind = tag === 'input' ? (el.getAttribute('type') || 'text').toLowerCase() : tag;
    if (el.getAttribute('role') === 'combobox' && tag !== 'select') kind = 'combobox';
    if (['hidden', 'submit', 'button', 'reset', 'image', 'search'].includes(kind)) continue;
    const required = el.required || el.getAttribute('aria-required') === 'true';
    if (kind === 'radio' || kind === 'checkbox') {
      const key = el.name || el.id;
      const own = el.id ? document.querySelector('label[for="' + CSS.escape(el.id) + '"]') : null;
      const optionLabel = text(own || el.closest('label')) || el.value;
      if (!groups.has(key)) {
        const fs = el.closest('fieldset');
        const legend = fs && fs.querySelector('legend') ? text(fs.querySelector('legend')) : '';
        const entry = { id: key, label: legend, kind, required, options: [] };
        groups.set(key, entry);
        out.push(entry);
      }
      const g = groups.get(key);
      g.required = g.required || required;
      if (optionLabel) g.options.push(optionLabel);
      continue;
    }
    const options =
      tag === 'select' ? Array.from(el.options).map((o) => text(o)).filter(Boolean) : [];
    out.push({ id: el.id || el.name || '', label: labelOf(el), kind, required, options });
  }
  for (const box of document.querySelectorAll('div, fieldset')) {
    const buttons = Array.from(box.children).filter((c) => c.tagName === 'BUTTON');
    const words = buttons.map((b) => text(b).toLowerCase());
    if (buttons.length === 2 && words.includes('yes') && words.includes('no')) {
      let node = box.parentElement;
      let label = '';
      for (let i = 0; node && !label && i < 4; i += 1, node = node.parentElement) {
        const l = node.querySelector('label, legend');
        if (l) label = text(l);
      }
      const required = label.includes('*');
      out.push({ id: box.id || '', label, kind: 'yesno', required, options: ['Yes', 'No'] });
    }
  }
  return out;
}
"""

_KIND_TYPES = {
    "text": QuestionType.text,
    "email": QuestionType.email,
    "tel": QuestionType.phone,
    "url": QuestionType.url,
    "number": QuestionType.number,
    "date": QuestionType.date,
    "textarea": QuestionType.textarea,
    "select": QuestionType.select,
    "radio": QuestionType.select,
    "checkbox": QuestionType.multiselect,
    "file": QuestionType.file,
    "yesno": QuestionType.boolean,
}


def questions_from_page_fields(raw: Sequence[Any]) -> list[Question]:
    """Turn the collected page fields into Questions (pure, so it can be tested)."""
    out: list[Question] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        label = " ".join(strip_invisible(str(item.get("label") or "")).split())
        required = bool(item.get("required")) or label.endswith("*")
        label = label.rstrip("* ").strip()
        kind = str(item.get("kind") or "")
        qtype = _KIND_TYPES.get(kind, QuestionType.unknown)
        if kind == "combobox":
            qtype = QuestionType.location if "locat" in label.casefold() else QuestionType.unknown
        base = str(item.get("id") or "") or f"page_{short_hash(label or str(len(out)))}"
        qid, n = base, 2
        while qid in seen:
            qid, n = f"{base}-{n}", n + 1
        seen.add(qid)
        options = [Option(label=str(o), value=str(o)) for o in item.get("options") or [] if o]
        out.append(
            Question(
                id=qid,
                label=label or qid,
                type=qtype,
                required=required,
                options=options,
                section="page",
                board_type=f"page:{kind}",
            )
        )
    return out


def schema_from_page(url: str, *, timeout_ms: int = 30_000) -> list[Question]:
    """Open `url` headless, wait for the form, and read its questions."""
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise GetmeajobError(
            "Reading the Ashby page needs Playwright.",
            hint="Install it with: pip install 'getmeajob[browser]' && playwright install chromium",
        ) from exc
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page(user_agent=USER_AGENT)
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_selector("input, textarea, select", timeout=timeout_ms)
                raw = page.evaluate(_COLLECT_JS)
            finally:
                browser.close()
    except PlaywrightError as exc:
        raise GetmeajobError(
            f"Could not read the form on {url}: {exc.message}",
            hint="Check that Chromium is installed (playwright install chromium) and try later.",
        ) from exc
    return questions_from_page_fields(raw if isinstance(raw, list) else [])
