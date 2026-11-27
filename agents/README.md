# Agent files

Pick your agent, then follow its steps below. Run `getmeajob agents list` to see the same list from the command line.

## What is in this folder

| Path | What it is |
|---|---|
| `claude-plugin/` | The Claude Code plugin `getmeajob`: ten slash commands and one skill |
| `AGENTS.md` | The workflow for Codex CLI, Cursor and any other agent |
| `POLICY.md` | The truthfulness rules every agent follows |
| `prompts/answer-review.md` | How an agent reviews form answers with the user |

The plugin's skill folder carries its own copies of `POLICY.md` and `answer-review.md`, because a plugin can only use files inside its own folder. A test keeps the copies identical.

## Claude Code: the plugin

1. Run `getmeajob agents install --claude .` in the project where you want it. It prints two commands.
2. Run them. The first adds this repository as a plugin marketplace; the second installs the plugin for that project.
3. Type `/getmeajob:status` in Claude Code to check it works.

The commands are `/getmeajob:source`, `/getmeajob:rank`, `/getmeajob:plan`, `/getmeajob:review-answers`, `/getmeajob:apply-dry`, `/getmeajob:hold-run`, `/getmeajob:queue`, `/getmeajob:status`, `/getmeajob:tracker` and `/getmeajob:resume`.

## Claude Code: plain copies, no plugin

1. Run `getmeajob agents install --claude . --flat`.
2. It copies each command to `.claude/commands/getmeajob-<name>.md` and the skill to `.claude/skills/getmeajob/`.
3. The commands are then `/getmeajob-status`, `/getmeajob-rank` and so on.

It never replaces a file that is already there. Add `--force` to replace them.

## The MCP server

1. Install the extra: `pip install "getmeajob[mcp]"`.
2. Run `getmeajob mcp config`. It prints snippets for Claude Desktop, Claude Code and Codex CLI with your workspace path filled in.
3. Paste the one for your client. The client starts the server itself with `getmeajob mcp`.

The server talks over stdio only and never opens a network port. It has no tool that fills or submits a form.

## Codex, Cursor, ChatGPT and others

Point the agent at `AGENTS.md` and `POLICY.md`. `AGENTS.md` ends with the steps for each kind of agent, including why ChatGPT cannot use the local server.
