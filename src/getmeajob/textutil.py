"""Small text helpers: HTML to text, label normalising, slugs, hashes."""

from __future__ import annotations

import hashlib
import html as _html
import re
import unicodedata
from collections.abc import Iterable
from html.parser import HTMLParser

# Zero-width characters, the BOM, soft hyphen and bidirectional controls.
_INVISIBLE = (
    "­"  # soft hyphen
    "؜"  # Arabic letter mark
    "᠎"  # Mongolian vowel separator
    "​‌‍‎‏"  # zero-width space/joiners, LRM, RLM
    "‪‫‬‭‮"  # bidi embedding and override
    "⁠⁡⁢⁣⁤"  # word joiner and invisible operators
    "⁦⁧⁨⁩"  # bidi isolates
    "﻿"  # BOM / zero-width no-break space
)
_INVISIBLE_TABLE = {ord(c): None for c in _INVISIBLE}

_BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "dd",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tr",
        "ul",
    }
)
_SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "head", "title"})
_ESCAPED_TAG = re.compile(r"&lt;\s*/?\s*[a-zA-Z][a-zA-Z0-9]*[^&]*?&gt;")
_LEFTOVER_ENTITY = re.compile(r"&(?:[a-zA-Z][a-zA-Z0-9]{1,31}|#\d{1,7}|#[xX][0-9a-fA-F]{1,6});")
_TAG = re.compile(r"<[^>]*>")
_SPACES = re.compile(r"[ \t\f\v]+")
_MANY_NEWLINES = re.compile(r"\n{3,}")
_WS = re.compile(r"\s+")
_LABEL_MARKERS = re.compile(r"\((?:required|optional)\)")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0
        self._pre = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in ("td", "th"):
            self.parts.append(" ")
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")
            if tag == "pre":
                self._pre += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")
            if tag == "pre":
                self._pre = max(0, self._pre - 1)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("br", "hr"):
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        self.parts.append(data if self._pre else _WS.sub(" ", data))


def html_to_text(html: str, max_chars: int | None = None) -> str:
    """Readable plain text from HTML, also when the HTML arrives escaped once more.

    Drops scripts and styles, turns block tags into line breaks and list items
    into "- " lines, normalises no-break spaces and removes invisible characters.
    """
    text = html or ""
    # Some APIs send HTML that was escaped twice (`&lt;p&gt;`). Unescape until real tags show.
    for _ in range(2):
        if _ESCAPED_TAG.search(text):
            text = _html.unescape(text)
        else:
            break
    parser = _TextExtractor()
    parser.feed(text)
    parser.close()
    out = "".join(parser.parts)
    if _LEFTOVER_ENTITY.search(out):  # double-escaped entities such as `&amp;nbsp;`
        out = _html.unescape(out)
    out = strip_invisible(out).replace(" ", " ").replace("\r\n", "\n").replace("\r", "\n")
    lines = [_SPACES.sub(" ", line).strip() for line in out.split("\n")]
    out = _MANY_NEWLINES.sub("\n\n", "\n".join(lines)).strip()
    if max_chars is not None:
        out = truncate(out, max_chars)
    return out


def strip_invisible(text: str) -> str:
    """Remove zero-width characters, bidi controls, soft hyphens and the BOM."""
    return text.translate(_INVISIBLE_TABLE)


def norm_label(text: str) -> str:
    """Normalise a form label so small differences do not matter.

    "First Name*", "first name (required)" and "First  name:" all give "first name".
    """
    out = _TAG.sub(" ", text or "")
    out = _html.unescape(out)
    out = strip_invisible(out).replace(" ", " ")
    out = unicodedata.normalize("NFKC", out).casefold()
    out = _LABEL_MARKERS.sub(" ", out)
    out = out.replace("*", " ").replace("✱", " ")
    out = _WS.sub(" ", out).strip()
    return out.rstrip("?:. ").strip()


def slugify(text: str, max_len: int = 60) -> str:
    """Lowercase ASCII slug with hyphens, for file and folder names ("untitled" if empty)."""
    ascii_text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    if max_len > 0 and len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    return slug or "untitled"


def truncate(text: str, n: int) -> str:
    """At most `n` characters; ends with an ellipsis when cut."""
    if n <= 0:
        return ""
    if len(text) <= n:
        return text
    if n == 1:
        return "…"
    return text[: n - 1].rstrip() + "…"


def short_hash(text: str, n: int = 10) -> str:
    """First `n` hex characters of the SHA-1 of `text`."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]


def options_hash(labels: Iterable[str]) -> str:
    """Order-independent hash of a list of option labels (normalised first)."""
    return short_hash("\n".join(sorted(norm_label(label) for label in labels)))
