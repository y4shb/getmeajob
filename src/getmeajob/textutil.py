"""Small text helpers: HTML to text, label normalising, slugs, hashes, refusal notices."""

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
# "Do not use automated tools" notices aimed at the applicant. A sentence counts when it
# names a tool, a prohibition and the application itself, and is not the employer
# describing its own tools ("We never use automated tools to screen candidates").
_TOOL = re.compile(
    r"\b(ai|artificial intelligence|chatgpt|gpt|llms?|(large )?language models?|chat ?bots?|"
    r"bots?|automated|automation|auto-?fill\w*|scripts?|scripted)\b",
    re.I,
)
_NO = re.compile(
    r"\b(do not|don['’]t|must not|may not|should not|cannot|can['’]t|never|refrain from|"
    r"prohibited|forbidden|banned|not (be )?(accepted|allowed|permitted|considered)|"
    r"(will be|are|is) (rejected|disqualified|removed|discarded|ignored))\b",
    re.I,
)
_FOR = re.compile(
    r"\b(apply|applying|applications?|applicants?|this (form|role|job|position|posting)|"
    r"your (answers?|responses?|cover letter|application|resume|cv)|"
    r"answer(ing)? (these|the|any|our) questions|(these|screening) questions|"
    r"fill(ing)? (out|in) (this|the) form)\b",
    re.I,
)
_SELF = re.compile(
    r"\b(we|our [\w-]+( [\w-]+)?|recruiters?|engineers?|employees?|staff|hiring managers?)\b"
    r"[^.!?;\n]{0,30}?\b(do not|don['’]t|never|won['’]t|will not|must not|may not|cannot)\s+"
    r"(use|rely on|employ)\b",
    re.I,
)
_DIRECT = re.compile(
    r"\bif you are an? (ai|llm|(ai )?language model|bot|automated (agent|tool|system))\b|"
    r"\bmust be (completed|filled( out)?|submitted|written|answered) by "
    r"(a human|a person|you personally|yourself|hand)\b",
    re.I,
)
_SENTENCE = re.compile(r"[^.!?;\n]+[.!?;]?")


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
    out = tidy_lines(out)
    if max_chars is not None:
        out = truncate(out, max_chars)
    return out


def strip_invisible(text: str) -> str:
    """Remove zero-width characters, bidi controls, soft hyphens and the BOM."""
    return text.translate(_INVISIBLE_TABLE)


def one_line(text: str) -> str:
    """Text on one line: invisible characters gone, every run of whitespace one space."""
    return " ".join(strip_invisible(text).split())


def tidy_lines(text: str) -> str:
    """Plain text that keeps its lines: invisible characters gone, no-break spaces and
    runs of spaces made one space, each line trimmed, at most one blank line in a row."""
    out = strip_invisible(text).replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    lines = [_SPACES.sub(" ", line).strip() for line in out.split("\n")]
    return _MANY_NEWLINES.sub("\n\n", "\n".join(lines)).strip()


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


def sentence_at(text: str, match: re.Match[str]) -> str:
    """The sentence holding a match, on one line, at most 200 characters."""
    start = max(text.rfind(".", 0, match.start()), text.rfind("\n", 0, match.start())) + 1
    stops = [i for i in (text.find(".", match.end()), text.find("\n", match.end())) if i != -1]
    end = min(stops) + 1 if stops else len(text)
    return truncate(" ".join(text[start:end].split()), 200)


def refusal_in(text: str) -> str | None:
    """The sentence asking applicants not to use automated tools, or None."""
    for found in _SENTENCE.finditer(text):
        s = found.group(0)
        direct = _DIRECT.search(s)
        aimed = _TOOL.search(s) and _NO.search(s) and _FOR.search(s) and not _SELF.search(s)
        if direct or aimed:
            return truncate(" ".join(s.split()), 200)
    return None
