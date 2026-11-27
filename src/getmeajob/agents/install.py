"""Find the agent files that ship with getmeajob and install them for Claude Code.

Two ways to install the Claude Code part:
- plugin: print the commands that add this repository as a plugin marketplace and
  install the `getmeajob` plugin (nothing is copied);
- flat: copy each command to `DIR/.claude/commands/getmeajob-<name>.md` and the skill
  to `DIR/.claude/skills/getmeajob/`, with `/getmeajob:<name>` links rewritten to
  `/getmeajob-<name>`.

Existing files are never replaced unless `force` is set.
"""

from __future__ import annotations

import re
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from getmeajob.demo import agents_dir
from getmeajob.errors import GetmeajobError
from getmeajob.files import atomic_write_text
from getmeajob.mcp.config import mcp_installed

PLUGIN_NAME = "getmeajob"
MARKETPLACE_NAME = "getmeajob"
SKILL_NAME = "getmeajob"
FLAT_PREFIX = "getmeajob-"
GITHUB_PLACEHOLDER = "<owner>/getmeajob"
SKIP_NAMES = frozenset({".DS_Store", ".gitkeep", "Thumbs.db"})
_PLUGIN_LINK = re.compile(r"/getmeajob:([a-z][a-z0-9-]*)")


@dataclass(frozen=True)
class Assets:
    """Paths of the agent files (`agents/` in a checkout, `_agents` in a wheel)."""

    root: Path

    @property
    def plugin_dir(self) -> Path:
        return self.root / "claude-plugin"

    @property
    def commands_dir(self) -> Path:
        return self.plugin_dir / "commands"

    @property
    def skill_dir(self) -> Path:
        return self.plugin_dir / "skills" / SKILL_NAME

    @property
    def agents_md(self) -> Path:
        return self.root / "AGENTS.md"

    @property
    def policy(self) -> Path:
        return self.root / "POLICY.md"

    @property
    def answer_review(self) -> Path:
        return self.root / "prompts" / "answer-review.md"

    def command_files(self) -> list[Path]:
        return sorted(p for p in self.commands_dir.glob("*.md") if p.name not in SKIP_NAMES)

    def skill_files(self) -> list[Path]:
        return sorted(
            p for p in self.skill_dir.rglob("*") if p.is_file() and p.name not in SKIP_NAMES
        )

    def marketplace_root(self) -> Path | None:
        """The repository root when it has `.claude-plugin/marketplace.json`, else None."""
        root = self.root.parent
        if (root / ".claude-plugin" / "marketplace.json").is_file():
            return root
        return None


def find_assets() -> Assets:
    assets = Assets(agents_dir())
    if not assets.commands_dir.is_dir() or not (assets.skill_dir / "SKILL.md").is_file():
        raise GetmeajobError(
            f"The Claude Code plugin files are missing from {assets.root}.",
            hint="Reinstall getmeajob, or run it from a full copy of the repository.",
        )
    return assets


def flatten_text(text: str) -> str:
    """Rewrite plugin command links (`/getmeajob:rank`) to flat ones (`/getmeajob-rank`)."""
    return _PLUGIN_LINK.sub(lambda m: f"/{FLAT_PREFIX}{m.group(1)}", text)


def flat_targets(assets: Assets, project: Path) -> list[tuple[Path, Path]]:
    """(source, target) pairs for a flat install into `project`."""
    claude = project / ".claude"
    pairs = [
        (path, claude / "commands" / f"{FLAT_PREFIX}{path.stem}.md")
        for path in assets.command_files()
    ]
    for path in assets.skill_files():
        pairs.append((path, claude / "skills" / SKILL_NAME / path.relative_to(assets.skill_dir)))
    return pairs


def install_flat(assets: Assets, project: Path, *, force: bool = False) -> list[Path]:
    """Copy the commands and the skill into `project/.claude/`. Returns the files written."""
    if not project.is_dir():
        raise GetmeajobError(
            f"The folder {project} does not exist.",
            hint="Pass the folder of the project where you use Claude Code.",
        )
    pairs = flat_targets(assets, project)
    existing = [target for _, target in pairs if target.exists()]
    if existing and not force:
        shown = ", ".join(str(t.relative_to(project)) for t in existing[:3])
        more = f" and {len(existing) - 3} more" if len(existing) > 3 else ""
        raise GetmeajobError(
            f"{len(existing)} file(s) are already there: {shown}{more}. Nothing was copied.",
            hint="Add --force to replace them.",
        )
    written: list[Path] = []
    for source, target in pairs:
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix == ".md":
            atomic_write_text(target, flatten_text(source.read_text(encoding="utf-8")))
        else:
            shutil.copyfile(source, target)
        written.append(target)
    return written


def plugin_commands(assets: Assets) -> list[str]:
    """The two shell commands that add the marketplace and install the plugin."""
    root = assets.marketplace_root()
    source = shlex.quote(str(root)) if root is not None else GITHUB_PLACEHOLDER
    return [
        f"claude plugin marketplace add {source}",
        f"claude plugin install {PLUGIN_NAME}@{MARKETPLACE_NAME} --scope project",
    ]


def available(assets: Assets) -> list[dict[str, Any]]:
    """What `getmeajob agents list` shows: each installable piece and how to install it."""
    commands = [p.stem for p in assets.command_files()]
    mcp_note = "" if mcp_installed() else ' (first: pip install "getmeajob[mcp]")'
    return [
        {
            "name": "claude-plugin",
            "what": f"Claude Code plugin: {len(commands)} slash commands and the "
            f"{SKILL_NAME} skill",
            "install": "getmeajob agents install --claude DIR",
            "path": str(assets.plugin_dir),
        },
        {
            "name": "claude-flat",
            "what": "the same commands and skill as plain files in DIR/.claude/",
            "install": "getmeajob agents install --claude DIR --flat",
            "path": str(assets.plugin_dir),
        },
        {
            "name": "mcp-server",
            "what": "MCP server over stdio with getmeajob_ tools (none fills a form)",
            "install": f"getmeajob mcp config{mcp_note}",
            "path": "",
        },
        {
            "name": "agents-md",
            "what": "workflow for Codex CLI, Cursor and other agents",
            "install": "point your agent at this file",
            "path": str(assets.agents_md),
        },
        {
            "name": "policy",
            "what": "truthfulness rules every agent follows",
            "install": "read by the skill, AGENTS.md and every command",
            "path": str(assets.policy),
        },
    ]
