"""The `getmeajob` command line.

Each package owns its commands in `getmeajob/<pkg>/cli.py`, which exposes
`register(sub)`. `register` adds parsers with `sub.add_parser(...)` and sets
`func=handler`, where `handler(args, ctx) -> int` returns the exit code.

`--home`, `--json` and `-q/--quiet` are global and work before or after the command
name (`getmeajob --json source` and `getmeajob source --json` are the same). Do not add
them again in a command; argparse will refuse the duplicate.
"""

from __future__ import annotations

import argparse
import functools
import importlib
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from getmeajob import __version__
from getmeajob.errors import GetmeajobError
from getmeajob.output import Output
from getmeajob.settings import Settings, load_settings
from getmeajob.workspace import Workspace

COMMAND_MODULES = [
    "getmeajob.demo",
    "getmeajob.sources.cli",
    "getmeajob.rank.cli",
    "getmeajob.plan.cli",
    "getmeajob.apply.cli",
    "getmeajob.queue.cli",
    "getmeajob.report.cli",
    "getmeajob.track.cli",
    "getmeajob.resume.cli",
    "getmeajob.agents.cli",
    "getmeajob.mcp.cli",
    "getmeajob.tokens.cli",
]

# argparse has no public name for the object `add_subparsers()` returns.
SubParsers = argparse._SubParsersAction


@dataclass
class Context:
    ws: Workspace
    out: Output
    settings_loader: Callable[[], Settings]


def _add_global_options(parser: argparse.ArgumentParser, *, suppress: bool) -> None:
    default: Any = argparse.SUPPRESS if suppress else None
    parser.add_argument(
        "--home",
        metavar="PATH",
        default=default,
        help="workspace folder (default: GETMEAJOB_HOME, else ./workspace)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS if suppress else False,
        help="machine-readable JSON output",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=argparse.SUPPRESS if suppress else False,
        help="print nothing except errors and warnings",
    )


class CommandParser(argparse.ArgumentParser):
    """Parser for commands and sub-commands; accepts the global options too."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        _add_global_options(self, suppress=True)


def build_parser() -> tuple[argparse.ArgumentParser, SubParsers[argparse.ArgumentParser]]:
    parser = argparse.ArgumentParser(
        prog="getmeajob",
        description="A job hunt as a pipeline of plain scripts that agents can drive.",
    )
    _add_global_options(parser, suppress=False)
    parser.add_argument("--version", action="version", version=f"getmeajob {__version__}")
    sub = cast(
        "SubParsers[argparse.ArgumentParser]",
        parser.add_subparsers(dest="command", metavar="COMMAND", parser_class=CommandParser),
    )
    for name in COMMAND_MODULES:
        module = importlib.import_module(name)
        module.register(sub)
    return parser, sub


def short_help(sub: SubParsers[argparse.ArgumentParser]) -> str:
    lines = ["usage: getmeajob [--home PATH] [--json] [-q] COMMAND [options]", "", "commands:"]
    for action in sub._choices_actions:
        name = action.metavar or action.dest
        lines.append(f"  {str(name):<16} {action.help or ''}".rstrip())
    lines += [
        "",
        "New here? Try: getmeajob init --demo   (sample data, no network needed)",
        "Help for one command: getmeajob COMMAND --help",
    ]
    return "\n".join(lines)


def _exit_code(code: object) -> int:
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    return 2


def _print_error(exc: GetmeajobError) -> None:
    sys.stderr.write(f"error: {exc.message}\n")
    if exc.hint:
        sys.stderr.write(f"hint: {exc.hint}\n")


def main(argv: list[str] | None = None) -> int:
    """Run the CLI. Returns the exit code (0 ok, 2 user error, 130 interrupted)."""
    try:
        parser, sub = build_parser()
        try:
            args = parser.parse_args(list(argv) if argv is not None else None)
        except SystemExit as exc:  # --help, --version and usage errors
            return _exit_code(exc.code)
        handler = getattr(args, "func", None)
        if handler is None:
            print(short_help(sub))
            return 0
        ws = Workspace.resolve(args.home)
        out = Output(json_mode=bool(args.json), quiet=bool(args.quiet))
        loader = functools.cache(lambda: load_settings(ws))
        ctx = Context(ws=ws, out=out, settings_loader=loader)
        return int(handler(args, ctx) or 0)
    except GetmeajobError as exc:
        _print_error(exc)
        return 2
    except KeyboardInterrupt:
        sys.stderr.write("interrupted\n")
        return 130
    except BrokenPipeError:
        # Output was piped into a command that stopped reading (for example `head`).
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        return 0
    except OSError as exc:
        where = f" {exc.filename}" if exc.filename else ""
        sys.stderr.write(f"error: could not read or write{where}: {exc.strerror or exc}\n")
        sys.stderr.write("hint: check that the folder exists and that you may write to it.\n")
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
