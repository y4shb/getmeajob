"""Find the job board (ATS and slug) for companies, from URLs or names.

Each input line is a board URL, a careers page URL, a company name, or a name and a
URL together ("Example Corp, https://...").
- Board URLs are read directly (no network).
- Careers pages are fetched (robots.txt respected) and scanned for ATS links; a page
  with none leads to at most a few of its own careers or jobs links.
- Names give up to 8 slug guesses, probed on the boards with fixed API hosts. A hit
  needs open jobs and a board name that does not contradict the company.
Discovery never asks a third-party lookup service about the company.
"""

from __future__ import annotations

import difflib
import html
import re
import threading
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import urljoin

from getmeajob.errors import BotWallError, GetmeajobError, RobotsDisallowed
from getmeajob.http import HttpClient
from getmeajob.models import Board
from getmeajob.sources.boards import board_id
from getmeajob.sources.common import DISCOVERY_TTL, split_url
from getmeajob.sources.lever import lever_region
from getmeajob.sources.registry import all_sources

# Recruitee boards live on their own sub-domain, so a wrong guess costs a slow DNS
# failure with retries; it is found from URLs and careers pages only.
PROBE_ORDER = ("greenhouse", "ashby", "lever", "smartrecruiters", "workable")
MAX_CANDIDATES = 8
MAX_PAGE_FETCHES = 4
MAX_PAGE_BOARDS = 5
NAME_RATIO = 0.7
SUFFIX_WORDS = frozenset(
    {
        *("inc", "ltd", "limited", "pvt", "private", "llc", "plc", "corp", "corporation"),
        *("co", "company", "technologies", "technology", "labs", "systems", "software"),
        *("global", "tech", "group", "services", "solutions", "holdings", "ventures"),
        *("partners", "consulting", "digital", "international", "ai", "hq"),
    }
)
EXTRA_SUFFIXES = ("ai", "hq", "inc", "labs", "tech")

_HTTP_URL = re.compile(r"https?://[^\s,;|<>\"']+", re.IGNORECASE)
_BARE_URL = re.compile(
    r"\b(?:[\w-]+\.)+[a-z]{2,}/[^\s,;|<>\"']*|\b[\w-]+\.(?:recruitee|workable)\.com\b",
    re.IGNORECASE,
)
_PAGE_URL = re.compile(r"(?:https?:)?//[^\s\"'<>()\\]+", re.IGNORECASE)
_HREF = re.compile(r"""href\s*=\s*["']([^"'#]+)["']""", re.IGNORECASE)
_CAREERS_WORD = re.compile(r"career|jobs|join|opening|positions|work-with-us|hiring", re.I)


@dataclass
class DiscoveryResult:
    input: str
    company: str
    board: Board | None
    confidence: str  # "url" | "verified" | "unverified" | "none"
    tried: list[str] = field(default_factory=list)
    note: str = ""


class _State:
    """Shared by the worker threads: ATS hosts that showed a bot check this run."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.walls: set[str] = set()

    def blocked(self, ats: str) -> bool:
        with self._lock:
            return ats in self.walls

    def block(self, ats: str) -> None:
        with self._lock:
            self.walls.add(ats)


# ------------------------------------------------------------------- names


def _words(name: str) -> list[str]:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"\([^)]*\)", " ", text).replace("&", " and ")
    text = re.sub(r"[,.'`]", "", text)
    return re.findall(r"[a-z0-9]+", text)


def _strip_suffixes(words: list[str]) -> list[str]:
    out = list(words)
    while len(out) > 1 and out[-1] in SUFFIX_WORDS:
        out.pop()
    return out


def slug_candidates(name: str) -> list[str]:
    """Up to 8 slug guesses: raw and suffix-stripped names, joined and hyphenated,
    then the stripped base plus ai, hq, inc, labs and tech."""
    raw = _words(name)
    stripped = _strip_suffixes(raw)
    forms = ["".join(raw), "-".join(raw), "".join(stripped), "-".join(stripped)]
    base = "".join(stripped)
    if len(base) >= 3:  # "ai" + "hq" is not a useful guess
        forms += [base + extra for extra in EXTRA_SUFFIXES]
    out: list[str] = []
    for form in forms:
        if 3 <= len(form) <= 39 and form not in out:
            out.append(form)
    return out[:MAX_CANDIDATES]


def _norm(text: str) -> str:
    return "".join(_words(text))


def name_matches(company: str, board_name: str | None) -> bool | None:
    """True when the board's own name fits the company, False when it contradicts it,
    None when the board has no name to compare."""
    if not board_name or not board_name.strip():
        return None
    pairs = [
        (_norm(company), _norm(board_name)),
        ("".join(_strip_suffixes(_words(company))), "".join(_strip_suffixes(_words(board_name)))),
    ]
    for a, b in pairs:
        if len(a) >= 3 and len(b) >= 3 and (a in b or b in a):
            return True
    best = max(
        (difflib.SequenceMatcher(None, a, b).ratio() for a, b in pairs if a and b), default=0.0
    )
    return best >= NAME_RATIO


# -------------------------------------------------------------------- URLs


def parse_line(line: str) -> tuple[str, str | None]:
    """(company name, URL) from an input line; either part may be empty."""
    text = line.strip()
    match = _HTTP_URL.search(text) or _BARE_URL.search(text)
    if match is None:
        return text, None
    url = match.group(0).rstrip(".,;)")
    name = (text[: match.start()] + " " + text[match.end() :]).strip(" ,;|\t-")
    return name, url


def board_from_url(url: str, company: str = "") -> Board | None:
    """The board a URL points to, if it is a known ATS URL."""
    for name, source in all_sources().items():
        slug = source.parse_url(url)
        if slug:
            region = lever_region(url) if name == "lever" else None
            return Board(company=company or slug, ats=name, slug=slug, region=region)
    return None


def _boards_in_page(final_url: str, text: str, company: str) -> list[Board]:
    page = html.unescape(text.replace("\\/", "/"))
    found: dict[tuple[str, str], Board] = {}
    for url in [final_url, *_PAGE_URL.findall(page)]:
        full = "https:" + url if url.startswith("//") else url
        board = board_from_url(full.rstrip(".,;"), company)
        if board is not None:
            found.setdefault(board_id(board), board)
    return list(found.values())[:MAX_PAGE_BOARDS]


def _site(host: str) -> str:
    return ".".join(host.split(".")[-2:])


def _careers_links(base_url: str, text: str) -> list[str]:
    base_host, _, _ = split_url(base_url)
    links: list[str] = []
    for href in _HREF.findall(text):
        url = urljoin(base_url, html.unescape(href).strip())
        host, segments, _ = split_url(url)
        if not url.startswith(("http://", "https://")) or _site(host) != _site(base_host):
            continue
        if _CAREERS_WORD.search("/".join(segments) + host) and url not in links:
            links.append(url)
    return links[:3]


# ---------------------------------------------------------------- discover


def _probe_names(line: str, name: str, client: HttpClient, state: _State) -> DiscoveryResult:
    sources = all_sources()
    tried: list[str] = []
    mismatches: list[str] = []
    failures = 0
    for slug in slug_candidates(name):
        for ats in PROBE_ORDER:
            source = sources.get(ats)
            if source is None or state.blocked(ats):
                continue
            tried.append(f"{ats}:{slug}")
            try:
                probe = source.probe(slug, client)
            except BotWallError:
                state.block(ats)
                continue
            except GetmeajobError:
                failures += 1
                continue
            if not probe.found or probe.count <= 0:
                continue
            fits = name_matches(name, probe.board_name)
            if fits is False:
                mismatches.append(f"{ats}:{slug} belongs to '{probe.board_name}'")
                continue
            note = f"{probe.count} open jobs"
            if fits is None:
                note += "; the board has no name to compare, so check it is the right company"
            board = Board(company=name, ats=ats, slug=slug, verified=fits is True)
            return DiscoveryResult(
                line, name, board, "verified" if fits else "unverified", tried, note
            )
    parts = ["no board found"]
    if mismatches:
        parts.append("rejected (name does not match): " + "; ".join(mismatches[:3]))
    if failures and failures == len(tried):
        parts.append("every lookup failed (offline mode, or no network?)")
    elif failures:
        parts.append(f"{failures} lookups failed")
    return DiscoveryResult(line, name, None, "none", tried, "; ".join(parts))


def _scan_careers(
    line: str, name: str, url: str, client: HttpClient, state: _State
) -> DiscoveryResult:
    pages, seen, notes = [url], set(), []
    candidates: list[Board] = []
    fetches = 0
    while pages and fetches < MAX_PAGE_FETCHES and not candidates:
        page = pages.pop(0)
        if page in seen:
            continue
        seen.add(page)
        try:
            resp = client.get(page, ttl=DISCOVERY_TTL, check_robots=True)
        except RobotsDisallowed:
            notes.append(f"robots.txt asks tools not to read {page}")
            continue
        except BotWallError:
            notes.append(f"{page} showed a bot check")
            break
        except GetmeajobError as exc:
            notes.append(exc.message)
            continue
        fetches += 1
        if resp.status >= 400:
            notes.append(f"{page} answered HTTP {resp.status}")
            continue
        candidates = _boards_in_page(resp.url, resp.text, name)
        if not candidates and fetches == 1:
            pages += _careers_links(resp.url, resp.text)
    host, _, _ = split_url(url)
    company = name or host.removeprefix("www.").split(".")[0]
    tried: list[str] = []
    sources = all_sources()
    for board in candidates:
        source = sources[board.ats]
        tried.append(f"{board.ats}:{board.slug}")
        if state.blocked(board.ats):
            continue
        try:
            probe = source.probe(board.slug, client)
        except BotWallError:
            state.block(board.ats)
            continue
        except GetmeajobError:
            continue
        if probe.found and probe.count > 0:
            company = name or probe.board_name or company
            fits = name_matches(company, probe.board_name)
            note = f"linked from the careers page; {probe.count} open jobs"
            if fits is False:
                note += f"; the board is named '{probe.board_name}'"
            found = Board(
                company=company,
                ats=board.ats,
                slug=board.slug,
                region=board.region,
                careers_url=url,
                verified=fits is not False,
            )
            confidence = "unverified" if fits is False else "verified"
            return DiscoveryResult(line, company, found, confidence, tried, note)
    if candidates:
        first = candidates[0]
        found = Board(
            company=company,
            ats=first.ats,
            slug=first.slug,
            region=first.region,
            careers_url=url,
            verified=False,
        )
        note = "linked from the careers page, but the board shows no open jobs right now"
        return DiscoveryResult(line, company, found, "unverified", tried, note)
    notes.insert(0, "no ATS link found on the careers page")
    return DiscoveryResult(line, company, None, "none", tried, "; ".join(notes[:3]))


def _discover_one(line: str, client: HttpClient, state: _State) -> DiscoveryResult:
    name, url = parse_line(line)
    if url is not None:
        board = board_from_url(url, name)
        if board is not None:
            note = "read from the URL"
            if not name:
                note += "; the company name is the slug, edit it in companies.yaml if needed"
            return DiscoveryResult(line, board.company, board, "url", [], note)
        return _scan_careers(line, name, url, client, state)
    return _probe_names(line, name, client, state)


def discover(lines: list[str], client: HttpClient) -> list[DiscoveryResult]:
    """One result per input line (blank lines and `#` comments are skipped)."""
    inputs = [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]
    state = _State()
    results = client.map(lambda line: _discover_one(line, client, state), inputs)
    out: list[DiscoveryResult] = []
    for line, result in zip(inputs, results, strict=True):
        if isinstance(result, Exception):
            name, _ = parse_line(line)
            out.append(DiscoveryResult(line, name, None, "none", [], f"failed: {result}"))
        else:
            out.append(result)
    return out
