"""`getmeajob agents list` and `getmeajob agents install --claude DIR [--flat] [--force]`.

getmeajob agents list                          what can be installed, and how
getmeajob agents install --claude DIR          print the commands that install the plugin
getmeajob agents install --claude DIR --flat   copy commands and skill into DIR/.claude/

Neither command needs a workspace.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING

from getmeajob.agents.install import (
    available,
    find_assets,
    install_flat,
    plugin_commands,
)

if TYPE_CHECKING:
    from getmeajob.cli import Context


def _cmd_list(args: argparse.Namespace, ctx: Context) -> int:
    assets = find_assets()
    items = available(assets)
    if ctx.out.json_mode:
        ctx.out.emit({"agents_dir": str(assets.root), "items": items})
        return 0
    ctx.out.table(items, ["name", "what", "install"], max_col=0)
    ctx.out.done(
        f"Files: {assets.root}",
        next_step="getmeajob agents install --claude .   (in your project folder)",
    )
    return 0


def _cmd_install(args: argparse.Namespace, ctx: Context) -> int:
    assets = find_assets()
    project = Path(args.claude).expanduser().resolve()
    out = ctx.out
    if args.flat:
        written = install_flat(assets, project, force=bool(args.force))
        if out.json_mode:
            out.emit({"mode": "flat", "project": str(project), "files": [str(p) for p in written]})
            return 0
        copied = sum(1 for p in written if p.parent.name == "commands")
        out.done(
            f"Copied {copied} commands to .claude/commands/ and the skill "
            f"({len(written) - copied} files) to .claude/skills/getmeajob/ in {project}.",
            next_step="type /getmeajob-status in Claude Code",
        )
        return 0
    commands = plugin_commands(assets)
    if out.json_mode:
        out.emit({"mode": "plugin", "project": str(project), "commands": commands})
        return 0
    out.line(f"Run these two commands in {project}:")
    for command in commands:
        out.line(f"  {command}")
    if assets.marketplace_root() is None:
        out.line("Replace <owner> with the GitHub account that hosts getmeajob.")
    out.line("Inside Claude Code you can type them as /plugin marketplace add and /plugin install.")
    out.done(
        "Without a plugin: add --flat to copy the files into .claude/ instead.",
        next_step="type /getmeajob:status in Claude Code",
    )
    return 0


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser(
        "agents",
        help="install the Claude Code plugin, or list the agent files",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    actions = parser.add_subparsers(dest="agents_command", metavar="ACTION", required=True)

    listing = actions.add_parser("list", help="what can be installed, and how")
    listing.set_defaults(func=_cmd_list)

    install = actions.add_parser(
        "install",
        help="install the Claude Code commands and skill",
        description="Print the plugin install commands, or with --flat copy the commands "
        "and the skill into DIR/.claude/. Existing files are kept unless you add --force.",
    )
    install.add_argument(
        "--claude", metavar="DIR", required=True, help="the project folder that uses Claude Code"
    )
    install.add_argument(
        "--flat",
        action="store_true",
        help="copy commands as .claude/commands/getmeajob-<name>.md and the skill",
    )
    install.add_argument("--force", action="store_true", help="replace files that already exist")
    install.set_defaults(func=_cmd_install)
