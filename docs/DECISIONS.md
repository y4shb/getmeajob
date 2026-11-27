# Decisions

In short: this file lists every decision made for getmeajob and the reason for it.
Each row gives the number, the decision, why, what was rejected, who decided (source) and the status.

Last updated: 2026-11-27, after wave 2 (applying, queue, tracking, tracker files, token saving) and the license change. Entries 1 to 136 all date from that day.

Words used in the Source and Status columns:

- owner: the project owner's request or answer.
- orchestrator: the build orchestrator's call.
- research: research notes on an earlier private prototype.
- decided / left out / open: settled, settled as "not building it", or still waiting on an answer.

Entries 36 and up come from the wave 0, wave 1 and wave 2 build workers' reports and the orchestrator. Build workers add their decisions here after each milestone, each with its reason and the alternative they rejected. To add one:

1. Pick the section that fits best.
2. Use the next free number. Numbers never change.
3. Fill every column. If nobody recorded the reason, write "not recorded" and add the item to Open at the end.

## Naming and identity

| # | Decision | Why | Rejected | Source | Status |
|---|---|---|---|---|---|
| 1 | Everything is named getmeajob: the package, the CLI `getmeajob`, the MCP server `getmeajob` with tools `getmeajob_<verb>`, the Claude Code plugin `getmeajob` (`/getmeajob:<command>`), the skill `getmeajob`, the env prefix `GETMEAJOB_` and the user agent `getmeajob/<version>`. | The owner wants the identity to be getmeajob wherever possible. | An earlier working name. | owner | decided |
| 12 | The only vendor env var name in the repo is the Anthropic SDK's standard API-key variable. All tool settings use the `GETMEAJOB_` prefix. | The owner's denylist covers private env key names, and the owner allowed this one standard name. | Banning that name too. | owner | decided |
| 13 | Commits use the owner's own identity, set in the repo-local git config, and the remote `origin` is mapped to the owner's GitHub repository. Agents never push. The scanner allows the repo's configured identity in commit metadata only, and CI runs it with `--skip-identity`. Where the author's name may appear in public files is set in #136. | The owner changed the earlier instruction on 2026-11-27 and asked for the remote to be mapped. | The neutral `getmeajob maintainers` identity first planned. | owner | decided |
| 14 | Commit messages carry no co-author or tool trailers. | The owner's standing preference. | none considered | owner | decided |
| 25 | Claude Code files ship as a plugin named getmeajob, with commands `/getmeajob:<command>`. Flat copies named `getmeajob-<command>.md` serve projects that do not use plugins. | The owner's naming rule and the plugin namespacing convention. | none considered | owner, orchestrator | decided |
| 34 | The license is Apache-2.0 with a NOTICE file that credits the original author. | The owner wants people to use and change the code while crediting them; the NOTICE file is the standard Apache way to require that credit. | MIT (credit only through the copyright line in copies of the code); a custom license (not a recognised open-source license) | owner | decided |
| 35 | Final repository name. | not recorded | none considered | owner | open |
| 136 | The author's name, GitHub username and email appear only in NOTICE, the README credit and clone line, and the package metadata. They appear nowhere in code, tests, examples or other docs. The scanner enforces this with a private allow list (`GETMEAJOB_ALLOW`) and file-scoped rules. Everything else personal stays banned. | The owner ruled that the README may use the real repository URL and credit the author, and that the credit needs a defined, checkable place. | Allowing the name anywhere in public files. | owner | decided |

## Data, network and tracking

| # | Decision | Why | Rejected | Source | Status |
|---|---|---|---|---|---|
| 3 | Storage is JSON and JSONL files in a gitignored workspace. The apply ledger, status events and queue are append-only logs. | Transparent, easy for agents to grep, diffable, stdlib only, no migrations. | SQLite: opaque to users and agents, and schema work for a few thousand rows. | orchestrator | decided |
| 5 | One HTTP client (httpx) with timeouts, retries with backoff and jitter, `Retry-After`, no retry on 404 or 410, a minimum interval per host, low concurrency (4), a disk cache with ETag revalidation, an immediate stop on bot walls, and robots.txt checks for HTML pages. | The owner asked for polite defaults and no scraping around robots.txt or bot walls. | requests (no transport injection for offline tests); aiohttp (async not needed). | owner, orchestrator | decided |
| 6 | An offline fixture transport replays recorded files for the demo and the tests. | The quick start and the tests must run with no network. | Live calls in the demo. | owner, orchestrator | decided |
| 20 | Automatic status updates only move forward. A person can set any status. | Automation must not undo a person's edit. | none considered | orchestrator, research | decided |
| 21 | The Excel tracker round-trips: `getmeajob track import-xlsx` reads Status, Notes and Next action back by Key. | Less technical users work in Excel. | none considered | orchestrator | decided |
| 27 | The default workspace is `./workspace` (gitignored). `--home` or `GETMEAJOB_HOME` overrides it. | Less technical users can find it and open the Excel file. | A hidden `~/.getmeajob` folder. | orchestrator | decided |
| 36 | `retries=3` means 3 extra tries, so 4 attempts in all. | not recorded | 3 attempts in total. | build worker | decided |
| 37 | A `Retry-After` above 60 seconds makes the client raise an error that names the wait. | Retrying early is impolite, and waiting out the full time would block the CLI. | Retrying early; blocking for the full wait. | build worker | decided |
| 38 | robots.txt: a 4xx reply allows the page. A 5xx or a timeout after retries refuses it. | RFC 9309 says so. | not recorded | build worker | decided |
| 39 | The disk cache is used only when a cache time is given, and it stores only 200 replies. No cache time means no cache. | not recorded | not recorded | build worker | decided |
| 40 | In fixture mode there is no disk cache and no wait between requests, and robots.txt is answered 404 before routes are checked. `offline: true` without fixtures refuses every request. | not recorded | not recorded | build worker | decided |
| 41 | `JobStore.upsert` keeps the stored description when the incoming one is empty, and does not count that as a change. | It protects the Greenhouse fallback, which lists jobs without full text. | not recorded | build worker | decided |
| 42 | Reading a record: a missing or null required field becomes None, `[]` or `{}` when the type allows it, and otherwise raises a store error that names the file. A number given for a text field becomes text (job ids). | not recorded | not recorded | build worker | decided |
| 43 | Queue item ids are short numbers ("1", "2"). Adding an identical open item writes nothing. | Short ids are easy to type, and re-runs stay idempotent. | not recorded | build worker | decided |
| 44 | Automatic sources can never set `rejected`, `withdrawn` or `skipped`. An unknown source counts as automatic. | not recorded (it follows #20). | not recorded | build worker | decided |
| 45 | Atomic writes create files readable only by the user (mode 0600). | A side effect of the temp-file call. It is a small privacy gain. | not recorded | build worker | decided |
| 46 | A job that comes back after being marked closed is reopened to `discovered` by sourcing. | not recorded | not recorded | orchestrator | decided |
| 122 | The Excel Tracker sheet has a hidden "Sync (do not edit)" column per row. It stores what getmeajob last wrote: the status and short hashes of Notes and Next action. Only cells that differ from it count as edits on import. | If you save an old copy of the file, rows you did not touch cannot undo newer changes. | Comparing with the current status, which would revert automatic progress. | build worker | decided |
| 123 | `getmeajob report` keeps edits you have not imported yet when it rewrites the file. It refuses to overwrite a file it cannot read. | No edit is lost. | Importing during `report`, which would be a hidden write. | build worker | decided |
| 124 | A hidden "Open queue items" column feeds the yellow row fill. | The colour stays right when you sort, and the visible columns stay exactly as specified. | Fills tied to fixed row ranges; formulas that point at the Queue sheet. | build worker | decided |
| 125 | The Key column is visible, not hidden. | People need the key to type `getmeajob track set KEY`. | Hiding it, as the plan said. | build worker | decided |
| 126 | Skipped and ghosted rows are grey, along with the three statuses already listed. | They are dead ends too. | not recorded | build worker | decided |
| 127 | Notes are an append-only `data/notes.jsonl`. The latest value wins, and an empty cell clears a note. | Same pattern as the other logs, and a second import changes nothing. | not recorded | build worker | decided |
| 128 | One write path (`record_by_person`) handles every status a person sets. Moving a job to applied or later, or to a dead end, also resolves its open queue items. | Queue items resolve when their cause clears. | Leaving stale items in the queue. | build worker | decided |
| 129 | The ghost sweep records its events with the source `ghost` and reads status events only. The source list now includes `ghost`. | It is automatic, so the forward-only store rules apply to it. | Reusing the `liveness` source. | build worker | decided |
| 130 | The Job descriptions sheet covers jobs on the Tracker only. | It keeps the file small. | Every sourced job. | build worker | decided |
| 131 | `status` and the Questions sheet skip jobs that are already applied or dropped when they list unknown questions. | Otherwise `status` keeps suggesting `plan unknowns` for jobs you are done with. | not recorded | build worker | decided |
| 132 | `getmeajob tokens estimate` needs no workspace. A relative path is tried from the current folder first, then from the workspace. | It then works on any file. | not recorded | build worker | decided |
| 133 | `getmeajob queue add` takes any kind (default `manual`), and the `queue` list shows 20 rows by default. | It stays flexible and stays under 40 lines. | not recorded | build worker | decided |
| 134 | The Read me sheet shows two counts per status: live `COUNTIF` formulas and fixed counts written at export. | An app that does not recalculate on open still shows numbers. | not recorded | build worker | decided |

## Sourcing and scope

| # | Decision | Why | Rejected | Source | Status |
|---|---|---|---|---|---|
| 8 | Lever is supported for sourcing only. There is no Lever form filler. | The owner asked for Ashby and Greenhouse fillers. Research found that Lever forms often show hCaptcha at submit. | A Lever filler. | owner, research | left out |
| 9 | Extra sources: SmartRecruiters, Workable and Recruitee boards, plus the Remotive, RemoteOK and HN Who is hiring feeds, all off by default. | The owner picked "more job sources". | none considered | owner | decided |
| 10 | No email status reader and no scam flags. | The owner did not select them. | none considered | owner | left out |
| 11 | Board discovery uses only the user's own list, URLs, careers pages and ATS probes. There is no third-party company lookup service. | Such a service would receive the user's target list, and its availability is outside our control. | A company-domain lookup API. | orchestrator | decided |
| 32 | Heavier career-site systems (Workday, Oracle, Eightfold and similar) are left out. | They use account portals and bot walls, and they are outside the owner's scope. | none considered | orchestrator, research | left out |
| 33 | Features described in the research notes on an earlier private prototype are left out: chat-app approvals, hash-chained audit, durable runtimes, outreach and contact lists, and interview prep. | They are personal, or too heavy for a CLI. | none considered | research, owner | left out |
| 47 | Boards are grouped by ATS. Groups run side by side, boards inside a group run one after another, and a bot check skips the rest of that group. | A site that already blocked us should not be hit again. | One thread per board. | build worker | decided |
| 48 | Feed jobs never close when they drop out of a feed. | A feed is a short latest list, so absence proves nothing. | Treating a feed like a board. | build worker | decided |
| 49 | HN Who is hiring sends two requests when its cache is cold: one to find the current thread (cached 24 hours), one for its comments (cached 6 hours). | There is no single-request way to get the comments. | Algolia comment pages, which take up to 8 requests. | build worker | decided |
| 50 | Ashby sends the workplace type separately, so getmeajob adds "(Hybrid)" or "Remote - " to the location when the text lacks it. | Ashby's location text alone loses that detail. | Writing "(Hybrid)" straight into the fixture. | build worker | decided |
| 51 | SmartRecruiters job text comes from one detail request per job, cached 7 days, with at most 25 network fetches per board per run. A small country-code table covers its short codes. A list cut off at 1,000 jobs is marked partial and closes nothing. | not recorded | Fetching every detail on every run. | build worker | decided |
| 52 | Recruitee is not tried for company-name guesses in discovery. It is still found from URLs and careers pages. | Its boards live on per-company subdomains, so each wrong guess costs a DNS failure plus 3 retries. | Probing all six ATS. | build worker | decided |
| 53 | A board linked from the company's own careers page counts as verified even when the board has no name. If the board's name contradicts the company, it is unverified. | not recorded | Requiring a name match. | build worker | decided |
| 54 | `import-portals --write` changes only `companies.yaml`. The title, location and alias filters are printed and shown in `--json`, but not written to preferences. | The ranking agent owns the preferences schema. | Writing keys the preferences loader might reject. | build worker | decided |
| 55 | Disabled portals entries are imported with `enabled: false`. | not recorded | Dropping them. | build worker | decided |
| 56 | `--board` and `--company` pick boards even when they are disabled. An `ats:slug` that is not in `companies.yaml` is fetched as a one-off board. | not recorded | not recorded | build worker | decided |
| 57 | `getmeajob source` exits 1 only when every board failed. Partial failures exit 0 and list the problems. | not recorded | not recorded | build worker | decided |
| 58 | The source diff is one table with a `change` column. Keys are never cut. Company, title and location are cut at 28, 40 and 40 characters. | not recorded | not recorded | build worker | decided |
| 59 | `getmeajob jd KEY` accepts a unique part of a key, such as `1001`, as `explain` does. | It matches `getmeajob explain`. | not recorded | build worker | decided |
| 60 | Run files are named `<timestamp>.json`, then `<timestamp>_02.json` for a second run in the same second. | The suffix keeps them in run order. | not recorded | build worker | decided |
| 61 | HN comment links are added to the job text under "Links:". | `Job` has no links field, and HN shortens long link text. | not recorded | build worker | decided |
| 62 | `save_boards` keeps the comment block at the top of the file. | not recorded | A plain YAML dump, which drops all comments. | build worker | decided |

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
| 63 | `off_track` is a hard flag whenever tracks are set and no `title_any` word matches. | It is predictable, and the Data Analyst job must be ineligible. | Letting a job-text keyword rescue the title, because that job's text can mention Python. | build worker | decided |
| 64 | A title with a `too_senior` word (staff, principal) is a hard flag, unless the job asks for no more years than you have. Then it is soft. "Member of technical staff" is stripped before matching. | It follows the research notes. | Always hard. | build worker | decided |
| 65 | `title.junior` words lower the title score and show in the reasons, but add no flag. | The flag codes in the plan have no junior code. | A hard `junior` flag. | build worker | decided |
| 66 | Preference weights are scaled to sum 100. | Any set of weights then gives a 0 to 100 score. | Using them as given. | build worker | decided |
| 67 | `rank` writes every open job to `ranked.jsonl` and applies `--min-score` only to the printed list. Closed jobs are skipped. A row that has not changed keeps its old `ranked_at`, so a second run gives identical files. | The planner needs all rows. | Filtering the file. | build worker | decided |
| 68 | Years bands: up to your years minus 3 scores 0.45, up to your years scores 1.0, a stretch scores 0.8 then 0.5, and above `too_senior_over` scores 0 with a hard flag. A soft flag marks the zone between your stretch and the hard limit. | not recorded | not recorded | build worker | decided |
| 69 | A bare "Remote" counts as remote worldwide only when the job text names your region, an allowed region or a global word. Otherwise it is `other`, with the reason "region not stated". | It follows the research notes. | not recorded | build worker | decided |
| 70 | Region names ("US", "U.S.", "United States" are one place) live in `regions_default.yaml` as data. Users extend them with `locations.region_aliases`. Short codes match only in capitals. | No place is hard-coded in Python. A lowercase "us" is an ordinary word. | A table inside the code. | build worker | decided |
| 71 | `no_sponsorship` fires only when no-sponsor wording is present and the job's location or region limits name a country in `needs_sponsorship_in`. | Flagging every "we do not sponsor" would block jobs in countries you may work in. | Flagging any no-sponsor wording. | build worker | decided |
| 72 | Skills score: naming half of your weighted skills gives full marks. Each gap takes 0.25 off, at most 0.5. Job text under 200 characters scores 0.5. Gaps are searched in the first 6,000 characters. | not recorded | not recorded | build worker | decided |
| 73 | The resume as data is stored in `report.json` under `doc`. | `render` can then compact the resume and rewrite its files. | An extra file in the role folder. | build worker | decided |
| 74 | `resume pick` returns the path to `resume.pdf`. Roles without a PDF are ignored. A role that already lists the key wins. Otherwise the best keyword coverage wins (at least one keyword), and the key moves into that role's `meta.yaml`. | not recorded | not recorded | build worker | decided |
| 75 | Compaction order: first swap in the bank's `short` wording, then drop the lowest-scoring bullets. Ties drop later roles and later bullets first. At least 2 bullets stay per role. The page count is checked from the PDF too. After compaction, `resume.md`, `resume.html` and `report.json` are rewritten to match, with a `compaction` note. | not recorded | not recorded | build worker | decided |
| 76 | `resume.md` and `resume.html` carry no timestamps. The role folder is `<company slug, 30>-<title slug, 40>`. A second job with the same company and title shares the folder, and the job keys are merged. | Same input gives same output. | not recorded | build worker | decided |
| 77 | The skill "Go" is matched by a list of patterns that accepts a language context (a list of languages, "in Go", "Go services", "write Go"). Aliases such as postgresql and k8s point to the same pattern. | "Go to market" must not count as the language. | not recorded | build worker | decided |
| 78 | Extra answer kinds: sponsorship, work authorization, former employer, location, compensation, file, education and languages. | One field lookup cannot answer these truthfully. | The old prototype's regex-only yes/no answers. | build worker | decided |
| 79 | A sponsorship or work-permit question with no country uses the job location. For a remote job it uses the home country. The answer carries a note saying so. | The demo question needs a truthful answer. | Always answering "No", or always leaving it unknown. | build worker | decided |
| 80 | Sanctions, relative or conflict, and referral questions are unknown when required and blank when optional. | The profile has no fields for them, and the schema is fixed. | A blind "No", or adding profile fields. | build worker | decided |
| 81 | A skill yes/no question gets "Yes" only for `experience.primary_languages`, never "No". | `preferences.yaml` is not an answer source. | Reading skills from preferences. | build worker | decided |
| 82 | Former-employer questions match only when the whole company name matches after dropping legal suffixes, and the question names the company or says "us" or "our company". | "Initech Example Ltd" is not "Example Corp", and "worked with Kubernetes" is a skill question. | not recorded | build worker | decided |
| 83 | In the option matcher, any step that finds more than one candidate stops as ambiguous. A closed year range beats an open one, and years count as completed years (rounded down). | not recorded | not recorded | build worker | decided |
| 84 | Short country codes such as "US" match only in capitals. | "Join us" is not a country. | not recorded | build worker | decided |
| 85 | Optional pay questions are always blank. Current pay is answered only when `share_current` is true. "Relevant experience" years count as topic-specific, so they become unknown. | not recorded | not recorded | build worker | decided |
| 86 | The AI-use rule also reads the question description. Refusal patterns do not fire on a bare "agents". | "Recruitment agents" must not block a plan. | not recorded | build worker | decided |
| 87 | In the Greenhouse fixture, gender, race and veteran questions sit in `demographic_questions`, `compliance` holds only the EEOC notice, and education comes from a top-level `education: education_optional`. | Each demo question then appears exactly once. | not recorded | build worker | decided |
| 88 | A schema problem is recorded as `blocked_reason`, and failed fetches are never cached. | Plan has no note field. | not recorded | build worker | decided |
| 89 | The plan's `inputs_hash` covers the schema, the profile, only the answers relevant to that job, the rules and refusal patterns, resume size and modified time, and job fields. | Approving one job should not re-plan the others. | not recorded | build worker | decided |
| 90 | The Ashby Chromium fallback never runs offline or with fixtures, and checks robots.txt first. | not recorded | not recorded | build worker | decided |
| 91 | `getmeajob plan` is one parser that dispatches on its first word. Limitation: `plan K1 --refresh K2` errors, so options go after all keys. | `plan KEY...` and `plan show KEY` cannot both be argparse subparsers. | not recorded | build worker | decided |
| 92 | Answer stubs: a question asked by one company goes under `by_company.<slug>`, otherwise under `global`. `plan answer` rewrites `answers.yaml` with a fixed header, so old comments in that file are lost. | not recorded | not recorded | build worker | decided |
| 93 | The AI drafting provider calls the Anthropic SDK's beta messages call with server-side fallback switched on and effort `low`. Drafts are stored with `source: draft`. The budget estimate is prompt characters divided by 4, plus max tokens. | The build worker took these from the SDK's current guidance for the default model and checked the call against the installed SDK. The owner may want to switch the fallback off. | not recorded | build worker, orchestrator | decided (owner may change) |
| 107 | Dry runs never block later runs. Only these skip as duplicates: a submitted job, a job tracked as `applied` or later, or a last attempt of `awaiting_human`, `captcha`, `account_required` or `automation_refused`. `needs_email_code` blocks dry and submit runs but not hold runs. | Hard stops are never retried, and a job that needs a code is queued for a hold run. | Blocking on any earlier attempt. | build worker | decided |
| 108 | Skipped jobs are returned to the caller but not written to the ledger. | The ledger records attempts. Skip lines would hide the real last status. | Logging every skip. | build worker | decided |
| 109 | Hold mode runs headless only when a stand-in human is injected (tests). Real use always opens a visible window. | The human-in-the-window rule holds for real use, and tests can still run. | A hidden headless override. | build worker | decided |
| 110 | `--mode` defaults to `dry`. | It is the safest choice, and the mode is still named in the command. | Making the flag required. | build worker | decided |
| 111 | Submit needs opt-in. If no selected job's board is listed in `apply.submit_boards`, the run stops with exit 2. If only some are listed, the others are `skipped_not_ready`. | Jobs on opted-in boards can still go ahead. | Refusing the whole run when only some boards are not opted in. | build worker | decided |
| 112 | The per-company cap counts distinct jobs per company name with `submitted`, `awaiting_human` or `needs_email_code` in the last 30 days. Dry runs are not capped. `per_company_cap: 0` turns the cap off. | Those are applications that were sent or may have been sent. | not recorded | build worker | decided |
| 113 | An exclusion matches the board slug, the full job key, or part of the company name. | not recorded | not recorded | build worker | decided |
| 114 | An error after the Submit click is recorded as `awaiting_human`. | No later run can click Submit twice. | not recorded | build worker | decided |
| 115 | Hold run details: with fill problems or unreviewed drafts, `--click-submit` does not click, and the person still gets the window. If the person does not finish, a `fill_problem` queue item is added next to the result. A timeout while the code step is showing becomes `needs_email_code`. A real page crash is `error`, not `closed_by_user`. | not recorded | not recorded | build worker | decided |
| 116 | Employment rows come from `profile.employment[]`, not from the plan. | The form schema has no employment questions. | not recorded | build worker | decided |
| 117 | The filler never picks "Other" for a school on its own. An unmatched school is a problem only when the field is required. | not recorded | Automatic "Other" pick. | build worker | decided |
| 118 | The ledger and the queue redact answer values of 4 or more characters. Values that also appear in the job's own public text are left alone. | The ledger must never hold answer text. The demo last name "Example" is part of the company name, so leaving public-text matches alone avoids broken notes. | not recorded | build worker | decided |
| 119 | With fixtures on, paths in `forms.json` resolve next to that file, then one folder up. A `?variant` query is kept. Browser requests other than `file:` are aborted. | The demo and tests must make no network calls. | not recorded | build worker | decided |
| 120 | `getmeajob inspect` also needs a workspace. | It reads the fixture settings from there, and the brief said every command needs one. | not recorded | build worker | decided |
| 121 | On cookie banners the filler clicks only "necessary only" style buttons inside a banner. | not recorded | not recorded | build worker | decided |

## Build, agents and process

| # | Decision | Why | Rejected | Source | Status |
|---|---|---|---|---|---|
| 2 | Clean-room rewrite. Research agents read the old sources and wrote prose notes (the research notes on an earlier private prototype). Build agents never open those sources. | The owner requires a clean-room rewrite, and the old sources contain personal data. | Porting files and editing them. | owner | decided |
| 4 | The CLI uses argparse. | No extra dependency, and easy to type-check. | typer; click. | orchestrator | decided |
| 24 | The MCP server has no tool that fills or submits forms. | Form filling stays a step that a person runs. | none considered | orchestrator | decided |
| 26 | The package requires `playwright>=1.45`. The dev environment pins 1.62 so it reuses a Chromium build already on the machine. | Avoids a browser download. | none considered | orchestrator | decided |
| 28 | The build backend is hatchling. `examples/` and `agents/` are included in the wheel. | The demo works after a plain pip install. | none considered | orchestrator | decided |
| 29 | The private denylist stays outside the repo, at a path the owner chose. The scanner reads it through `GETMEAJOB_DENYLIST`. A private allow list (`GETMEAJOB_ALLOW`) names the few places where the author's credit is allowed (see #136). CI uses generic patterns only. | The list itself is personal. | none considered | owner | decided |
| 30 | The scanner matches env-style denylist terms case-sensitively, as whole tokens. | Avoids false hits on ordinary code words such as `dry_run`. | none considered | orchestrator | decided |
| 31 | Python 3.11 is the minimum version. CI runs on 3.11 and 3.12. | not recorded | none considered | owner | decided |
| 94 | `--json`, `-q` and `--home` also work after the command name, through a parser subclass. A subcommand that defines them again fails at startup. | not recorded | not recorded | build worker | decided |
| 95 | `main` returns argparse's exit code instead of raising `SystemExit`. An OS error gives a friendly message and exit 2, and a broken pipe exits 0. Real bugs still show a traceback. | not recorded | not recorded | build worker | decided |
| 96 | `--json` silences `line`, `table` and `done`, and `emit` prints one line of JSON. `--quiet` silences everything except `warn()`. | not recorded | not recorded | build worker | decided |
| 97 | `init` writes `settings.yaml` in both modes and refuses to overwrite without `--force`. It also writes a workspace `.gitignore` containing `*`. Config templates ship in the wheel as `getmeajob/_config`. | A stale demo setting must not leave a real workspace offline. | not recorded | build worker | decided |
| 98 | Templates leave booleans and numbers empty (unknown). Only the consent fields are `false`. `companies: []` and `tracks: []` come with commented examples. | An empty active entry would be fetched, or would mark every job off track. | not recorded | build worker | decided |
| 99 | Demo fields the plan does not pin are filled with plausible values (for example `over_18: true`, `open_to_onsite: false`). The one global answer is "Preferred work arrangement: Hybrid". | The Ashby demo form asks that question. | not recorded | build worker | decided |
| 100 | pytest runs with `--import-mode=importlib --strict-markers`. | Later agents can reuse file names such as `test_cli.py`. | not recorded | build worker | decided |
| 101 | The CI browser job accepts pytest exit code 5 (no tests collected) until browser tests exist. | not recorded | not recorded | build worker | decided |
| 102 | The scanner matches an allow pattern against `rule:matched-text` as well, so a single GitHub owner/repo link can be allowed. Word-like denylist terms match on letter and digit boundaries (`_` counts as a separator). Multi-word terms also match when joined by `-`, `_`, `.` or nothing. Every matched value is masked in printed locations. | not recorded | not recorded | build worker | decided |
| 103 | The scanner also checks file, zip-member and ref names, tag messages, UTF-16 strings and decompressed PDF streams (decompression capped). `--staged` also checks the repo's configured git name and email. It adds `--repo DIR` and a few key patterns (Stripe live, GitLab, npm, Slack webhook). | Reading the config avoids writing vendor env var names into the repo. | not recorded | build worker | decided |
| 104 | The hook installer writes to the repo's own hooks folder, never one set by `core.hooksPath`, and backs up a foreign hook. The pre-commit config uses `language: python`. | `python` always exists. | not recorded | build worker | decided |
| 105 | The test socket guard also blocks DNS lookups, raises an error httpx does not retry, and clears `GETMEAJOB_*` env vars during tests. | A swallowed error would turn into silent retries. | not recorded | build worker | decided |
| 106 | The private denylist matches ALL-CAPS terms case-sensitively, and all denylist terms are checked in one combined pass. | not recorded | not recorded | orchestrator | decided |
| 135 | Releases: a GitHub Actions workflow builds the wheel and sdist when a `v*` tag is pushed, runs the tests and attaches the files to a GitHub Release. v0.1.0 is cut only after the review gates pass. GitHub Packages is not used. PyPI publishing waits until the repo is public and the owner has a PyPI account. | Pinned, tested, installable snapshots with release notes. GitHub Packages has no Python registry. | Publishing to GitHub Packages; publishing to PyPI now. | owner | decided |

## Open

Waiting on the owner:

1. Final repository name (#35). The reason is not recorded because the decision is not made yet.
2. Reason for the Python 3.11 minimum (#31) is not recorded.

Decided, but the owner may still change them:

1. Default drafting model (#16).
2. Server-side fallback in the AI drafting call (#93). The build worker switched it on from the SDK's guidance. The owner may want it off.

Reason not recorded (build workers gave none):

Rows #36, #39, #40, #42, #44, #46, #51, #53, #55, #56, #57, #58, #62, #68, #72, #74, #75, #83, #85, #90, #92, #94, #95, #96, #101, #102, #106, #113, #115, #121. Ask the worker or the owner if any of these matter.

Left for later by the build workers:

1. Mapping the portals filters into preferences needs a ruling (see the `import-portals` row).
2. There is no "willing to relocate" field in the preferences, so an on-site job elsewhere scores 0 on location and is not made ineligible.
3. Ashby internal-posting detection is not built.
4. There is no `--retry` for jobs held as waiting for the human (apply).
5. Ashby education-history fields are reported as a problem by the filler.
6. Excel and Numbers have not opened the tracker file by hand (see `docs/TESTS.md`).
