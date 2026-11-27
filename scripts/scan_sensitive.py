#!/usr/bin/env python3
"""Scan this repository for personal data and secrets before it goes public.

Standalone, standard library only (Python 3.11+).

Modes (default with no mode flag: --tree --history):
  --tree        tracked files plus untracked files that are not ignored
  --history     every blob reachable from any ref (each once), every commit and tag
                message, every author, committer and tagger, every ref name
  --staged      the blobs in the index and the configured git identity (pre-commit)
  --path DIR    walk a folder without git (skips .git, .venv, caches, node_modules)

Identity: the name and email set in this repo's own git config (git config --local)
are the owner's deliberate choice and are not findings in commit metadata.
--skip-identity skips author/committer checks entirely (used in CI).

Rules: email, phone, personal-url, key, home-path, denylist, large-file.
A private denylist (one term per line, # comments) comes from --denylist or the
GETMEAJOB_DENYLIST environment variable. Findings never print a denylist term or
the full matched text: each shows `location  rule  mask`, where the mask keeps two
characters and the length. ALL-CAPS terms (env names, acronyms) match
case-sensitively as whole tokens; other terms match case-insensitively as whole
words, or as substrings when they start or end with punctuation.

Allow rules: `.scan-allow` in the repo root (or --allow FILE), one regex per line,
searched in `rule:location` and in `rule:matched-text` (so a line like
`personal-url:github\\.com/owner/repo` allows that one repository link). A line of a
scanned file that contains the marker `scan:allow` is skipped.

Exit codes: 0 clean, 1 findings, 2 usage or setup error.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
import zipfile
import zlib
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

MAX_BYTES = 5 * 1024 * 1024
ALLOW_MARKER = "scan:" + "allow"
SKIP_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__",
    ".mypy_cache", ".ruff_cache", ".pytest_cache", ".tox", ".nox", ".cache", ".eggs",
}  # fmt: skip
ZIP_EXTS = {".zip", ".xlsx", ".xlsm", ".docx", ".pptx", ".odt", ".ods", ".odp", ".jar", ".whl"}
STRINGS_EXTS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".ico", ".heic",
}  # fmt: skip

# ------------------------------------------------------------------ generic rules
# Patterns are built from parts so this file does not match its own definitions.
AT = "@"
EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9._%+-]+)" + AT
    + r"([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24})(?![A-Za-z0-9-])"
)  # fmt: skip
EMAIL_OK_DOMAINS = ("example.com", "example.org", "example.net")
EMAIL_OK_TLDS = {"example", "invalid", "test", "localhost"}
NOT_EMAIL_TLDS = {"png", "jpg", "jpeg", "gif", "svg", "webp", "css", "js", "ts", "py", "json",
                  "yaml", "yml", "md", "txt", "html", "pdf", "toml", "lock"}  # fmt: skip

PHONE_PLUS = re.compile(r"(?<![\w+])\+\d{1,3}(?:[ .-]?\(?\d{1,5}\)?){1,6}(?![\w])")
PHONE_GROUPED = re.compile(r"(?<![\w+.:/#=-])\(?\d{2,5}\)?(?:[ .-]\d{2,5}){2,5}(?![\w.:/-])")
FICTION_PHONE = re.compile(r"1?(?:\d{3})?55501\d\d")  # +1 555 01xx is reserved for fiction
DATE_IN = re.compile(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{4}")
NOISE = [
    re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S+"),  # URLs
    re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"),
    re.compile(r"\b[0-9a-fA-F]{12,}\b"),  # hex ids and long digit runs
    re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?"),
    re.compile(r"\b[vV]?\d+(?:\.\d+){2,}\b"),  # versions and IP addresses
]
NANP_DOTTED = re.compile(r"\d{3}\.\d{3}\.\d{4}")

PERSONAL_URL = [
    re.compile(r"linkedin\.com/(?:in|pub)/[A-Za-z0-9%_.-]+", re.I),
    re.compile(r"twitter\.com/[A-Za-z0-9_]{1,15}", re.I),
    re.compile(r"(?:(?<=//)|(?<=www\.)|(?<![\w.@-]))x\.com/[A-Za-z0-9_]{1,15}", re.I),
    re.compile(r"[A-Za-z0-9-]+\.(?:github\.io|vercel\.app|netlify\.app)", re.I),
]
GITHUB = re.compile(r"(?:github\.com|githubusercontent\.com)/([A-Za-z0-9-]+)(?:/[\w.-]+)?", re.I)
GITHUB_SITE_PATHS = {
    "about", "apps", "codespaces", "collections", "contact", "customer-stories", "enterprise",
    "explore", "features", "issues", "join", "login", "marketplace", "new", "notifications",
    "pricing", "pulls", "search", "security", "settings", "site", "team", "topics", "trending",
}  # fmt: skip

KEYS = [  # scan:allow (the lines below define the secret patterns)
    re.compile(r"(?<![A-Za-z0-9])sk-ant-[A-Za-z0-9_-]{20,}"),  # scan:allow
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9]{32,}"),  # scan:allow
    re.compile(r"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{30,}"),  # scan:allow
    re.compile(r"(?<![A-Za-z0-9])github_pat_[A-Za-z0-9_]{40,}"),  # scan:allow
    re.compile(r"(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}(?![0-9A-Z])"),  # scan:allow
    re.compile(r"(?<![A-Za-z0-9])xox[abprs]-[A-Za-z0-9-]{10,}"),  # scan:allow
    re.compile(r"(?<![A-Za-z0-9])AIza[0-9A-Za-z_-]{35}"),  # scan:allow
    re.compile(r"(?<![A-Za-z0-9])(?:sk|rk)_live_[0-9A-Za-z]{20,}"),  # scan:allow
    re.compile(r"(?<![A-Za-z0-9])glpat-[A-Za-z0-9_-]{20,}"),  # scan:allow
    re.compile(r"(?<![A-Za-z0-9])npm_[A-Za-z0-9]{36}"),  # scan:allow
    re.compile(r"hooks\.slack\.com/services/T[A-Za-z0-9]+/[A-Za-z0-9/]+"),  # scan:allow
    re.compile("-----BEGIN [A-Z ]*" + "PRIVATE KEY-----"),  # scan:allow
    re.compile(  # scan:allow
        r"(?i)(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"][A-Za-z0-9_\-/+=]{24,}['\"]"
    ),
]
HOME = [
    re.compile(r"(?<![\w.-])/(?:Users|home)/(<[^>]*>|[^/\s'\"`<>(){}\[\],;]+)"),
    re.compile(r"(?<![\w.-])[A-Za-z]:(?:\\\\|\\|/)Users(?:\\\\|\\|/)(<[^>]*>|[^\\/\s'\"`<>]+)"),
]
HOME_PLACEHOLDERS = {"you", "user", "username", "runner", "me", "example", "~", "shared", "name",
                     "yourname", "your-name", "someone", "*", "...", "…"}  # fmt: skip
# ALL-CAPS terms (env names, acronyms) match case-sensitively as whole tokens.
ENV_LIKE = re.compile(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*")


@dataclass(frozen=True)
class Finding:
    rule: str
    location: str
    value: str  # never printed in full


def mask(value: str) -> str:
    return f"{value[:2]}…({len(value)})"


def _email_ok(local: str, domain: str) -> bool:
    d = domain.lower().rstrip(".")
    tld = d.rsplit(".", 1)[-1]
    if local.lower() in ("noreply", "no-reply") or d == "localhost":
        return True
    if tld in EMAIL_OK_TLDS or tld in NOT_EMAIL_TLDS:
        return True
    return any(d == base or d.endswith("." + base) for base in EMAIL_OK_DOMAINS)


def _denoise(line: str) -> str:
    """Hide URLs, UUIDs, hex ids, timestamps and versions before looking for phones."""

    def hide(m: re.Match[str]) -> str:
        return m.group(0) if NANP_DOTTED.fullmatch(m.group(0)) else "x" * len(m.group(0))

    for pattern in NOISE:
        line = pattern.sub(hide, line)
    return line


def _phones(line: str) -> list[str]:
    found: list[str] = []
    spans: list[tuple[int, int]] = []
    clean = _denoise(line)
    for pattern, plus in ((PHONE_PLUS, True), (PHONE_GROUPED, False)):
        for m in pattern.finditer(clean):
            if any(m.start() < end and start < m.end() for start, end in spans):
                continue  # already covered by a longer match
            text = m.group(0).strip()
            digits = re.sub(r"\D", "", text)
            if not (10 <= len(digits) <= (15 if plus else 13)):
                continue
            if FICTION_PHONE.fullmatch(digits) or DATE_IN.search(text):
                continue
            seps = set(re.sub(r"[\d()+]", "", text))
            if seps == {"."} and not NANP_DOTTED.fullmatch(text):
                continue
            spans.append((m.start(), m.end()))
            if text not in found:
                found.append(text)
    return found


def _denylist_body(term: str) -> tuple[str, str]:
    """(group, regex body) for one denylist term; groups are combined into a few big regexes."""
    if ENV_LIKE.fullmatch(term):
        return "caps", re.escape(term)
    words = term.split()
    if term[0].isalnum() and term[-1].isalnum():
        return "word", r"[\s._-]*".join(re.escape(w) for w in words)
    return "plain", r"\s+".join(re.escape(w) for w in words)


def _denylist_patterns(terms: Iterable[str]) -> list[re.Pattern[str]]:
    groups: dict[str, list[str]] = {"caps": [], "word": [], "plain": []}
    for term in terms:
        group, body = _denylist_body(term)
        groups[group].append(body)
    patterns: list[re.Pattern[str]] = []
    for group, bodies in groups.items():
        if not bodies:
            continue
        alt = "|".join(sorted(set(bodies), key=len, reverse=True))
        if group == "caps":
            patterns.append(re.compile(rf"(?<![A-Za-z0-9_])(?:{alt})(?![A-Za-z0-9_])"))
        elif group == "word":
            patterns.append(re.compile(rf"(?<![^\W_])(?:{alt})(?![^\W_])", re.I))
        else:
            patterns.append(re.compile(rf"(?:{alt})", re.I))
    return patterns


def _denylist_pattern(term: str) -> re.Pattern[str]:
    return _denylist_patterns([term])[0]


@dataclass
class Rules:
    denylist: list[re.Pattern[str]] = field(default_factory=list)

    def scan_text(self, text: str) -> list[tuple[str, str]]:
        """(rule, matched text) pairs for one line of text."""
        hits: list[tuple[str, str]] = []
        if AT in text:
            for m in EMAIL.finditer(text):
                if not _email_ok(m.group(1), m.group(2)):
                    hits.append(("email", m.group(0)))
        if any(c.isdigit() for c in text):
            hits.extend(("phone", p) for p in _phones(text))
        lowered = text.lower()
        if "." in text:
            for pattern in PERSONAL_URL:
                hits.extend(("personal-url", m.group(0)) for m in pattern.finditer(text))
            if "github" in lowered:
                for m in GITHUB.finditer(text):
                    if m.group(1).lower() not in GITHUB_SITE_PATHS:
                        hits.append(("personal-url", m.group(0)))
        for pattern in KEYS:
            hits.extend(("key", m.group(0)) for m in pattern.finditer(text))
        if "users" in lowered or "home" in lowered:
            for pattern in HOME:
                for m in pattern.finditer(text):
                    name = m.group(1)
                    if name.lower() in HOME_PLACEHOLDERS or name[:1] in "<${%":
                        continue
                    hits.append(("home-path", m.group(0)))
        for pattern in self.denylist:
            hits.extend(("denylist", m.group(0)) for m in pattern.finditer(text))
        return hits


# --------------------------------------------------------------------- content


Where = Callable[[str], str]


@dataclass
class Scanner:
    rules: Rules
    findings: list[Finding] = field(default_factory=list)
    files: int = 0
    blobs: int = 0
    commits: int = 0
    _seen: set[Finding] = field(default_factory=set)

    def _add(self, rule: str, location: str, value: str) -> None:
        finding = Finding(rule, location, value)
        if finding not in self._seen:
            self._seen.add(finding)
            self.findings.append(finding)

    def file(self, full: Path, rel: str) -> None:
        """Scan one file on disk: its name, then its content (or a symlink's target)."""
        self.files += 1

        def where(suffix: str) -> str:
            return f"{rel}:{suffix}"

        self.name(rel, where)
        if full.is_symlink():
            self.text_lines([("(link)", os.readlink(full))], where)
            return
        size = full.stat().st_size
        if size > MAX_BYTES:
            self._add("large-file", where("(size)"), f"{size / 1e6:.1f} MB")
            return
        self.content(rel, full.read_bytes(), where)

    def text_lines(self, lines: Iterable[tuple[str, str]], where: Where) -> None:
        for suffix, line in lines:
            if ALLOW_MARKER in line:
                continue
            for rule, value in self.rules.scan_text(line):
                self._add(rule, where(suffix), value)

    def name(self, path: str, where: Where) -> None:
        self.text_lines([("(name)", path)], where)

    def content(self, path: str, data: bytes, where: Where, depth: int = 0) -> None:
        if len(data) > MAX_BYTES:
            self._add("large-file", where("(size)"), f"{len(data) / 1e6:.1f} MB")
            return
        ext = os.path.splitext(path)[1].lower()
        if depth < 2 and (ext in ZIP_EXTS or data[:4] == b"PK\x03\x04"):
            try:
                self._zip(path, data, where, depth)
                return
            except (zipfile.BadZipFile, OSError, RuntimeError, EOFError):
                pass
        if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
            self._text(data.decode("utf-16", "replace"), where)
        elif ext in STRINGS_EXTS or b"\x00" in data[:8192]:
            self._binary(data, where, pdf=ext == ".pdf" or data[:5] == b"%PDF-")
        else:
            self._text(data.decode("utf-8", "replace"), where)

    def _text(self, text: str, where: Where) -> None:
        self.text_lines(((str(n), line) for n, line in enumerate(text.splitlines(), 1)), where)

    def _binary(self, data: bytes, where: Where, *, pdf: bool) -> None:
        chunks: list[bytes] = [data]
        if pdf:
            for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
                try:  # capped, so a crafted stream cannot blow up memory
                    chunks.append(zlib.decompressobj().decompress(m.group(1), MAX_BYTES))
                except zlib.error:
                    continue
        for n, chunk in enumerate(chunks):
            strings: list[tuple[str, str]] = []
            for pattern, codec in (
                (rb"[\x20-\x7e]{6,}", "ascii"),
                (rb"(?:[\x20-\x7e]\x00){6,}", "utf-16-le"),
                (rb"(?:\x00[\x20-\x7e]){6,}", "utf-16-be"),
            ):
                for m in re.finditer(pattern, chunk):
                    label = f"@{m.start()}" if n == 0 else f"stream{n}@{m.start()}"
                    strings.append((label, m.group(0).decode(codec, "replace")))
            self.text_lines(strings, where)

    def _zip(self, path: str, data: bytes, where: Where, depth: int) -> None:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                member = f"{path}!{info.filename}"

                def inner(suffix: str, _m: str = info.filename) -> str:
                    return where(f"{_m}:{suffix}").replace(":", "!", 1)

                self.name(info.filename, inner)
                if info.file_size > MAX_BYTES:
                    self._add("large-file", inner("(size)"), f"{info.file_size / 1e6:.1f} MB")
                    continue
                self.content(member, archive.read(info), inner, depth + 1)


# ------------------------------------------------------------------------- git


class SetupError(Exception):
    """A usage or setup problem (exit code 2)."""


def git(root: Path, *args: str, data: bytes | None = None) -> bytes:
    try:
        proc = subprocess.run(["git", *args], cwd=root, input=data, capture_output=True)
    except FileNotFoundError as exc:
        raise SetupError("git is not installed (use --path DIR to scan without git)") from exc
    if proc.returncode != 0:
        msg = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise SetupError(f"git {args[0]} failed: {msg[-1] if msg else 'unknown error'}")
    return proc.stdout


class CatFile:
    """Reads objects one at a time through `git cat-file --batch`."""

    def __init__(self, root: Path) -> None:
        self.proc = subprocess.Popen(
            ["git", "cat-file", "--batch"], cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE
        )

    def read(self, sha: str) -> tuple[str, bytes]:
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self.proc.stdin.write(sha.encode() + b"\n")
        self.proc.stdin.flush()
        header = self.proc.stdout.readline().split()
        if len(header) < 3:
            return ("missing", b"")
        data = self.proc.stdout.read(int(header[2]))
        self.proc.stdout.read(1)
        return (header[1].decode(), data)

    def close(self) -> None:
        if self.proc.stdin is not None:
            self.proc.stdin.close()
        self.proc.wait()


IDENT = re.compile(r"^(author|committer|tagger) (.*?) <([^>]*)>")


def local_identity(root: Path) -> tuple[str, str] | None:
    """The identity set in this repo's own config (not global): the owner's deliberate choice."""
    vals = []
    for key in ("user.name", "user.email"):
        proc = subprocess.run(
            ["git", "config", "--local", "--get", key], cwd=root, capture_output=True
        )
        vals.append(proc.stdout.decode("utf-8", "replace").strip())
    return (vals[0], vals[1]) if all(vals) else None


def scan_tree(sc: Scanner, root: Path) -> None:
    for rel in git(root, "ls-files", "-co", "--exclude-standard", "-z").decode().split("\0"):
        path = root / rel
        if rel and (path.is_file() or path.is_symlink()):
            sc.file(path, rel)


def scan_history(sc: Scanner, root: Path, *, skip_identity: bool = False) -> None:
    allowed_ident = local_identity(root)
    paths: dict[str, str] = {}
    for line in git(root, "rev-list", "--objects", "--all").decode("utf-8", "replace").splitlines():
        sha, _, path = line.partition(" ")
        if sha and sha not in paths:
            paths[sha] = path
    for path in sorted({p for p in paths.values() if p}):
        sc.name(path, lambda s, p=path: f"{p}:{s}@history")
    for ref in git(root, "for-each-ref", "--format=%(refname)").decode().splitlines():
        sc.name(ref, lambda s, r=ref: f"ref {r}")
    if not paths:
        return
    checks = git(root, "cat-file", "--batch-check", data="\n".join(paths).encode() + b"\n")
    cat = CatFile(root)
    try:
        for line in checks.decode().splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            sha, kind, size = parts[0], parts[1], int(parts[2])
            short = sha[:7]
            if kind == "blob":
                sc.blobs += 1
                where = lambda s, p=paths[sha], h=short: f"{p}:{s}@{h}"  # noqa: E731
                if size > MAX_BYTES:
                    sc._add("large-file", where("(size)"), f"{size / 1e6:.1f} MB")
                    continue
                sc.content(paths[sha], cat.read(sha)[1], where)
            elif kind in ("commit", "tag"):
                if kind == "commit":
                    sc.commits += 1
                head, _, message = cat.read(sha)[1].decode("utf-8", "replace").partition("\n\n")
                for h in head.splitlines():
                    m = IDENT.match(h)
                    if m and not skip_identity and (m.group(2), m.group(3)) != allowed_ident:
                        role, ident = m.group(1), f"{m.group(2)} <{m.group(3)}>"
                        sc.text_lines(
                            [("", ident)], lambda s, k=kind, r=role, h7=short: f"{k} {h7}:{r}"
                        )
                sc.text_lines(
                    ((str(n), t) for n, t in enumerate(message.splitlines(), 1)),
                    lambda s, k=kind, h7=short: f"{k} {h7}:message:{s}",
                )
    finally:
        cat.close()


def scan_staged(sc: Scanner, root: Path, *, skip_identity: bool = False) -> None:
    cat = CatFile(root)
    try:
        for entry in git(root, "ls-files", "-s", "-z").decode().split("\0"):
            meta, _, rel = entry.partition("\t")
            parts = meta.split()
            if len(parts) < 3 or parts[0] == "160000":
                continue
            sc.blobs += 1
            sc.name(rel, lambda s, r=rel: f"{r}:{s}")
            sc.content(rel, cat.read(parts[1])[1], lambda s, r=rel: f"{r}:{s}")
    finally:
        cat.close()
    if skip_identity:
        return
    ident = []
    for key in ("user.name", "user.email"):
        proc = subprocess.run(["git", "config", "--get", key], cwd=root, capture_output=True)
        ident.append(proc.stdout.decode("utf-8", "replace").strip())
    if (ident[0], ident[1]) == local_identity(root):
        return  # set on purpose in this repo's own config
    sc.text_lines([("", f"{ident[0]} <{ident[1]}>")], lambda s: "git identity (user.name/email)")


def scan_path(sc: Scanner, root: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and ".egg-info" not in d)
        for name in sorted(filenames):
            full = Path(dirpath) / name
            sc.file(full, full.relative_to(root).as_posix())


# -------------------------------------------------------------------------- CLI


def load_terms(path: Path) -> list[re.Pattern[str]]:
    terms: list[str] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        term = raw.strip()
        if not term or term.startswith("#"):
            continue
        if len(term) < 3:
            print(f"warning: denylist line {number} is very short", file=sys.stderr)
        terms.append(term)
    return _denylist_patterns(terms)


def load_allow(path: Path) -> list[re.Pattern[str]]:
    patterns: list[re.Pattern[str]] = []
    if not path.is_file():
        return patterns
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            patterns.append(re.compile(line))
        except re.error as exc:
            raise SetupError(f"{path} line {number} is not a valid regex: {exc}") from exc
    return patterns


def redact(text: str, rules: Rules, values: Iterable[str]) -> str:
    for value in sorted(set(values), key=len, reverse=True):
        if len(value) >= 3:
            text = text.replace(value, mask(value))
    for pattern in rules.denylist:
        text = pattern.sub(lambda m: mask(m.group(0)), text)
    return text


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    p.add_argument("--tree", action="store_true", help="tracked and untracked-not-ignored files")
    p.add_argument("--history", action="store_true", help="all reachable blobs, commits, refs")
    p.add_argument("--staged", action="store_true", help="index blobs and git identity")
    p.add_argument("--path", metavar="DIR", help="walk a folder without git")
    p.add_argument("--repo", metavar="DIR", default=".", help="repository folder (default .)")
    p.add_argument("--denylist", metavar="FILE", help="private terms (default GETMEAJOB_DENYLIST)")
    p.add_argument("--allow", metavar="FILE", help="allow regexes (default .scan-allow in root)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument(
        "--skip-identity",
        action="store_true",
        help="do not check commit author/committer identities (CI; commit metadata is public)",
    )
    args = p.parse_args(argv)
    if args.path and (args.tree or args.history or args.staged):
        p.error("--path cannot be combined with --tree, --history or --staged")
    if not (args.path or args.tree or args.history or args.staged):
        args.tree = args.history = True
    return args


def run(args: argparse.Namespace) -> int:
    deny_file = args.denylist or os.environ.get("GETMEAJOB_DENYLIST", "").strip() or None
    if deny_file and not Path(deny_file).is_file():
        raise SetupError("the denylist file does not exist (check --denylist or the env var)")
    rules = Rules(load_terms(Path(deny_file)) if deny_file else [])
    sc = Scanner(rules)
    if args.path:
        root = Path(args.path).resolve()
        if not root.is_dir():
            raise SetupError(f"{args.path} is not a folder")
    else:
        root = Path(git(Path(args.repo), "rev-parse", "--show-toplevel").decode().strip())
    allow = load_allow(Path(args.allow) if args.allow else root / ".scan-allow")
    if args.path:
        scan_path(sc, root)
    if args.tree:
        scan_tree(sc, root)
    if args.history:
        scan_history(sc, root, skip_identity=args.skip_identity)
    if args.staged:
        scan_staged(sc, root, skip_identity=args.skip_identity)

    def allowed(f: Finding) -> bool:
        keys = (f"{f.rule}:{f.location}", f"{f.rule}:{f.value}")
        return any(p.search(k) for p in allow for k in keys)

    findings = [f for f in sc.findings if not allowed(f)]
    values = [f.value for f in findings]
    rows = [
        {
            "location": redact(f.location, rules, values),
            "rule": f.rule,
            "mask": f.value if f.rule == "large-file" else mask(f.value),
        }
        for f in findings
    ]
    counts = Counter(f.rule for f in findings)
    scanned = {"files": sc.files, "blobs": sc.blobs, "commits": sc.commits}
    if args.json:
        print(json.dumps({"findings": rows, "counts": dict(counts), "scanned": scanned}))
    else:
        for row in rows:
            print(f"{row['location']}  {row['rule']}  {row['mask']}")
        totals = ", ".join(f"{rule} {n}" for rule, n in sorted(counts.items()))
        what = f"{sc.files} files, {sc.blobs} blobs, {sc.commits} commits scanned"
        status = f"{len(findings)} findings ({totals})" if findings else "clean"
        print(f"scan: {status}; {what}")
    return 1 if findings else 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except SetupError as exc:
        print(f"scan error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
