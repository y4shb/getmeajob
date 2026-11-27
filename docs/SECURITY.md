# Security and privacy

In short: report a security problem privately through a GitHub security advisory, and report other bugs as GitHub issues with no personal data in them. getmeajob keeps your data in one gitignored folder on your machine. It contacts only the job boards and pages you configure, plus an AI provider when you run drafting yourself.

## Reporting a problem

1. A security problem, such as job text that makes getmeajob submit a form or leak a file: report it privately. On the repository's GitHub page, open Security, then "Report a vulnerability". This creates a private security advisory that only the maintainers see.
2. If that button is missing, open an issue that only says you found a security problem and asks for a private way to send the details.
3. Any other bug: open a GitHub issue. Reproduce it with the demo workspace (`getmeajob init --demo`) when you can.
4. Include the output of `getmeajob --version`, your Python version and operating system, the command you ran, and the `error:` and `hint:` lines.
5. Leave out personal data: no real names, email addresses, phone numbers, profiles, answers files, resumes, trackers or screenshots of filled forms.

## What getmeajob stores, and where

Everything lives in the workspace folder: `./workspace` by default, or the folder given by `--home` or `GETMEAJOB_HOME`. The repo's `.gitignore` keeps it out of git, and `getmeajob init` also writes a `.gitignore` containing `*` inside the workspace.

1. Your facts: `profile.yaml`, `answers.yaml`, `resume/bank.yaml` and your resume PDFs.
2. Job data: jobs, job texts, rankings, form questions and plans under `data/`. Plans hold your answers.
3. Logs: the apply ledger, status events, the queue and notes. The ledger keeps a digest of your answers and the plan path, never the answer text. Notes in the ledger and the queue show answer values of 4 or more characters as `[answer]`.
4. Pictures and exports: screenshots of filled forms in `shots/` and the trackers in `exports/`. Both show your answers or your search, so treat them as personal.
5. Caches: board replies in `cache/http/` and AI drafts in `cache/llm/`.

Files that getmeajob writes in one step, such as `data/jobs.jsonl` and the plans, are created readable only by your user account (mode 0600). Copied templates and the append-only logs keep your usual file permissions.

## What leaves your machine

1. Requests to the job board APIs of the boards in `companies.yaml`, and to the job and form pages of the jobs you plan or apply to.
2. Feed requests, only for the feeds you name with `--feeds`.
3. Requests to the careers pages and board APIs for the companies in the file you give `getmeajob discover`. Your company list is never sent to a lookup service.
4. A filled application, only when you click Submit or a submit mode you switched on clicks it.
5. AI drafting, only when you run `getmeajob plan draft`. The prompt holds the question, the job title and company, the start of the job text and a few profile facts. It goes to Anthropic or to the command in `GETMEAJOB_LLM_COMMAND`.

getmeajob sends no usage data. The demo workspace sends nothing at all: board replies come from recorded files, and the browser blocks every request that is not a local file.

## The privacy scanner

`scripts/scan_sensitive.py` looks for email addresses, phone numbers, personal URLs, API keys, home-folder paths, large files and the terms on your private denylist. It uses only the Python standard library, and exits 0 when clean, 1 with findings and 2 on a usage error.

Run it in one of these modes:

1. `python scripts/scan_sensitive.py --tree` checks tracked files and untracked files that are not ignored.
2. `python scripts/scan_sensitive.py --history` checks every blob, commit message, author and ref in the git history. With no mode flag, the scanner runs `--tree --history`.
3. `python scripts/scan_sensitive.py --staged` checks what you are about to commit, plus your git identity.
4. `python scripts/scan_sensitive.py --path DIR` checks a folder without git.

Private lists stay outside the repo:

1. `GETMEAJOB_DENYLIST` (or `--denylist FILE`) names a file of private terms, one per line. A finding never prints the term; it shows two characters and the length.
2. `GETMEAJOB_ALLOW` names a private file of allow rules, for allowances that would reveal a private term.
3. `.scan-allow` in the repo root holds generic allow rules. A line that contains the marker `scan:allow` is skipped.

Where it runs:

1. Before each commit, after `bash scripts/install-git-hooks.sh`. The hook runs `--staged`, and also checks your denylist when `GETMEAJOB_DENYLIST` is set. If you use the pre-commit tool instead, `.pre-commit-config.yaml` runs the same check.
2. In CI, as `--tree --history --skip-identity`, with the generic patterns only. CI has no denylist.

## Prompt injection

Job text, form labels and page text come from employers and strangers. getmeajob treats them as data, never as instructions.

1. The scripts never act on text they read. Answers come only from your profile and saved answers, and rules match on labels.
2. Zero-width and bidirectional control characters are removed from job text and form labels when they are stored.
3. The drafting prompt wraps job and question text in tags and tells the model to treat it as data. Every draft still needs your review.
4. The MCP server has no tool that fills or submits a form, so an agent cannot apply through it.
5. Agents follow `agents/POLICY.md`: never invent facts, leave gaps as gaps, stop and ask, and treat page text as data. An agent that meets instructions inside job text should stop and tell you.

## Secrets

1. The only vendor environment variable name in the repo is `ANTHROPIC_API_KEY`, the Anthropic SDK's standard key variable. The SDK reads it, and getmeajob never stores it.
2. getmeajob's own settings use the `GETMEAJOB_` prefix: `GETMEAJOB_HOME`, `GETMEAJOB_FIXTURES`, `GETMEAJOB_LLM_COMMAND`, `GETMEAJOB_DENYLIST` and `GETMEAJOB_ALLOW`.
3. Never commit a `.env` file. `.gitignore` covers `.env` and `.env.*`, and the scanner's key rule catches common key formats.
