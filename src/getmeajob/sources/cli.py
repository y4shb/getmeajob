"""Commands for this package. This stub adds none; its owner replaces it.

Contract (see getmeajob/cli.py): `register(sub)` adds parsers with
`sub.add_parser(name, help=...)` and calls `set_defaults(func=handler)`, where
`handler(args: argparse.Namespace, ctx: getmeajob.cli.Context) -> int`.
Do not add --json, --quiet or --home here: they are global and already accepted
after the command name. Call `ctx.ws.require()` before reading the workspace.
"""

from __future__ import annotations

import argparse


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add this package's commands (none yet)."""
