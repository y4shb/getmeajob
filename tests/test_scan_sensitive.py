"""Tests for scripts/scan_sensitive.py.

Every planted value is assembled at runtime, so no literal secret, personal address or
denylist term appears in this file.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCANNER = Path(__file__).resolve().parents[1] / "scripts" / "scan_sensitive.py"
AT = "@"
NEUTRAL = ("getmeajob maintainers", "maintainers" + AT + "getmeajob.invalid")
DENY_TERM = "zorb" + "latt" + "quintex"
AUTHOR_EMAIL = "pat.author" + AT + "corpmail" + ".io"
PLANTS = {
    "email": "pat.sample" + AT + "mailhost" + ".io",
    "phone": "+44 20 " + "7946 0958",
    "personal-url": "https://www.linked" + "in.com/in/" + "pat-sample-42",
    "key-ant": "sk-" + "ant-" + "api03-" + "Zq8" * 10,
    "key-aws": "AK" + "IA" + "IOSFODNN7" + "EXAMPLE",
    "home-path": "/Us" + "ers/" + "patsample" + "/projects/notes.txt",
}


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("scan_sensitive", SCANNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["scan_sensitive"] = module
    spec.loader.exec_module(module)
    return module


scan = _load()


def _git(repo: Path, *args: str, ident: tuple[str, str] = NEUTRAL) -> None:
    hooks = repo.parent / "no-hooks"
    hooks.mkdir(exist_ok=True)
    base = [
        "git",
        "-c",
        f"user.name={ident[0]}",
        "-c",
        f"user.email={ident[1]}",
        "-c",
        "commit.gpgsign=false",
        "-c",
        "init.defaultBranch=main",
        "-c",
        f"core.hooksPath={hooks}",
    ]
    subprocess.run([*base, *args], cwd=repo, check=True, capture_output=True)


def _new_repo(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "-q")
    return path


def _run(*args: str, env: dict[str, str] | None = None) -> tuple[int, str, dict[str, Any] | None]:
    proc = subprocess.run(
        [sys.executable, str(SCANNER), *args],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, **env} if env else None,
    )
    data = json.loads(proc.stdout) if "--json" in args and proc.returncode in (0, 1) else None
    return proc.returncode, proc.stdout + proc.stderr, data


@pytest.fixture
def planted(tmp_path: Path) -> tuple[Path, Path]:
    repo = _new_repo(tmp_path / "repo")
    (repo / "notes.txt").write_text("\n".join(PLANTS.values()) + "\n", encoding="utf-8")
    (repo / "secret.txt").write_text(f"codename: {DENY_TERM.title()}\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add notes", f"--author=Pat Author <{AUTHOR_EMAIL}>")
    _git(repo, "rm", "-q", "secret.txt")
    _git(repo, "commit", "-q", "-m", "remove secret")
    deny = tmp_path / "deny.txt"
    deny.write_text(f"# private terms\n{DENY_TERM}\n", encoding="utf-8")
    return repo, deny


def _rules(data: dict[str, Any] | None) -> list[str]:
    assert data is not None
    return [f["rule"] for f in data["findings"]]


def test_tree_finds_current_plants(planted: tuple[Path, Path]) -> None:
    repo, deny = planted
    code, output, data = _run("--tree", "--repo", str(repo), "--denylist", str(deny), "--json")
    assert code == 1
    rules = _rules(data)
    for rule in ("email", "phone", "personal-url", "home-path"):
        assert rule in rules, rule
    assert rules.count("key") == 2
    assert "denylist" not in rules  # the file with the term was deleted
    assert all("author" not in f["location"] for f in data["findings"])  # type: ignore[index]
    for value in PLANTS.values():
        assert value not in output


def test_history_finds_deleted_file_and_author(planted: tuple[Path, Path]) -> None:
    repo, deny = planted
    code, output, data = _run("--history", "--repo", str(repo), "--denylist", str(deny), "--json")
    assert code == 1
    locations = {f["location"]: f["rule"] for f in data["findings"]}  # type: ignore[index]
    assert any(loc.startswith("secret.txt:1@") and r == "denylist" for loc, r in locations.items())
    assert any(":author" in loc and r == "email" for loc, r in locations.items())
    assert data["scanned"]["commits"] == 2 and data["scanned"]["blobs"] >= 2  # type: ignore[index]
    assert DENY_TERM not in output.lower() and AUTHOR_EMAIL not in output

    code, human, _ = _run("--repo", str(repo), "--denylist", str(deny))  # default: tree+history
    assert code == 1 and DENY_TERM not in human.lower()
    assert "scan: " in human and "denylist 1" in human


def test_all_objects_finds_orphaned_and_reflog_only_objects(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path / "orphans")
    (repo / "README.md").write_text("clean\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "docs")
    loose = tmp_path / "loose.txt"
    loose.write_text(PLANTS["email"] + "\n", encoding="utf-8")
    _git(repo, "hash-object", "-w", str(loose))  # a blob that no commit points at
    (repo / "notes.txt").write_text(PLANTS["key-aws"] + "\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "oops")
    _git(repo, "reset", "-q", "--hard", "HEAD~1")  # that commit is now only in the reflog
    code, output, data = _run("--history", "--repo", str(repo), "--json")
    assert code == 0 and data is not None and data["findings"] == [], output
    code, output, data = _run("--all-objects", "--repo", str(repo), "--json")
    assert code == 1 and data is not None
    found = {f["rule"]: f["location"] for f in data["findings"]}
    assert found["email"].startswith("(no path):1@") and found["key"].startswith("notes.txt:1@")
    assert PLANTS["email"] not in output and PLANTS["key-aws"] not in output


def test_clean_repo_exits_zero(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path / "clean")
    (repo / "README.md").write_text(
        "Contact alex" + AT + "example.com or call +1 555 0100.\n"
        "Built 2026-11-27T10:00:00Z, version 1.2.3, id 5a1e0000-0000-4000-8000-000000000001.\n",
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "docs")
    code, output, data = _run("--repo", str(repo), "--json")
    assert code == 0, output
    assert data is not None and data["findings"] == []


def test_staged_mode_checks_index_and_identity(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path / "staged")
    _git(repo, "config", "user.name", NEUTRAL[0])
    _git(repo, "config", "user.email", NEUTRAL[1])
    (repo / "config.txt").write_text(PLANTS["key-aws"] + "\n", encoding="utf-8")
    _git(repo, "add", "config.txt")
    code, output, data = _run("--staged", "--repo", str(repo), "--json")
    assert code == 1 and _rules(data) == ["key"]

    # An identity set in this repo's own config is a deliberate choice: not a finding.
    _git(repo, "config", "user.email", AUTHOR_EMAIL)
    code, output, data = _run("--staged", "--repo", str(repo), "--json")
    assert _rules(data) == ["key"]

    # An identity that only comes from the global config is checked.
    _git(repo, "config", "--unset", "user.name")
    _git(repo, "config", "--unset", "user.email")
    global_cfg = tmp_path / "global.gitconfig"
    global_cfg.write_text(f"[user]\n\tname = Pat Author\n\temail = {AUTHOR_EMAIL}\n")
    code, output, data = _run(
        "--staged", "--repo", str(repo), "--json", env={"GIT_CONFIG_GLOBAL": str(global_cfg)}
    )
    assert "email" in _rules(data) and AUTHOR_EMAIL not in output


def test_local_identity_allowed_in_history(tmp_path: Path) -> None:
    owner = ("Pat Owner", "pat.owner" + AT + "corpmail" + ".io")
    repo = _new_repo(tmp_path / "owned")
    _git(repo, "config", "user.name", owner[0])
    _git(repo, "config", "user.email", owner[1])
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "first", ident=owner)
    code, output, data = _run("--history", "--repo", str(repo), "--json")
    assert code == 0, output

    (repo / "more.md").write_text("more\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "second", f"--author=Pat Author <{AUTHOR_EMAIL}>", ident=owner)
    code, output, data = _run("--history", "--repo", str(repo), "--json")
    assert code == 1
    assert any(":author" in f["location"] for f in data["findings"])  # type: ignore[index]


def test_skip_identity_flag(planted: tuple[Path, Path]) -> None:
    repo, deny = planted
    code, output, data = _run(
        "--history", "--skip-identity", "--repo", str(repo), "--denylist", str(deny), "--json"
    )
    assert code == 1
    locations = [f["location"] for f in data["findings"]]  # type: ignore[index]
    assert not any(":author" in loc or ":committer" in loc for loc in locations)
    assert "denylist" in _rules(data)


def test_path_mode_skips_venv_and_honours_allow(tmp_path: Path) -> None:
    root = tmp_path / "folder"
    (root / ".venv" / "lib").mkdir(parents=True)
    (root / ".venv" / "lib" / "x.txt").write_text(PLANTS["email"], encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "a.md").write_text(
        f"{PLANTS['email']}\n{PLANTS['phone']}  scan:allow\n", encoding="utf-8"
    )
    code, _, data = _run("--path", str(root), "--json")
    assert code == 1 and _rules(data) == ["email"]
    (root / ".scan-allow").write_text("^email:docs/a\\.md:1$\n", encoding="utf-8")
    code, _, data = _run("--path", str(root), "--json")
    assert code == 0 and data is not None and data["scanned"]["files"] == 2


def test_usage_errors_exit_two(tmp_path: Path) -> None:
    assert _run("--path", str(tmp_path / "missing"))[0] == 2
    assert _run("--path", str(tmp_path), "--tree")[0] == 2
    assert _run("--path", str(tmp_path), "--all-objects")[0] == 2
    assert _run("--tree", "--repo", str(tmp_path))[0] == 2  # not a git repository
    assert _run("--path", str(tmp_path), "--denylist", str(tmp_path / "nope.txt"))[0] == 2
    (tmp_path / ".scan-allow").write_text("([unclosed\n", encoding="utf-8")
    assert _run("--path", str(tmp_path))[0] == 2


# ---------------------------------------------------------------- unit level


def _hits(text: str, deny: list[str] | None = None) -> list[str]:
    rules = scan.Rules([scan._denylist_pattern(t) for t in deny or []])
    return [rule for rule, _ in rules.scan_text(text)]


def test_phone_rule_ignores_noise() -> None:
    assert _hits(PLANTS["phone"]) == ["phone"]
    assert _hits("call (415) " + "555-2671 today") == ["phone"]
    for text in (
        "+1 555 0100",
        "+1 613 555 0123",
        "2026-11-27 10:00:00",
        "timestamp 2026-11-27T10:00:00Z",
        "ashby:samplesystems:5a1e0000-0000-4000-8000-000000000001",
        "smartrecruiters:PlaceholderLabs:744000000000001",
        "version 10.0.19041.1234 and ip 192.168.100.200",
        "https://example.com/jobs/2021-0042-1234-5678",
        "1700000000 +0000",
    ):
        assert "phone" not in _hits(text), text


def test_email_url_home_rules() -> None:
    assert _hits("x " + "a" + AT + "example.org y " + "b" + AT + "mail.example.com") == []
    assert _hits("noreply" + AT + "corp.io, team" + AT + "getmeajob.invalid") == []
    assert _hits("logo" + AT + "2x.png") == []
    assert _hits("https://github.com/" + "someone") == ["personal-url"]
    assert _hits("https://github.com/features/actions") == []
    assert _hits("https://someone.github" + ".io/blog") == ["personal-url"]
    assert _hits("see https://dropbox.com/" + "x and box.com/y") == []
    assert _hits("/home/runner/work and /Users/<name>/repo and C:\\Users\\you\\x") == []
    assert _hits("C:\\Us" + "ers\\patsample\\file") == ["home-path"]
    assert _hits("https://example.com/home/page") == []


def test_denylist_matching_modes() -> None:
    assert _hits("value: PRIVATE_THING_KEY", ["PRIVATE_THING_KEY"]) == ["denylist"]
    assert _hits("private_thing_key", ["PRIVATE_THING_KEY"]) == []  # env-like: case-sensitive
    assert _hits("Hello Pat Sampleton!", ["pat sampleton"]) == ["denylist"]
    assert _hits("pat-sampleton and patsampleton", ["Pat Sampleton"]) == ["denylist", "denylist"]
    assert _hits("patsampletons", ["pat sampleton"]) == []  # whole word only
    assert _hits("x@@y", ["@@"]) == ["denylist"]  # substring for non-word edges


def test_binary_zip_and_pdf(tmp_path: Path) -> None:
    sc = scan.Scanner(scan.Rules([scan._denylist_pattern(DENY_TERM)]))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", f"<t>{PLANTS['email']}</t>")
    sc.content("tracker.xlsx", buffer.getvalue(), lambda s: f"tracker.xlsx:{s}")
    from getmeajob.demo import write_simple_pdf

    pdf = tmp_path / "cv.pdf"
    write_simple_pdf(pdf, [f"Name {DENY_TERM}"])
    sc.content("cv.pdf", pdf.read_bytes(), lambda s: f"cv.pdf:{s}")
    sc.content("big.bin", b"\0" * (scan.MAX_BYTES + 1), lambda s: f"big.bin:{s}")
    found = {(f.rule, f.location.split(":")[0]) for f in sc.findings}
    assert ("email", "tracker.xlsx!xl/sharedStrings.xml") in found
    assert ("denylist", "cv.pdf") in found
    assert ("large-file", "big.bin") in found


def test_mask_and_redact() -> None:
    assert scan.mask("abcdefghijkl") == "ab\u2026(12)"
    rules = scan.Rules([scan._denylist_pattern(DENY_TERM)])
    shown = scan.redact(f"docs/{DENY_TERM}-notes.md:(name)", rules, [])
    assert DENY_TERM not in shown and shown.startswith("docs/")


def test_allow_scoped_to_file_and_term(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path / "scoped")
    (repo / "NOTICE").write_text(f"Copyright {DENY_TERM.title()}\n", encoding="utf-8")
    (repo / "app.py").write_text(f"AUTHOR = '{DENY_TERM}'\n", encoding="utf-8")
    deny = tmp_path / "deny.txt"
    deny.write_text(f"{DENY_TERM}\n", encoding="utf-8")
    private_allow = tmp_path / "allow.txt"
    private_allow.write_text(f"(?i)^denylist:NOTICE:[^=]*={DENY_TERM}$\n", encoding="utf-8")
    code, output, data = _run(
        "--tree",
        "--repo",
        str(repo),
        "--denylist",
        str(deny),
        "--json",
        env={"GETMEAJOB_ALLOW": str(private_allow)},
    )
    assert code == 1
    locations = [f["location"] for f in data["findings"]]  # type: ignore[index]
    assert locations == ["app.py:1"]
    assert DENY_TERM not in output.lower()
