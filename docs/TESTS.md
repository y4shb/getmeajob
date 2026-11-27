# Tests

In short: run these five commands from the repo root. They need no network and no browser.

```
pip install -e ".[dev]"
ruff check .
ruff format --check .
mypy
pytest -m "not browser"
```

Browser tests (form filling and resume PDFs) need Chromium first:

```
pip install -e ".[browser]"
playwright install chromium
pytest -m browser
```

The privacy scanner checks the current files and the full git history:

```
python scripts/scan_sensitive.py --tree --history
```

To also check your private denylist, point the scanner at it with `GETMEAJOB_DENYLIST`:

```
GETMEAJOB_DENYLIST=/path/to/your/denylist.txt python scripts/scan_sensitive.py --tree --history
```

The scanner exits 0 when clean, 1 when it finds something, and 2 on a usage error. It never prints a denylist term in full.

Last updated: 2026-11-27, after the release milestone. The full suite has 621 passing tests, with 0 skipped when the dev extras are installed. The packaging test needs hatchling, which is a dev dependency.

## How the tests are set up

1. `tests/conftest.py` blocks network connections to anything except 127.0.0.1 and ::1, so a test that tries to go online fails.
2. HTTP tests use recorded fixtures (`FixtureTransport`) or `httpx.MockTransport`, with a fake `sleep` so retries run instantly.
3. Tests marked `browser` need Chromium. Tests marked `slow` take longer.
4. CI (GitHub Actions) runs lint, types, the non-browser tests and the scanner on Python 3.11 and 3.12. A second job runs the browser tests.
5. Before a release, the full check is `pip install -e ".[dev,browser,llm,mcp]"`, the commands above, a plain `pytest`, and `bash scripts/quickstart.sh`.

## Suites

Each row names a test file, what it proves, and the `docs/SPEC.md` area and rows it covers. Status is `passing` (the suite exists and passes), `in progress` or `planned` (not written yet).

### Wave 0: core

| Suite | What it proves | SPEC area (rows) | Status |
|---|---|---|---|
| `tests/core/test_models.py` | Every data model survives a `to_dict` and `from_dict` round trip, unknown keys are ignored, and job keys come out as `ats:board:job_id`. | Setup and workspace (SET-11, SET-12) | passing |
| `tests/core/test_workspace.py` | `--home` beats `GETMEAJOB_HOME`, which beats `./workspace`; file names are safe and capped; a missing workspace raises an error with a hint. | Setup and workspace (SET-2, SET-6, SET-12) | passing |
| `tests/core/test_store.py` | Upserts sort jobs into new, changed and unchanged and keep first seen; automatic status only moves forward, manual can go back, and automatic closed never follows applied; open queue items are not duplicated and resolve by kind; the ledger returns the last status; a bad JSONL line is named; sourcing never reopens a job a person closed. | Setup and workspace (SET-11, SET-13); Sourcing (SRC-5); Queue and tracking (TRK-3, TRK-6, TRK-7, TRK-8) | passing |
| `tests/core/test_http.py` | Retries on 503, no retry on 404, `Retry-After` is honoured, bot walls stop at once, cache hits and ETag revalidation work, robots.txt can block, per-host spacing holds, and the fixture transport tries routes, then paths, then fails clearly. Private addresses and redirects to them are refused, a name that resolves to a private address is refused, robots.txt is checked on every redirect, and the redirect and 10 MB reply caps hold. | Sourcing (SRC-18 to SRC-24, SRC-28) | passing |
| `tests/core/test_textutil.py` | Double-escaped HTML and lists become clean text, labels such as "First Name*" and "first name (required)" normalise to the same value, and invisible characters are stripped. Two tables pin the no-automation detector: 20 notices are found and 18 harmless sentences (including employers describing their own tools) are not. | Sourcing (SRC-25); Planning answers (ANS-20) | passing |
| `tests/core/test_packaging.py` (slow) | The sdist, built with hatchling, ships the plugin files, the docs, NOTICE and the examples. | Docs and releases (REL-1) | passing |
| `tests/core/test_output_yaml_settings.py` | Human and JSON output modes, cell truncation, YAML round trip and errors, settings defaults from file and env, and the network block in tests. | Setup and workspace (SET-7, SET-9) | passing |
| `tests/core/test_cli.py` | `--version` works; a missing workspace gives exit code 2, a `hint:` line and no traceback; `init --demo` creates the workspace and the demo PDF. | Setup and workspace (SET-4, SET-6, SET-7) | passing |
| `tests/test_scan_sensitive.py` | In a temp git repo, planted secrets are found in the tree and in history (including a deleted file and an author email); denylist terms are masked; a clean repo exits 0; an `example.com` email and `+1 555 0100` are not findings. `--all-objects` finds orphaned and reflog-only objects, and a usage error exits 2. | Privacy guardrails (PRV-3 to PRV-6, PRV-12) | passing |
| `tests/test_quickstart.py` | `bash scripts/quickstart.sh` runs the README quick start end to end on a fresh folder and ends with both demo jobs `dry_ok`. It refuses a folder that is not empty. | Setup and workspace (SET-14) | passing |

### Wave 1: sources

All in `tests/sources/`, with recorded files in `tests/sources/fixtures/`.

| Suite | What it proves | SPEC area (rows) | Status |
|---|---|---|---|
| `test_greenhouse.py` | Fixture jobs parse, a timeout falls back to the list without full text, and null ids are skipped. | Sourcing (SRC-8, SRC-9) | passing |
| `test_ashby.py` | Unlisted jobs are skipped and secondary locations are joined. | Sourcing (SRC-8) | passing |
| `test_lever.py` | A 404 on the main host falls back to the EU host. | Sourcing (SRC-8) | passing |
| `test_smartrecruiters.py`, `test_workable.py`, `test_recruitee.py` | A fixture board parses into jobs for each. | Sourcing (SRC-6) | passing |
| `test_feeds.py` | RemoteOK's legal notice is skipped, HN posts parse by the pipe convention, and ATS boards are harvested from links. | Sourcing (SRC-7, SRC-26) | passing |
| `test_registry.py` | Sources are found through the registry. | Sourcing (SRC-6) | passing |
| `test_pipeline.py` | A second run gives an empty diff, a vanished job is marked closed with an event, a failed board never closes jobs, a bot wall skips the rest of that ATS, and feed jobs are stored but never closed. Sourcing reopens only jobs it closed. | Sourcing (SRC-1 to SRC-4, SRC-21, SRC-26) | passing |
| `test_discover.py` | URL inputs parse directly, slug guesses follow the rules, and a board whose name does not match is rejected. | Sourcing (SRC-11, SRC-12) | passing |
| `test_portals_yaml.py` | Entries map to boards, unsupported ones are reported, and title filters follow `word:`, `stem:` and ` + `. | Sourcing (SRC-14) | passing |
| `test_liveness.py` | A 403 gives unknown, a 404 gives closed, and closed-page text gives closed. | Sourcing (SRC-15) | passing |
| `test_jd.py` | The digest is at most 12 lines. | Sourcing (SRC-16) | passing |
| `test_cli.py` | `source` on the offline demo prints the diff; `--limit` and `--json` work; `boards`, `jd` and `check-live` run; `discover` writes only with `--write`; `import-portals` runs; a missing workspace gives the friendly error. | Sourcing (SRC-2, SRC-13, SRC-16, SRC-17, SRC-27); Setup and workspace (SET-6) | passing |

### Wave 1: ranking and resumes

| Suite | What it proves | SPEC area (rows) | Status |
|---|---|---|---|
| `tests/rank/test_yoe.py` | Ranges, "5+", number words and "yrs" parse; "founded 20 years ago" and "a 10 year old company" are ignored; required beats preferred. | Ranking (RANK-5) | passing |
| `tests/rank/test_location.py` | Each demo job gets its expected tier, and "Remote - US" plus US work authorization gives `region_restricted`. | Ranking (RANK-6, RANK-7) | passing |
| `tests/rank/test_eligibility.py` | Eligibility flags come out with the right codes and reasons. | Ranking (RANK-3) | passing |
| `tests/rank/test_skills.py` | "go to market" does not count as Go. | Ranking (RANK-8) | passing |
| `tests/rank/test_score.py` | The eight demo jobs get the expected eligibility, and every reason is a short line. | Ranking (RANK-2, RANK-10) | passing |
| `tests/rank/test_prefs.py` | The preferences schema loads, the demo values are right, bad values give a friendly error, and missing sections use defaults. | Ranking (RANK-4) | passing |
| `tests/rank/test_rank_all.py` | Every open job is written to `ranked.jsonl`, good ones are shortlisted, `--min-score` trims only the printed list, a second run changes nothing, and closed jobs are not ranked. | Ranking (RANK-1, RANK-9) | passing |
| `tests/rank/test_cli.py` | `rank` and `explain` run, and a missing workspace gives the friendly error. | Ranking (RANK-11); Setup and workspace (SET-6) | passing |
| `tests/resume/test_bank.py` | The demo bank loads, its hash is stable, and bad or missing banks give friendly errors. | Resumes per role (RES-1) | passing |
| `tests/resume/test_tailor.py` | Only bank text is used, gaps are never added, skills named by the job move first but none are added, the folder layout is right, and the output is the same on every run. | Resumes per role (RES-2 to RES-6) | passing |
| `tests/resume/test_keywords.py` | Job keywords are found and resume coverage is reported. | Resumes per role (RES-8) | passing |
| `tests/resume/test_lint.py` | Lint warnings fire for weak openers, stock phrases, invisible characters and em dashes, and en-dash ranges pass. | Resumes per role (RES-10) | passing |
| `tests/resume/test_render.py` (browser) | A one-page PDF is written, an overflowing resume is compacted, short wordings are tried before bullets are dropped, and a resume that cannot fit gives a clear error. | Resumes per role (RES-7) | passing |
| `tests/resume/test_store.py` | Role resumes are listed, `pick` prefers the role that lists the key or the best keyword match, and roles without a PDF are ignored. | Resumes per role (RES-9, RES-11) | passing |
| `tests/resume/test_cli.py` | `tailor`, `list`, `pick`, `keywords`, `lint` and `render` run, and a missing workspace gives the friendly error. | Resumes per role (RES-2, RES-8 to RES-11); Setup and workspace (SET-6) | passing |

### Wave 1: planning answers

| Suite | What it proves | SPEC area (rows) | Status |
|---|---|---|---|
| `tests/plan/test_options.py` | Exact and yes/no matches work, decline variants match, years land in the right range (4 in "3-5", 12 in "10+", 1 in "0-2"), unclear options give no match, and the first option is never a fallback. A negated option never matches its opposite (veteran, authorized and sponsorship pairs). | Planning answers (ANS-8, ANS-9) | passing |
| `tests/plan/test_rules.py` | One test per rule category, plus the over-match fixes, AI questions never answered automatically, and a missing profile field becoming unknown. | Planning answers (ANS-3, ANS-6, ANS-10) | passing |
| `tests/plan/test_schema.py` | Greenhouse and Ashby question fixtures parse, Ashby falls back to the page reader (mocked) when the request fails, the offline demo never opens a browser, messy payloads degrade, and the schema cache holds for 24 hours. | Planning answers (ANS-1, ANS-18) | passing |
| `tests/plan/test_planner.py` | The demo plan goes from `needs_answers` to `ready` after answering, a second run uses the cache, automation refusal blocks the plan (including a notice in the job text), file answers stay inside the workspace, plans stay current when the workspace moves, and the queue item is added and then resolved. | Planning answers (ANS-2, ANS-4, ANS-5, ANS-7, ANS-11, ANS-14, ANS-20 to ANS-22) | passing |
| `tests/plan/test_unknowns.py` | Unknown questions are deduplicated across jobs. | Planning answers (ANS-12) | passing |
| `tests/plan/test_draft.py` | With a fake provider: the budget stops calls, a cache hit makes no call, factual questions are never drafted, and drafts are marked `needs_review`. Employer text cannot close the prompt tags, a reply cut at max tokens is not saved, and the default budget fits 5 drafts. | Planning answers (ANS-15, ANS-16) | passing |
| `tests/plan/test_cli.py` | `plan`, `plan show`, `plan unknowns`, `plan answer`, `plan review`, `plan draft` and `plan approve` run, and a missing workspace gives the friendly error. | Planning answers (ANS-12, ANS-13, ANS-19); Setup and workspace (SET-6) | passing |

### Wave 2: applying

Browser suites need Chromium and run under `pytest -m browser`.

| Suite | What it proves | SPEC area (rows) | Status |
|---|---|---|---|
| `tests/apply/test_greenhouse_fill.py` (browser) | A dry run fills every field and never clicks submit, a type-ahead select with no match is a problem, the education repeater fills, and location type-ahead needs a match. A file outside the workspace is never attached, and an untyped Add another button is never clicked. | Applying (APP-2, APP-8, APP-17, ANS-22) | passing |
| `tests/apply/test_ashby_fill.py` (browser) | A dry run fills booleans, choices, location and number fields, and a yes/no or choice field with no clear match is not guessed. Buttons that would submit are never clicked. | Applying (APP-2, APP-8, APP-17) | passing |
| `tests/apply/test_guards.py` (browser) | The CAPTCHA variant stops and queues, the account and no-automation variants stop, the detectors stay quiet on plain forms, and error, success and code pages are read. A notice above the form stops every mode, and job text about bots is not a stop. | Applying (APP-5, APP-6, APP-7, APP-15, ANS-20) | passing |
| `tests/apply/test_runner.py` (browser) | A second run skips, the per-company cap and exclusion list hold, the hold code flow works with a stand-in human, a closed window or a page crash moves on to the next job, and submit is refused without opt-in or with an unreviewed draft. An error after the click never clicks twice, and any non-submitted outcome after the click is `awaiting_human`. Success text already on the page is ignored, jobs you ruled out are never opened, and a stale plan is refused. | Applying (APP-3, APP-4, APP-9, APP-10, APP-11, APP-16, APP-18, APP-19, ANS-24) | passing |
| `tests/apply/test_ledger.py` | The ledger and queue never contain answer text. The answers digest changes only when answers change. A good dry run resolves a fill-problem item. Runs without a browser. | Applying (APP-12) | passing |
| `tests/apply/test_policy.py` | Preference defaults and errors, exclusion matching, duplicate and waiting-job rules, the 30-day cap and the not-ready rules. Jobs you ruled out are never opened. | Applying (APP-4, APP-9, APP-10, APP-16) | passing |
| `tests/apply/test_values.py` | Number, date and phone values are coerced, employment rows come from the profile, the degree is matched by level, and the location pick is never the first suggestion by default. | Applying (APP-8) | passing |
| `tests/apply/test_cli.py` | Missing workspace gives the friendly error, submit is refused, hold needs a window, a missing Playwright gives a hint, and `inspect` lists fields and options. | Applying (APP-4, APP-14); Setup and workspace (SET-6) | passing |

### Wave 2: queue, tracker and token saving

| Suite | What it proves | SPEC area (rows) | Status |
|---|---|---|---|
| `tests/report/test_xlsx.py` | Sheets, columns, the status drop-down and links are present. Importing the same edits twice records each change once. A rewrite keeps edits not yet imported, and an old copy cannot undo newer changes. Unknown statuses are reported, not recorded. Text never becomes a formula, a long description is capped, and an unreadable file is never overwritten. | Excel and Markdown tracker (XLS-2 to XLS-8) | passing |
| `tests/report/test_md.py` | The Markdown tracker groups jobs by status in ladder order, stays short on the demo, escapes cells and handles an empty workspace. | Excel and Markdown tracker (XLS-9) | passing |
| `tests/track/test_track_cli.py` | A manual status can go backward, setting the same status writes nothing, stats counts are right, ghosting waits for the set number of days, and setting applied resolves open queue items. | Queue and tracking (TRK-6, TRK-7, TRK-9, TRK-10) | passing |
| `tests/track/test_notes.py` | The same note value writes nothing, and clearing a note is recorded. | Excel and Markdown tracker (XLS-7, XLS-8) | passing |
| `tests/queue/test_queue_cli.py` | Every kind has a "what we need" line, groups follow a fixed order, add and resolve work, and an empty queue says so. | Queue and tracking (TRK-1, TRK-2, TRK-3, TRK-4) | passing |
| `tests/tokens/test_status.py` | `getmeajob status` fits in 40 lines and gives the next command, including on an empty workspace. It suggests `plan` when a ready plan is stale, the hold run after a dry run, and nothing once the tracker is current. | Token saving (TOK-1); Planning answers (ANS-24) | passing |
| `tests/tokens/test_context.py` | `getmeajob context` stays under 2,000 characters, even for a messy job. | Token saving (TOK-2) | passing |
| `tests/tokens/test_estimate.py` | `getmeajob tokens estimate` reports characters divided by 4, works without a workspace, and gives a friendly error for a missing file. | Token saving (TOK-3) | passing |

### Wave 2: agents, MCP and quick start

| Suite | What it proves | SPEC area (rows) | Status |
|---|---|---|---|
| `tests/agents/test_assets.py` | The ten commands and the skill exist with frontmatter, every CLI command they mention exists, manifests point at real paths, the policy is linked from every command, plugin copies match the canonical files, and there are no forbidden words, long dashes, long lists or personal data. | Agents and MCP (AGT-1 to AGT-5, AGT-10) | passing |
| `tests/agents/test_cli.py` | `agents list` needs no workspace, `--flat` install copies commands and never overwrites without `--force`, the plugin steps print without `--flat`, and an installed wheel names the repository from its metadata. | Agents and MCP (AGT-3) | passing |
| `tests/mcp/test_server.py` | The tool list is exactly the `getmeajob_` tools, read tools stay under 2,000 characters, empty answers are refused, answers are saved and used by the plan, errors come back as text, and a real stdio server lists its tools. Skipped when the `mcp` extra is missing. | Agents and MCP (AGT-6 to AGT-8) | passing |
| `tests/mcp/test_tools_and_config.py` | Long text is clipped, an answer needs one scope, an agent answer waits for review before submit, file questions are refused, and the config snippets parse. | Agents and MCP (AGT-7, AGT-9, ANS-22, ANS-23) | passing |

## Review focus

These five failure modes count as bugs even if everything else works. Each is pinned by the tests named here.

| # | Failure mode | What must happen | Pinned by |
|---|---|---|---|
| 1 | Messy API payloads: null or "None" ids, missing fields, a location given as a list or a stringified list, double-escaped HTML, invisible Unicode. | Sources and the planner do not crash. The item is skipped or degraded, with a recorded reason. | `tests/sources/test_greenhouse.py::test_skips_null_ids`, `tests/core/test_textutil.py::test_html_to_text_double_escaped_and_lists`, `tests/core/test_textutil.py::test_strip_invisible`. Planner side: `tests/plan/test_schema.py::test_messy_payload_degrades`. |
| 2 | Running a command twice. | `source` gives no duplicates and an empty diff, `plan` reuses the cached plan, `apply` skips by job key, and `track import-xlsx` writes no duplicate events. | `tests/sources/test_pipeline.py::test_second_run_is_empty_diff`, `tests/plan/test_planner.py::test_second_plan_run_uses_cache`, `tests/apply/test_runner.py::test_idempotent_second_run_skips`, `tests/report/test_xlsx.py::test_roundtrip_import_records_changes_once` |
| 3 | First run on an empty or missing workspace. | Every command prints a friendly message pointing to `getmeajob init`, exits with code 2, and shows no traceback. | `tests/core/test_cli.py::test_unknown_workspace_friendly_error`, `tests/core/test_workspace.py::test_require_missing_raises_with_hint`, and `test_missing_workspace_friendly` in the CLI test of each wave 1 package (`tests/sources/test_cli.py`, `tests/rank/test_cli.py`, `tests/resume/test_cli.py`, `tests/plan/test_cli.py`) |
| 4 | Ambiguous options, such as "Yes, I will require sponsorship" and "Yes, I have sponsorship". | The matcher refuses to guess and returns no match with a reason. | `tests/plan/test_options.py::test_ambiguous_returns_none`, `tests/plan/test_options.py::test_never_first_option` |
| 5 | The person closes the browser window during a hold, or a page crashes. | That job is recorded as `closed_by_user` or `error`, and the run continues with the next job. | `tests/apply/test_runner.py::test_window_closed_continues_next_job`, `tests/apply/test_runner.py::test_page_crash_is_an_error_and_the_run_goes_on` |

## Verified at release

These checks passed for v0.1.0:

1. CI on GitHub passes: the Python 3.11 and 3.12 jobs and the browser-tests job.
2. A fresh clone in a new virtualenv, installed with `pip install -e ".[dev,browser,llm,mcp]"`, passed ruff, ruff format, mypy (126 files) and 621 tests.
3. The quick start filled both demo forms.
4. A fresh install pulls the newest Playwright. Run `playwright install chromium` before the browser tests, or they fail.

## Known gaps

By design:

1. There are no live-network tests. Tests use recorded fixtures and mock transports, so a change in a real ATS API only shows up in real use.
2. Browser tests need Chromium (`playwright install chromium`). The default `pytest -m "not browser"` run skips them.
3. Real ATS pages can change their markup. The mock forms only prove our widget logic, not that real Greenhouse or Ashby pages still match it.
4. CI scans with generic patterns only. Denylist checks run only on a machine where `GETMEAJOB_DENYLIST` is set.
5. MCP tests skip when the `mcp` extra is not installed.
6. Headed hold mode has not run in a real visible window. Tests use a stand-in human in headless Chromium.
7. The Excel file was checked with openpyxl only, not in Excel, LibreOffice or Numbers.
8. Feed terms pages need a manual check. v0.1.0 shipped without it.
9. The Mermaid diagrams in the docs were not render-checked on GitHub.

Open items the wave 1 builders named:

1. The live terms pages of the job feeds were not re-checked. The attribution rules in `docs/sources.md` are paraphrased.
2. The Greenhouse education shape and the Ashby form request are checked only against synthetic fixtures, not live APIs.
3. The rendered-page Ashby reader is only unit-tested (its parser). It has not run against a real page.
4. `plan K1 --refresh K2` errors by design, and no test covers that limit.

Open items the wave 2 builders named:

1. Ashby education-history fields are reported as a problem, and no test covers a fix.
2. There is no retry option for jobs waiting on the human, so no test exists for one.

Not yet covered by the plan:

1. Some SPEC rows have no planned test yet. Some of these get checked by hand or by CI. The wave 1 rows were not fully re-audited, so treat this table as a floor.

| SPEC area | Rows with no planned test |
|---|---|
| Setup and workspace | SET-1, SET-3, SET-5, SET-8, SET-9, SET-10, SET-15 |
| Sourcing | SRC-10 |
| Ranking | none known |
| Planning answers | ANS-17 |
| Applying | APP-1, APP-13 |
| Queue and tracking | TRK-5, TRK-7, TRK-8 |
| Excel and Markdown tracker | XLS-1, XLS-6 |
| Resumes per role | RES-3 |
| Token saving | TOK-4, TOK-5 |
| Agents and MCP | AGT-2 |
| Docs and releases | DOC-1, DOC-2 |
| Privacy guardrails | PRV-1, PRV-2, PRV-7, PRV-8, PRV-9, PRV-10, PRV-11, PRV-13 |
