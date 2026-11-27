"""Ready-to-paste MCP client config for `getmeajob mcp config`.

Every snippet starts the server with this Python (`python -m getmeajob mcp`), so the
client finds getmeajob even when the virtual environment is not on its PATH, and sets
GETMEAJOB_HOME to the workspace. Only stdio clients are covered: getmeajob never runs a
network server, because that would expose the workspace.
"""

from __future__ import annotations

import importlib.util
import json
import shlex
import sys
from pathlib import Path
from typing import Any

CLIENTS = ("claude-desktop", "claude-code", "codex")
SERVER_ARGS = ["-m", "getmeajob", "mcp"]

DESKTOP_FILES = (
    "macOS: ~/Library/Application Support/Claude/claude_desktop_config.json; "
    "Windows: %APPDATA%\\Claude\\claude_desktop_config.json"
)
CHATGPT_NOTE = (
    "ChatGPT: the ChatGPT apps connect only to remote MCP servers over HTTPS "
    "(developer mode on the web, on some plans). getmeajob's server runs only on this "
    "computer over stdio and is never put on the network, because that would expose your "
    "workspace. Use a local agent instead, such as Codex CLI with agents/AGENTS.md."
)


def mcp_installed() -> bool:
    """True when the optional `mcp` package can be imported."""
    return importlib.util.find_spec("mcp") is not None


def _toml(value: str) -> str:
    return json.dumps(value)  # a TOML basic string uses the same escapes for paths


def desktop_config(python: str, home: Path) -> dict[str, Any]:
    return {
        "mcpServers": {
            "getmeajob": {
                "command": python,
                "args": SERVER_ARGS,
                "env": {"GETMEAJOB_HOME": str(home)},
            }
        }
    }


def claude_code_command(python: str, home: Path) -> str:
    env = shlex.quote(f"GETMEAJOB_HOME={home}")
    command = " ".join(shlex.quote(part) for part in [python, *SERVER_ARGS])
    return f"claude mcp add getmeajob -e {env} -- {command}"


def codex_toml(python: str, home: Path) -> str:
    args = ", ".join(_toml(a) for a in SERVER_ARGS)
    return "\n".join(
        [
            "[mcp_servers.getmeajob]",
            f"command = {_toml(python)}",
            f"args = [{args}]",
            "tool_timeout_sec = 300",
            "",
            "[mcp_servers.getmeajob.env]",
            f"GETMEAJOB_HOME = {_toml(str(home))}",
        ]
    )


def snippets(home: Path, python: str | None = None) -> dict[str, Any]:
    """Everything `mcp config` prints, as plain data."""
    exe = python or sys.executable
    return {
        "workspace": str(home),
        "command": [exe, *SERVER_ARGS],
        "claude-desktop": desktop_config(exe, home),
        "claude-code": claude_code_command(exe, home),
        "codex": codex_toml(exe, home),
        "chatgpt": CHATGPT_NOTE,
    }


def config_lines(data: dict[str, Any], client: str = "all") -> list[str]:
    """The human screen for one client, or for all of them."""
    blocks: list[list[str]] = []
    if client in ("all", "claude-desktop"):
        blocks.append(
            [
                f"Claude Desktop: add this to claude_desktop_config.json ({DESKTOP_FILES}),"
                " then restart the app.",
                json.dumps(data["claude-desktop"], indent=2),
            ]
        )
    if client in ("all", "claude-code"):
        blocks.append(
            [
                "Claude Code: run this in your project folder (add --scope user for every "
                "project).",
                data["claude-code"],
            ]
        )
    if client in ("all", "codex"):
        blocks.append(["Codex CLI: add this to ~/.codex/config.toml.", data["codex"]])
    if client == "all":
        blocks.append([data["chatgpt"]])
    lines: list[str] = []
    for block in blocks:
        if lines:
            lines.append("")
        lines += block
    return lines
