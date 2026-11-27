# Spec

In short: this file says what getmeajob does, as plain statements you can check.
Each row has an ID, a status (`planned`, `in progress` or `shipped`) and one behaviour.

Last updated: 2026-11-27, after wave 1 (core, sources, ranking, resumes and answer planning shipped).

How to read it:

1. Find your area below. Its commands come first.
2. Read the rows. `planned` means not built yet, `in progress` means being built now, `shipped` means done and in the repo.
3. Use the ID (for example `SRC-2`) to find the tests for a row in `docs/TESTS.md`.

A docs agent updates the statuses after each milestone. Reasons for these choices live in `docs/DECISIONS.md`.

## Setup and workspace

Commands:

```
getmeajob init [--demo] [--force]
```

Global options: `--home PATH`, `--json`, `-q/--quiet`, `--version`. `python -m getmeajob` runs the same CLI.

| ID | Status | Behaviour |
|---|---|---|
| SET-1 | shipped | The package installs one command, `getmeajob`. It needs Python 3.11 or newer, and CI runs on 3.11 and 3.12. |
| SET-2 | shipped | The workspace is `./workspace` by default. `GETMEAJOB_HOME` overrides the default, and `--home` overrides both. |
| SET-3 | shipped | `getmeajob init` copies the commented example files into the workspace as `profile.yaml`, `preferences.yaml`, `answers.yaml` and `companies.yaml`. |
| SET-4 | shipped | `getmeajob init --demo` fills the workspace with a synthetic candidate, switches sourcing to offline fixtures, and writes a one-page demo resume at `resume/base.pdf`. |
| SET-5 | shipped | `getmeajob init` does not overwrite an existing workspace unless you pass `--force`. |
| SET-6 | shipped | Any command run before `getmeajob init` prints a plain message that points to `getmeajob init`, exits with code 2, and shows no traceback. |
| SET-7 | shipped | A user error prints an `error:` line and a `hint:` line to stderr and exits with code 2. Ctrl+C exits with code 130. |
| SET-8 | shipped | `getmeajob` with no command prints a short list of commands. |
| SET-9 | shipped | `--json` switches a command to JSON output. |
| SET-10 | in progress | Without `--json`, each command prints a compact table of about 40 lines or fewer. Commands with lists that can grow take `--limit`. |
| SET-11 | shipped | All data is JSON and JSONL files in the workspace. Each write goes to a temp file first, then replaces the old file. The apply ledger, status events and queue are append-only. |
| SET-12 | shipped | A job key is `<ats>:<board>:<job_id>`. In file names, `:` becomes `__`, other unsafe characters become `_`, and names over 150 characters are cut and given a short hash. |
| SET-13 | shipped | A broken line in a JSONL file gives an error that names the file and the line number. |
| SET-14 | planned | `bash scripts/quickstart.sh` runs the README quick start on the demo workspace, in dry mode, with no network. |

## Sourcing

Commands:

```
getmeajob source [--board ats:slug] [--company NAME] [--feeds remotive,remoteok,hn] [--limit N]
getmeajob boards
getmeajob discover FILE [--write]
getmeajob import-portals FILE [--write]
getmeajob check-live [KEY...]
getmeajob jd KEY [--grep RE] [--full]
```

| ID | Status | Behaviour |
|---|---|---|
| SRC-1 | shipped | `getmeajob source` fetches the enabled boards in `companies.yaml`, saves jobs to `data/jobs.jsonl` and job text to `data/jd/<key>.txt`, and writes a run summary to `data/runs/`. |
| SRC-2 | shipped | `getmeajob source` prints only new, changed and closed jobs, with counts. |
| SRC-3 | shipped | Running `getmeajob source` twice adds no duplicate jobs, and the second run prints an empty diff. |
| SRC-4 | shipped | A new job gets a `discovered` status event. A job that disappears from its board is marked closed and gets a `closed` event. A closed job that comes back is reopened to `discovered`. |
| SRC-5 | shipped | Saving a job again keeps its first-seen date and updates its last-seen date. A job counts as changed when its title, location, URL or description changes. |
| SRC-6 | shipped | Board sources: Greenhouse, Ashby, Lever, SmartRecruiters, Workable and Recruitee. Other packages can add sources through the `getmeajob.sources` entry-point group. |
| SRC-7 | shipped | The feeds (Remotive, RemoteOK, HN Who is hiring) run only when you pass `--feeds`. They cache for 6 hours, keep each feed's attribution rule, and pull ATS board slugs out of job links. |
| SRC-8 | shipped | Greenhouse falls back to the job list without full text when the full request times out. Ashby skips unlisted jobs and joins secondary locations. Lever tries the EU host after a 404 when no region is set. |
| SRC-9 | shipped | Messy payloads (null or "None" ids, missing fields, a location given as a list, double-escaped HTML, invisible Unicode) do not crash a run. The job is skipped or degraded, and the reason is recorded. |
| SRC-10 | shipped | Job text is stored as plain text, capped at 20,000 characters. Listings are cached for 6 hours and discovery results for 7 days. |
| SRC-11 | shipped | `getmeajob discover FILE` reads the ATS and slug straight from board URLs, scans careers pages for ATS signs (respecting robots.txt), and tries up to 8 slug guesses per company name. |
| SRC-12 | shipped | Discovery accepts a board only if it has jobs and its name matches the company (similarity 0.7 or more, or one name contains the other). A board with no name is kept as `verified: false`. |
| SRC-13 | shipped | `getmeajob discover` changes `companies.yaml` only with `--write`. It never sends your company list to a third-party lookup service. |
| SRC-14 | shipped | `getmeajob import-portals FILE` turns a `portals.yml` file into boards and preferences. It honours `enabled`, lists unsupported entries with a reason, and supports `word:`, `stem:` and ` + ` (all of) title filters. |
| SRC-15 | shipped | `getmeajob check-live` marks a job closed only on clear evidence: gone from its board, a 404 or 410, or closed-page text. A 403, 406, 429 or network error gives `unknown`. |
| SRC-16 | shipped | `getmeajob jd KEY` prints a digest of at most 12 lines. `--grep RE` searches the text. `--full` prints the text, capped. |
| SRC-17 | shipped | `getmeajob boards` lists the boards in `companies.yaml`. |

Network rules for every command that goes online:

| ID | Status | Behaviour |
|---|---|---|
| SRC-18 | shipped | Every request goes through one client with a 10 s connect timeout, a 25 s read timeout and the user agent `getmeajob/<version>`. |
| SRC-19 | shipped | The client retries 429, 5xx and timeouts up to 3 times with backoff and jitter, honours `Retry-After` (up to 60 s), and never retries 404 or 410. |
| SRC-20 | shipped | The client waits at least 1 second between requests to the same host and runs at most 4 requests at once. |
| SRC-21 | shipped | The client stops at once on a bot wall (a challenge page, or the `cf-mitigated: challenge` header) and does not retry. |
| SRC-22 | shipped | For HTML pages the client reads robots.txt and refuses pages it disallows. JSON APIs skip this check. A missing robots.txt allows the page. |
| SRC-23 | shipped | Responses are cached on disk. After the cache time runs out, the client revalidates with ETag or Last-Modified. |
| SRC-24 | shipped | With `GETMEAJOB_FIXTURES` set (or `fixtures` in `settings.yaml`), the client replays recorded files and makes no network calls. A missing fixture gives an error naming the URL and the places it looked. |
| SRC-25 | shipped | HTML becomes clean text: double-escaped entities are decoded, scripts and styles are dropped, list items start with "- ", and invisible characters (zero-width, bidi controls, BOM) are stripped. |
| SRC-26 | shipped | A job from a feed is never marked closed when it drops out of the feed. Only boards close jobs. |
| SRC-27 | shipped | `getmeajob source` exits 1 only when every board failed. Partial failures exit 0 and list the problems. |

## Ranking

Commands:

```
getmeajob rank [--min-score N] [--limit N] [--all]
getmeajob explain KEY
```

| ID | Status | Behaviour |
|---|---|---|
| RANK-1 | shipped | `getmeajob rank` scores each job from 0 to 100, writes `data/ranked.jsonl`, and prints a compact table. |
| RANK-2 | shipped | Each reason and each flag is one short line a person can read. |
| RANK-3 | shipped | A hard flag makes a job ineligible whatever its score. Flag codes: `too_senior`, `title_excluded`, `off_track`, `region_restricted`, `no_sponsorship`, `clearance_required`, `citizenship_required`, `company_excluded`. |
| RANK-4 | shipped | Every list, weight and threshold comes from `preferences.yaml`. No home city or country is built into the code. |
| RANK-5 | shipped | The years parser reads "3-5", "3 to 5", "between 3 and 5", "5+", "at least five" and "7 yrs". It ignores company-age phrases such as "founded 20 years ago", and a required figure beats a preferred one. |
| RANK-6 | shipped | Region locks ("US only", "must be based in", "authorized to work in the US"), no-sponsorship wording, clearance and citizenship rules become flags with reasons. |
| RANK-7 | shipped | Location tiers come from preferences, for example remote worldwide, remote in the home country, or hybrid in the home city. |
| RANK-8 | shipped | Skill matching respects word boundaries: "go to market" does not count as the Go language. |
| RANK-9 | shipped | Eligible jobs at or above `thresholds.shortlist` get a `shortlisted` status event. |
| RANK-10 | shipped | The eight demo jobs get the eligibility set in the demo data: four eligible and four ineligible, each for its stated reason. |
| RANK-11 | shipped | `getmeajob explain KEY` explains one job's score and flags. |

## Planning answers

Commands:

```
getmeajob plan [KEY...] [--refresh] [--min-score N]
getmeajob plan show KEY
getmeajob plan unknowns [--stub FILE]
getmeajob plan answer FILE
getmeajob plan review [KEY...]
getmeajob plan draft [--budget N] [--provider anthropic|command] [KEY...]
getmeajob plan approve KEY
```

| ID | Status | Behaviour |
|---|---|---|
| ANS-1 | shipped | `getmeajob plan` reads each form's questions and caches them for 24 hours in `data/schemas/`. Greenhouse uses its questions API. Ashby uses the same no-login request its public job page makes (at most 1 per second), with a Chromium read of the page as the fallback. |
| ANS-2 | shipped | By default it plans eligible ranked jobs that have a Greenhouse or Ashby form and score at or above the shortlist threshold. Each plan is saved to `data/plans/<key>.json` and records `planned` or `ready` status events. |
| ANS-3 | shipped | Answers come only from `profile.yaml` and `answers.yaml`. A missing profile field makes the question unknown. |
| ANS-4 | shipped | `answers.yaml` wins over the rules, in this order: per job, per company, global. Values are checked against the form's options. |
| ANS-5 | shipped | Each plan has a status: `ready`, `needs_answers`, `schema_unavailable` or `blocked`. A required unknown makes it `needs_answers`. An optional unknown is skipped. |
| ANS-6 | shipped | Consent questions are answered only when the profile sets `consent.privacy_notice: true`. Questions about AI or automation use are never answered automatically. |
| ANS-7 | shipped | A form that says not to use automated tools blocks the plan with the reason `automation_refused`. |
| ANS-8 | shipped | EEO and demographic questions get the decline option when the profile leaves them unset. |
| ANS-9 | shipped | The option matcher never falls back to the first option. When the match is unclear (for example "Yes, I will require sponsorship" and "Yes, I have sponsorship") it returns no match with a reason. |
| ANS-10 | shipped | Rules do not over-match: "expected graduation" is not a pay question, "open source" is not "how did you hear about us", and "certifications" is not consent. |
| ANS-11 | shipped | Running `getmeajob plan` twice reuses the saved plan when the questions, profile and answers have not changed. |
| ANS-12 | shipped | `getmeajob plan unknowns` lists each unknown question once across all jobs (same label and options). `--stub FILE` writes a YAML file to fill in, and `getmeajob plan answer FILE` merges it into `answers.yaml`. |
| ANS-13 | shipped | `getmeajob plan review` prints one table of labels and answers, each label once, plus the unknowns. |
| ANS-14 | shipped | A plan with required unknowns adds a `needs_answers` queue item. The item resolves itself once the answers are in. |
| ANS-15 | shipped | `getmeajob plan draft` drafts free-text questions only. It never drafts legal, pay, EEO, sponsorship, years, dates or contact questions. |
| ANS-16 | shipped | Drafting stops at the token budget, reuses cached drafts by prompt hash, and marks every draft `needs_review`. `getmeajob plan approve KEY` clears that mark after you read the drafts. |
| ANS-17 | shipped | Draft providers: `anthropic` (optional extra, default model `claude-sonnet-5-5`, called with server-side fallback on and low effort) and `command`, which pipes the prompt to the CLI set in `GETMEAJOB_LLM_COMMAND`. |
| ANS-18 | shipped | Messy question data (missing fields, double-escaped HTML, invisible Unicode) does not crash the planner. The question is skipped or degraded with a recorded reason. |
| ANS-19 | shipped | `getmeajob plan show KEY` prints one job's plan. |

## Applying

Commands:

```
getmeajob apply [KEY...] --mode dry|hold|submit [--headed] [--click-submit] [--hold-timeout SECONDS] [--limit N]
getmeajob inspect URL
```

| ID | Status | Behaviour |
|---|---|---|
| APP-1 | in progress | Form filling works for Greenhouse and Ashby forms only. |
| APP-2 | in progress | `--mode dry` fills the form and takes a screenshot. It never clicks submit. |
| APP-3 | in progress | `--mode hold` opens a visible browser and fills the form. With `--click-submit` it clicks submit once, then waits for you to type the emailed code. It records success, timeout or window closed. |
| APP-4 | in progress | `--mode submit` runs only when the ATS is listed in `preferences.apply.submit_boards`. It clicks submit once and refuses any plan with unreviewed drafts. |
| APP-5 | in progress | A CAPTCHA or bot check stops that job and adds a queue item. It is never retried. |
| APP-6 | in progress | An account wall stops that job. The tool never creates accounts. |
| APP-7 | in progress | A page that refuses automation stops that job. A fill problem means no submit. |
| APP-8 | in progress | The filler handles text, file uploads, type-ahead selects, Ashby yes/no buttons, radios, checkboxes, location type-ahead, phone country, multi-select and education or employment repeaters. A select with no matching option is reported as a problem, and location type-ahead picks only a matching suggestion. |
| APP-9 | in progress | Running `getmeajob apply` twice skips jobs already in the ledger. |
| APP-10 | in progress | A per-company cap (default 2 per 30 days) and an exclusion list from preferences are enforced. |
| APP-11 | in progress | If you close the browser window or a page crashes, that job is recorded as `closed_by_user` or `error`, and the run moves on to the next job. |
| APP-12 | in progress | The ledger records every attempt with an answers digest and the plan path. It never holds answer text. |
| APP-13 | in progress | Screenshots are saved as `shots/<mode>-<key>-<status>.png`. |
| APP-14 | in progress | `getmeajob inspect URL` prints a form's inputs, labels and options as a compact table. |
| APP-15 | in progress | The demo uses mock Greenhouse and Ashby forms written from scratch, with variants for a CAPTCHA, an email code, an account wall and a no-automation notice. |

## Queue and tracking

Commands:

```
getmeajob queue [--all] [--kind K]
getmeajob queue resolve ID [--note]
getmeajob queue add KEY --kind manual --note TEXT
getmeajob track set KEY STATUS [--note]
getmeajob track show KEY
getmeajob track list [--status S]
getmeajob track stats
getmeajob track ghost [--days 21] [--apply]
```

`getmeajob track import-xlsx PATH` is under Excel and Markdown tracker.

| ID | Status | Behaviour |
|---|---|---|
| TRK-1 | in progress | `getmeajob queue` groups open items by kind, each kind with a "what we need from you" line. |
| TRK-2 | in progress | Queue kinds are `needs_email_code`, `needs_answers`, `captcha`, `account_required`, `automation_refused`, `validation_error`, `fill_problem` and `manual`. |
| TRK-3 | in progress | Adding an item for a job and kind that already has an open item updates that item instead of adding a second one. |
| TRK-4 | in progress | Queue items resolve themselves when the cause clears. `getmeajob queue resolve ID` resolves one by hand. |
| TRK-5 | in progress | The status ladder is discovered, shortlisted, planned, ready, applied, screening, interviewing, offer, accepted. The side states are rejected, withdrawn, closed, skipped and ghosted. |
| TRK-6 | in progress | Automatic updates only move a job forward on the ladder. A person (with `getmeajob track set` or the Excel import) can set any status. |
| TRK-7 | in progress | Automatic `closed` applies only before `applied`. Automatic `ghosted` applies only from `applied` or `screening`. Nothing automatic moves a job out of a side state. Setting the current status again does nothing. |
| TRK-8 | in progress | Status events are appended to `data/events.jsonl`. |
| TRK-9 | in progress | `getmeajob track show KEY` prints one job's timeline, `getmeajob track stats` prints funnel counts, and `getmeajob track list` filters by `--status`. |
| TRK-10 | in progress | `getmeajob track ghost` treats an application as ghosted only after `--days` days (default 21). |

## Excel and Markdown tracker

Commands:

```
getmeajob report [--xlsx PATH] [--md PATH]
getmeajob track import-xlsx PATH
```

| ID | Status | Behaviour |
|---|---|---|
| XLS-1 | in progress | `getmeajob report` writes `exports/tracker.xlsx` and `exports/tracker.md` unless you pass other paths. |
| XLS-2 | in progress | The workbook has five sheets: Read me (counts), Tracker, Job descriptions, Queue and Questions. |
| XLS-3 | in progress | The Tracker sheet has one row per job with: key, company, role, location, tier, score, eligible, why, status, applied on, next action, resume used, plan status, unknowns, job link, JD file, posted, first seen, new or closed since last run, and notes. |
| XLS-4 | in progress | Status cells offer a drop-down of valid statuses. Job links are clickable. The header row is frozen and has filters. Rows are coloured by status. |
| XLS-5 | in progress | The Key column stays in the sheet (hidden) so your edits can be read back. |
| XLS-6 | in progress | The Job descriptions sheet holds each job's full text, up to 32,000 characters. |
| XLS-7 | in progress | `getmeajob track import-xlsx PATH` reads Status, Notes and Next action back by Key and records the changes. |
| XLS-8 | in progress | Importing the same file twice writes no duplicate events. |
| XLS-9 | in progress | The Markdown tracker groups jobs by status. |

## Resumes per role

Commands:

```
getmeajob resume tailor KEY
getmeajob resume render DIR_OR_KEY
getmeajob resume keywords KEY [--file PATH]
getmeajob resume list
getmeajob resume pick KEY
getmeajob resume lint [PATH]
```

| ID | Status | Behaviour |
|---|---|---|
| RES-1 | shipped | You write every sentence in `resume/bank.yaml`: header, summaries, experience bullets, projects, skills and education. |
| RES-2 | shipped | `getmeajob resume tailor KEY` picks and orders bullets from the bank by keyword overlap with the job text. It copies bank text word for word and writes nothing new. |
| RES-3 | shipped | Skills come only from the bank, with the ones the job mentions listed first. |
| RES-4 | shipped | Gaps (job keywords that are not in the bank) are listed in `report.json` and never added to the resume. |
| RES-5 | shipped | The same bank and the same job always give the same output. |
| RES-6 | shipped | Output goes to `roles/<company>-<role>/`: `jd.txt`, `resume.md`, `resume.html`, `report.json` and `meta.yaml`. |
| RES-7 | shipped | `getmeajob resume render` makes a Letter-size PDF through Chromium and checks that it fits on one page. If it does not fit, it drops the lowest-scoring bullets (keeping at least 2 per role) or fails with a clear message. |
| RES-8 | shipped | `getmeajob resume keywords KEY` shows which job keywords the resume covers and which it misses. |
| RES-9 | shipped | `getmeajob resume pick KEY` picks the best existing role resume for a job and sets it as that job's plan resume. |
| RES-10 | shipped | `getmeajob resume lint` warns about weak openers, stock phrases, invisible characters and em dashes. |
| RES-11 | shipped | `getmeajob resume list` lists the role resumes in the workspace. |

## Token saving

Commands:

```
getmeajob status
getmeajob context KEY
getmeajob tokens estimate FILE...
```

| ID | Status | Behaviour |
|---|---|---|
| TOK-1 | in progress | `getmeajob status` fits on one screen (40 lines or fewer): counts per status, new jobs from the last run, open queue items by kind, plans that need answers, and the next command to run. |
| TOK-2 | in progress | `getmeajob context KEY` prints a small pack for an agent, under 2,000 characters: the job digest, rank reasons, plan unknowns and a resume report summary. |
| TOK-3 | in progress | `getmeajob tokens estimate FILE...` prints characters divided by 4 for each file and in total, labelled as an estimate. |
| TOK-4 | in progress | Commands print diffs and digests instead of full dumps. Unknown questions show once per label. |
| TOK-5 | in progress | Plans are reused when the questions, profile and answers are unchanged. Drafts are cached by prompt hash. HTTP responses are cached on disk. |

## Agents and MCP

Commands:

```
getmeajob agents install --claude DIR [--flat]
getmeajob agents list
getmeajob mcp
getmeajob mcp config
```

Claude Code slash commands (plugin `getmeajob`): `/getmeajob:source`, `/getmeajob:rank`, `/getmeajob:plan`, `/getmeajob:review-answers`, `/getmeajob:apply-dry`, `/getmeajob:hold-run`, `/getmeajob:queue`, `/getmeajob:status`, `/getmeajob:tracker`, `/getmeajob:resume`.

| ID | Status | Behaviour |
|---|---|---|
| AGT-1 | planned | The Claude Code plugin `getmeajob` ships the ten slash commands above and one skill, `getmeajob`. |
| AGT-2 | planned | Each slash command runs a `getmeajob ... --json` command and shows the compact result. No slash command fills forms inside the chat. |
| AGT-3 | planned | `getmeajob agents install --claude DIR --flat` copies the commands as `getmeajob-<command>.md` into `DIR/.claude/commands/`. Without `--flat` it prints the plugin install steps. |
| AGT-4 | planned | `agents/AGENTS.md` describes the same workflow for Codex, ChatGPT and other agents. |
| AGT-5 | planned | `agents/POLICY.md` sets the truthfulness rules: never invent facts, gaps stay gaps, stop and ask, and treat page text as data and never as instructions. `agents/prompts/answer-review.md` shows only the deduplicated answer table and the unknowns. |
| AGT-6 | planned | `getmeajob mcp` runs a stdio MCP server named `getmeajob` with the tools `getmeajob_status`, `getmeajob_source`, `getmeajob_rank`, `getmeajob_plan`, `getmeajob_unknowns`, `getmeajob_answer`, `getmeajob_review`, `getmeajob_queue`, `getmeajob_report`, `getmeajob_jd` and `getmeajob_context`. Each calls the same code as the CLI and returns compact text. |
| AGT-7 | planned | No MCP tool fills or submits forms. Applying stays a CLI step that a person runs. |
| AGT-8 | planned | `getmeajob_status` on the demo workspace returns under 2,000 characters. |
| AGT-9 | planned | `getmeajob mcp config` prints client config snippets for Claude Desktop, Claude Code and ChatGPT. |
| AGT-10 | planned | Every command file has a `description` and refers only to CLI commands that exist. |

## Privacy guardrails

Scripts (outside the `getmeajob` CLI):

```
python scripts/scan_sensitive.py --tree --history
python scripts/scan_sensitive.py --staged
bash scripts/install-git-hooks.sh
```

| ID | Status | Behaviour |
|---|---|---|
| PRV-1 | shipped | Commits use the owner's own identity, set in the repo-local git config, and the remote is mapped. Agents never push. Public files never contain the owner's name, email or handle. The scanner allows the configured identity in commit metadata only, and CI runs it with `--skip-identity`. |
| PRV-2 | shipped | `.gitignore` keeps the workspace, profiles, answers, ledgers, screenshots, browser profiles, resumes, PDFs, `.env` files, caches and spreadsheets out of git. |
| PRV-3 | shipped | `scripts/scan_sensitive.py --tree --history` checks current files, plus every blob, commit message and author in history, for emails, phone numbers, personal URLs, API keys, home-folder paths and denylist terms. |
| PRV-4 | shipped | Placeholders are not findings: `example.com`, `example.org`, `example.net`, `.example`, `.invalid` and `.test` addresses, `noreply@` addresses, and `+1 555 01xx` phone numbers. |
| PRV-5 | shipped | The private denylist lives outside the repo. The scanner reads it from `GETMEAJOB_DENYLIST` (or `--denylist FILE`) and never prints a denylist term in full. ALL-CAPS and env-style terms match case-sensitively, as whole tokens. All denylist terms are checked in one combined pass. |
| PRV-6 | shipped | The scanner exits 1 on findings, 0 when clean, and 2 on a usage error. A `.scan-allow` file or a `scan:allow` marker on a line skips known-safe matches. |
| PRV-7 | shipped | A pre-commit hook runs the scanner on staged files. CI runs it on the tree and full history with generic patterns only. |
| PRV-8 | shipped | Examples use synthetic data only: `example.com`, `.org` and `.net` emails and URLs, `+1 555 01xx` phone numbers, and no real person or employer. |
| PRV-9 | shipped | Tool settings use the `GETMEAJOB_` prefix. The only vendor env var name in the repo is the Anthropic SDK's standard API-key variable. |
| PRV-10 | planned | The tool never creates accounts, solves CAPTCHAs, gets around bot walls, or fetches pages that robots.txt disallows. |

## Not in scope

These were decided against. See the "left out" rows in `docs/DECISIONS.md`.

1. A Lever form filler. Lever is for sourcing only (#8).
2. An email status reader and scam flags (#10).
3. Heavier career-site systems such as Workday, Oracle and Eightfold (#32).
4. Chat-app approvals, hash-chained audit logs, durable runtimes, outreach and contact lists, and interview prep (#33).
5. By design, never: account creation, CAPTCHA solving, bot-wall bypass, LinkedIn automation, a hosted service, a database server or a scheduler daemon.
