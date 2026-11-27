"""`getmeajob mcp`: run the MCP server over stdio, or print client config.

getmeajob mcp                     run the server (an MCP client starts this for you)
getmeajob mcp config              snippets for Claude Desktop, Claude Code and Codex CLI
getmeajob mcp config --client codex

The workspace comes from --home or GETMEAJOB_HOME. The server needs the optional
extra: pip install -e ".[mcp]".
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from getmeajob.mcp.config import CLIENTS, config_lines, mcp_installed, snippets

if TYPE_CHECKING:
    from getmeajob.cli import Context


def _cmd_serve(args: argparse.Namespace, ctx: Context) -> int:
    from getmeajob.mcp.server import serve

    if sys.stdin.isatty():
        sys.stderr.write(
            f"getmeajob MCP server on stdio, workspace {ctx.ws.root}. It waits for an MCP "
            "client; press Ctrl+C to stop. To connect a client: getmeajob mcp config\n"
        )
    serve(ctx.ws)
    return 0


def _cmd_config(args: argparse.Namespace, ctx: Context) -> int:
    data = snippets(ctx.ws.root)
    if ctx.out.json_mode:
        ctx.out.emit(
            {**data, "workspace_exists": ctx.ws.exists(), "mcp_installed": mcp_installed()}
        )
        return 0
    for line in config_lines(data, args.client):
        ctx.out.line(line)
    if not ctx.ws.exists():
        ctx.out.line("")
        ctx.out.line(
            f"note: there is no workspace at {ctx.ws.root} yet. Run `getmeajob init` "
            "first, or pass --home PATH."
        )
    if not mcp_installed():
        ctx.out.line('note: the mcp package is missing. Install it: pip install -e ".[mcp]"')
    return 0


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser(
        "mcp",
        help="the MCP server for agents (stdio); `mcp config` prints client setup",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.set_defaults(func=_cmd_serve)
    actions = parser.add_subparsers(dest="mcp_command", metavar="ACTION")
    serve = actions.add_parser("serve", help="run the server over stdio (the default)")
    serve.set_defaults(func=_cmd_serve)
    config = actions.add_parser(
        "config", help="print config snippets for Claude Desktop, Claude Code and Codex CLI"
    )
    config.add_argument(
        "--client", choices=("all", *CLIENTS), default="all", help="one client only"
    )
    config.set_defaults(func=_cmd_config)
