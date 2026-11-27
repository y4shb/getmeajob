"""The agent files: valid manifests and frontmatter, real CLI commands only, the policy
linked everywhere, and no personal data, forbidden words or long dashes."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from getmeajob import __version__
from getmeajob.agents.install import SKIP_NAMES, Assets
from getmeajob.cli import build_parser
from getmeajob.demo import agents_dir
from getmeajob.plan.cli import SUBCOMMANDS as PLAN_WORDS

AGENTS = agents_dir()
REPO = AGENTS.parent
ASSETS = Assets(AGENTS)
MARKETPLACE = REPO / ".claude-plugin" / "marketplace.json"
PLUGIN_JSON = ASSETS.plugin_dir / ".claude-plugin" / "plugin.json"
COMMANDS = {
    "source",
    "rank",
    "plan",
    "review-answers",
    "apply-dry",
    "hold-run",
    "queue",
    "status",
    "tracker",
    "resume",
}
# Placeholders the assets use in example commands, and a value that parses for each.
PLACEHOLDERS = {
    "KEY": "greenhouse:examplecorp:1001",
    "FILE": "answers-todo.yaml",
    "ID": "1",
    "DIR": ".",
    "PATH": "x",
    "N": "1",
    "STATUS": "applied",
    "WORD": "python",
    "TEXT": "note",
    "KIND": "manual",
}
_START = re.compile(r"(?:^|&&|;|\|\||\||\s--\s)\s*(?:\$\s+)?(getmeajob\s[^`\n]*)")


def asset_files() -> list[Path]:
    files = [p for p in AGENTS.rglob("*") if p.is_file() and p.name not in SKIP_NAMES]
    return sorted([*files, MARKETPLACE])


def markdown_files() -> list[Path]:
    return [p for p in asset_files() if p.suffix == ".md"]


def frontmatter(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path.name} has no frontmatter"
    head, _, _ = text[4:].partition("\n---\n")
    data = yaml.safe_load(head)
    assert isinstance(data, dict), f"{path.name}: frontmatter is not a mapping"
    return data


def code_spans(text: str) -> list[str]:
    spans: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            spans.append(line)
        else:
            spans += re.findall(r"`([^`\n]+)`", line)
    return spans


def cli_commands(text: str) -> list[str]:
    found: list[str] = []
    for span in code_spans(text):
        for match in _START.finditer(span.split(" #")[0]):
            found.append(re.split(r"\s*(?:&&|;|\|)\s*", match.group(1))[0].strip())
    return found


def _argv(command: str, hint: str) -> list[str]:
    words = shlex.split(command)[1:]
    argv: list[str] = []
    for word in words:
        if word == "$ARGUMENTS":
            first = hint.split()[0] if hint.split() else ""
            if first in PLACEHOLDERS:  # a required argument, like KEY
                argv.append(PLACEHOLDERS[first])
            continue
        if word in ("...", "KEY..."):
            continue
        argv.append(PLACEHOLDERS.get(word, word))
    return argv


def test_the_ten_commands_exist_with_frontmatter() -> None:
    names = {p.stem for p in ASSETS.command_files()}
    assert names == COMMANDS
    for path in ASSETS.command_files():
        data = frontmatter(path)
        description = data.get("description")
        assert isinstance(description, str) and description.strip(), path
        assert set(data) <= {"description", "argument-hint", "disable-model-invocation"}, path
        if "argument-hint" in data:
            assert isinstance(data["argument-hint"], str), path


def test_skill_frontmatter() -> None:
    data = frontmatter(ASSETS.skill_dir / "SKILL.md")
    assert data["name"] == "getmeajob"
    description = data.get("description")
    assert isinstance(description, str) and 50 < len(description) < 1_000


def test_every_cli_command_mentioned_exists() -> None:
    parser, _ = build_parser()
    seen = 0
    for path in markdown_files():
        text = path.read_text(encoding="utf-8")
        hint = ""
        if path.parent == ASSETS.commands_dir:
            hint = str(frontmatter(path).get("argument-hint") or "")
        for command in cli_commands(text):
            seen += 1
            argv = _argv(command, hint)
            where = f"{path.relative_to(REPO)}: `{command}`"
            try:
                parser.parse_args(argv)
            except SystemExit:
                pytest.fail(f"{where} is not a valid command")
            # `plan` takes free words (job keys), so check its sub-command names here.
            if argv[0] == "plan" and len(argv) > 1 and re.fullmatch(r"[a-z]+", argv[1]):
                assert argv[1] in PLAN_WORDS, f"{where}: no `plan {argv[1]}`"
    assert seen > 60  # the check really ran over the assets


def test_manifests_parse_and_point_at_real_paths() -> None:
    plugin = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
    assert plugin["name"] == "getmeajob"
    assert plugin["version"] == __version__
    assert set(plugin) <= {"name", "version", "description", "author", "license", "keywords"}
    market = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    assert market["name"] == "getmeajob"
    assert market["owner"]["name"]
    (entry,) = market["plugins"]
    assert entry["name"] == plugin["name"]
    assert entry["source"].startswith("./") and ".." not in entry["source"]
    root = (REPO / entry["source"]).resolve()
    assert root == ASSETS.plugin_dir.resolve()
    assert (root / ".claude-plugin" / "plugin.json").is_file()
    assert (root / "commands").is_dir() and (root / "skills" / "getmeajob" / "SKILL.md").is_file()


def test_policy_is_linked_from_skill_agents_md_and_every_command() -> None:
    for path in [ASSETS.skill_dir / "SKILL.md", ASSETS.agents_md, *ASSETS.command_files()]:
        assert "POLICY.md" in path.read_text(encoding="utf-8"), path.name
    review = (ASSETS.commands_dir / "review-answers.md").read_text(encoding="utf-8")
    assert "answer-review.md" in review


def test_plugin_copies_match_the_canonical_files() -> None:
    pairs = [
        (ASSETS.policy, ASSETS.skill_dir / "POLICY.md"),
        (AGENTS / "prompts" / "answer-review.md", ASSETS.skill_dir / "answer-review.md"),
    ]
    for canonical, copy in pairs:
        assert copy.read_bytes() == canonical.read_bytes(), f"{copy} differs from {canonical}"


def test_no_forbidden_words_or_long_dashes() -> None:
    for path in asset_files():
        text = path.read_text(encoding="utf-8")
        assert "toolbelt" not in text.casefold(), path
        assert "—" not in text and "–" not in text, f"{path.name} has a long dash"


def test_lists_have_at_most_five_items() -> None:
    item = re.compile(r"^(\s*)(?:[-*]|\d+\.)\s")
    for path in markdown_files():
        run, indent = 0, None
        for line in path.read_text(encoding="utf-8").splitlines():
            match = item.match(line)
            if match and match.group(1) == indent:
                run += 1
            elif match:
                run, indent = 1, match.group(1)
            elif line.startswith(" ") and indent is not None:
                continue  # a nested line inside the current item
            else:
                run, indent = 0, None
            assert run <= 5, f"{path.relative_to(REPO)}: a list has more than five items"


def _git(*args: str) -> str:
    try:
        done = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=False)
    except OSError:
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def test_no_personal_data() -> None:
    for folder in (AGENTS, MARKETPLACE.parent):
        done = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "scan_sensitive.py"), "--path", str(folder)],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode == 0, done.stdout + done.stderr
    # The repository's own identity (whatever it is) never appears in the agent files.
    terms = [_git("config", "user.name"), _git("config", "user.email")]
    origin = re.search(r"github\.com[:/]([^/]+)/", _git("remote", "get-url", "origin"))
    if origin:
        terms.append(origin.group(1))
    terms = [t.casefold() for t in terms if len(t) >= 3]
    for path in asset_files():
        text = path.read_text(encoding="utf-8").casefold()
        for term in terms:
            assert term not in text, f"{path.relative_to(REPO)} names the repository owner"
