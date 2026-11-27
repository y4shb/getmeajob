# Decisions

In short: this file lists every decision made for getmeajob and the reason for it.
Each row gives the number, the decision, why, what was rejected, who decided (source) and the status.

Last updated: 2026-11-27, during wave 0. Entries 1 to 35 all date from that day.

Words used in the Source and Status columns:

- owner: the project owner's request or answer.
- orchestrator: the build orchestrator's call.
- research: research notes on an earlier private prototype.
- decided / left out / open: settled, settled as "not building it", or still waiting on an answer.

Build workers add their decisions here after each milestone, each with its reason and the alternative they rejected. To add one:

1. Pick the section that fits best.
2. Use the next free number. Numbers never change.
3. Fill every column. If nobody recorded the reason, write "not recorded" and add the item to Open at the end.

## Naming and identity

| # | Decision | Why | Rejected | Source | Status |
|---|---|---|---|---|---|
| 1 | Everything is named getmeajob: the package, the CLI `getmeajob`, the MCP server `getmeajob` with tools `getmeajob_<verb>`, the Claude Code plugin `getmeajob` (`/getmeajob:<command>`), the skill `getmeajob`, the env prefix `GETMEAJOB_` and the user agent `getmeajob/<version>`. | The owner wants the identity to be getmeajob wherever possible. | An earlier working name. | owner | decided |
| 12 | The only vendor env var name in the repo is the Anthropic SDK's standard API-key variable. All tool settings use the `GETMEAJOB_` prefix. | The owner's denylist covers private env key names, and the owner allowed this one standard name. | Banning that name too. | owner | decided |
| 13 | The repo-local git identity is `getmeajob maintainers <maintainers@getmeajob.invalid>`, with commit signing off locally. | The owner asked for a neutral noreply identity. The `.invalid` domain never delivers mail. The owner may change it before publishing. | none considered | owner | decided |
| 14 | Commit messages carry no co-author or tool trailers. | The owner's standing preference. | none considered | owner | decided |
| 25 | Claude Code files ship as a plugin named getmeajob, with commands `/getmeajob:<command>`. Flat copies named `getmeajob-<command>.md` serve projects that do not use plugins. | The owner's naming rule and the plugin namespacing convention. | none considered | owner, orchestrator | decided |
| 34 | The MIT copyright line is "getmeajob contributors". | Neutral until the owner picks a name. | none considered | orchestrator | open (owner may change) |
| 35 | Final repository name. | not recorded | none considered | owner | open |

## Data, network and tracking

| # | Decision | Why | Rejected | Source | Status |
|---|---|---|---|---|---|
| 3 | Storage is JSON and JSONL files in a gitignored workspace. The apply ledger, status events and queue are append-only logs. | Transparent, easy for agents to grep, diffable, stdlib only, no migrations. | SQLite: opaque to users and agents, and schema work for a few thousand rows. | orchestrator | decided |
| 5 | One HTTP client (httpx) with timeouts, retries with backoff and jitter, `Retry-After`, no retry on 404 or 410, a minimum interval per host, low concurrency (4), a disk cache with ETag revalidation, an immediate stop on bot walls, and robots.txt checks for HTML pages. | The owner asked for polite defaults and no scraping around robots.txt or bot walls. | requests (no transport injection for offline tests); aiohttp (async not needed). | owner, orchestrator | decided |
| 6 | An offline fixture transport replays recorded files for the demo and the tests. | The quick start and the tests must run with no network. | Live calls in the demo. | owner, orchestrator | decided |
| 20 | Automatic status updates only move forward. A person can set any status. | Automation must not undo a person's edit. | none considered | orchestrator, research | decided |
| 21 | The Excel tracker round-trips: `getmeajob track import-xlsx` reads Status, Notes and Next action back by Key. | Less technical users work in Excel. | none considered | orchestrator | decided |
| 27 | The default workspace is `./workspace` (gitignored). `--home` or `GETMEAJOB_HOME` overrides it. | Less technical users can find it and open the Excel file. | A hidden `~/.getmeajob` folder. | orchestrator | decided |

## Sourcing and scope

| # | Decision | Why | Rejected | Source | Status |
|---|---|---|---|---|---|
| 8 | Lever is supported for sourcing only. There is no Lever form filler. | The owner asked for Ashby and Greenhouse fillers. Research found that Lever forms often show hCaptcha at submit. | A Lever filler. | owner, research | left out |
| 9 | Extra sources: SmartRecruiters, Workable and Recruitee boards, plus the Remotive, RemoteOK and HN Who is hiring feeds, all off by default. | The owner picked "more job sources". | none considered | owner | decided |
| 10 | No email status reader and no scam flags. | The owner did not select them. | none considered | owner | left out |
| 11 | Board discovery uses only the user's own list, URLs, careers pages and ATS probes. There is no third-party company lookup service. | Such a service would receive the user's target list, and its availability is outside our control. | A company-domain lookup API. | orchestrator | decided |
| 32 | Heavier career-site systems (Workday, Oracle, Eightfold and similar) are left out. | They use account portals and bot walls, and they are outside the owner's scope. | none considered | orchestrator, research | left out |
| 33 | Features described in the research notes on an earlier private prototype are left out: chat-app approvals, hash-chained audit, durable runtimes, outreach and contact lists, and interview prep. | They are personal, or too heavy for a CLI. | none considered | research, owner | left out |

## Forms, answers and resumes

| # | Decision | Why | Rejected | Source | Status |
|---|---|---|---|---|---|
| 7 | Ashby form questions come from the same no-login request that Ashby's public job page makes (cached, at most 1 per second). Reading the rendered page in Chromium is the fallback. | The owner's choice. It is fast and needs no browser for planning. | Reading the rendered page only. | owner | decided |
| 15 | Optional AI drafting covers free-text questions only, behind `getmeajob plan draft`, with a token budget, a cache keyed by prompt hash, and every draft marked `needs_review`. Submit mode refuses plans with unreviewed drafts. Providers: Anthropic (optional extra) and a "command" provider that pipes the prompt to any CLI. | The owner's spec. The command provider covers other vendors with no extra dependency. | An OpenAI SDK provider. | owner, orchestrator | decided |
| 16 | The default drafting model is `claude-sonnet-5-5`. | A current, capable mid-tier model. | Opus (cost); Haiku (quality of free text). | orchestrator | decided (owner may change) |
| 17 | Consent questions are answered only when the profile opts in. Questions about AI or automation use are never answered automatically. A form that says not to use automated tools blocks the plan. | Honesty and site terms. Research found an old rule that answered "yes" to such questions. | none considered | orchestrator, research | decided |
| 18 | The option matcher never picks the first option as a fallback. An ambiguous match becomes an unknown, with a reason. | Research found silent wrong picks. | none considered | research | decided |
| 19 | EEO and demographic questions get the "decline" option when the profile leaves them unset. | The questions are voluntary, and declining is truthful. | none considered | orchestrator | decided |
| 22 | Resumes per role are built by deterministic selection and ordering from a fact bank the candidate writes. The PDF comes from Chromium `page.pdf()`. | Truthful by construction. No LaTeX toolchain. It reuses the browser the form filler already needs. | LLM rewriting of bullets; LaTeX. | owner, orchestrator | decided |
| 23 | `getmeajob init --demo` generates the demo resume PDF with a tiny built-in PDF writer. | No binary files in the repo. | none considered | orchestrator | decided |

## Build, agents and process

| # | Decision | Why | Rejected | Source | Status |
|---|---|---|---|---|---|
| 2 | Clean-room rewrite. Research agents read the old sources and wrote prose notes (the research notes on an earlier private prototype). Build agents never open those sources. | The owner requires a clean-room rewrite, and the old sources contain personal data. | Porting files and editing them. | owner | decided |
| 4 | The CLI uses argparse. | No extra dependency, and easy to type-check. | typer; click. | orchestrator | decided |
| 24 | The MCP server has no tool that fills or submits forms. | Form filling stays a step that a person runs. | none considered | orchestrator | decided |
| 26 | The package requires `playwright>=1.45`. The dev environment pins 1.62 so it reuses a Chromium build already on the machine. | Avoids a browser download. | none considered | orchestrator | decided |
| 28 | The build backend is hatchling. `examples/` and `agents/` are included in the wheel. | The demo works after a plain pip install. | none considered | orchestrator | decided |
| 29 | The private denylist stays outside the repo, at a path the owner chose. The scanner reads it through `GETMEAJOB_DENYLIST`. CI uses generic patterns only. | The list itself is personal. | none considered | owner | decided |
| 30 | The scanner matches env-style denylist terms case-sensitively, as whole tokens. | Avoids false hits on ordinary code words such as `dry_run`. | none considered | orchestrator | decided |
| 31 | Python 3.11 is the minimum version. CI runs on 3.11 and 3.12. | not recorded | none considered | owner | decided |

## Open

Waiting on the owner:

1. Final repository name (#35). The reason is not recorded because the decision is not made yet.
2. Copyright line (#34). It stays "getmeajob contributors" until the owner picks a name.
3. Reason for the Python 3.11 minimum (#31) is not recorded.

Decided, but the owner may still change them:

1. Git identity (#13), before publishing.
2. Default drafting model (#16).
