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

Last updated: 2026-11-27, after wave 1. The full suite has 409 passing tests.

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
| `tests/core/test_store.py` | Upserts sort jobs into new, changed and unchanged and keep first seen; automatic status only moves forward, manual can go back, and automatic closed never follows applied; open queue items are not duplicated and resolve by kind; the ledger returns the last status; a bad JSONL line is named. | Setup and workspace (SET-11, SET-13); Sourcing (SRC-5); Queue and tracking (TRK-3, TRK-6, TRK-7, TRK-8) | passing |
| `tests/core/test_http.py` | Retries on 503, no retry on 404, `Retry-After` is honoured, bot walls stop at once, cache hits and ETag revalidation work, robots.txt can block, per-host spacing holds, and the fixture transport tries routes, then paths, then fails clearly. | Sourcing (SRC-18 to SRC-24) | passing |
| `tests/core/test_textutil.py` | Double-escaped HTML and lists become clean text, labels such as "First Name*" and "first name (required)" normalise to the same value, and invisible characters are stripped. | Sourcing (SRC-25) | passing |
| `tests/core/test_output_yaml_settings.py` | Human and JSON output modes, cell truncation, YAML round trip and errors, settings defaults from file and env, and the network block in tests. | Setup and workspace (SET-7, SET-9) | passing |
| `tests/core/test_cli.py` | `--version` works; a missing workspace gives exit code 2, a `hint:` line and no traceback; `init --demo` creates the workspace and the demo PDF. | Setup and workspace (SET-4, SET-6, SET-7) | passing |
| `tests/test_scan_sensitive.py` | In a temp git repo, planted secrets are found in the tree and in history (including a deleted file and an author email); denylist terms are masked; a clean repo exits 0; an `example.com` email and `+1 555 0100` are not findings. | Privacy guardrails (PRV-3 to PRV-6) | passing |

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
| `test_pipeline.py` | A second run gives an empty diff, a vanished job is marked closed with an event, a failed board never closes jobs, a bot wall skips the rest of that ATS, and feed jobs are stored but never closed. | Sourcing (SRC-1 to SRC-4, SRC-21, SRC-26) | passing |
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
| `tests/plan/test_options.py` | Exact and yes/no matches work, decline variants match, years land in the right range (4 in "3-5", 12 in "10+", 1 in "0-2"), unclear options give no match, and the first option is never a fallback. | Planning answers (ANS-8, ANS-9) | passing |
| `tests/plan/test_rules.py` | One test per rule category, plus the over-match fixes, AI questions never answered automatically, and a missing profile field becoming unknown. | Planning answers (ANS-3, ANS-6, ANS-10) | passing |
| `tests/plan/test_schema.py` | Greenhouse and Ashby question fixtures parse, Ashby falls back to the page reader (mocked) when the request fails, the offline demo never opens a browser, messy payloads degrade, and the schema cache holds for 24 hours. | Planning answers (ANS-1, ANS-18) | passing |
| `tests/plan/test_planner.py` | The demo plan goes from `needs_answers` to `ready` after answering, a second run uses the cache, automation refusal blocks the plan, and the queue item is added and then resolved. | Planning answers (ANS-2, ANS-4, ANS-5, ANS-7, ANS-11, ANS-14) | passing |
| `tests/plan/test_unknowns.py` | Unknown questions are deduplicated across jobs. | Planning answers (ANS-12) | passing |
| `tests/plan/test_draft.py` | With a fake provider: the budget stops calls, a cache hit makes no call, factual questions are never drafted, and drafts are marked `needs_review`. | Planning answers (ANS-15, ANS-16) | passing |
| `tests/plan/test_cli.py` | `plan`, `plan show`, `plan unknowns`, `plan answer`, `plan review`, `plan draft` and `plan approve` run, and a missing workspace gives the friendly error. | Planning answers (ANS-12, ANS-13, ANS-19); Setup and workspace (SET-6) | passing |

### Wave 2: applying

| Suite | What it proves | SPEC area (rows) | Status |
|---|---|---|---|
| `tests/apply/test_greenhouse_fill.py` (browser) | A dry run fills every field and never clicks submit, a type-ahead select with no match is a problem, the education repeater fills, and location type-ahead needs a match. | Applying (APP-2, APP-8) | planned |
| `tests/apply/test_ashby_fill.py` (browser) | A dry run fills booleans, choices, location and number fields. | Applying (APP-2, APP-8) | planned |
| `tests/apply/test_guards.py` (browser) | The CAPTCHA variant stops and queues, and the account and no-automation variants stop. | Applying (APP-5, APP-6, APP-7, APP-15) | planned |
| `tests/apply/test_runner.py` (browser) | A second run skips, the per-company cap and exclusion list hold, the hold code flow works with a stand-in human, a closed window moves on to the next job, and submit is refused without opt-in or with an unreviewed draft. | Applying (APP-3, APP-4, APP-9, APP-10, APP-11) | planned |
| `tests/apply/` (file not named yet) `test_ledger_has_no_answer_text` | The ledger never contains answer text. Runs without a browser. | Applying (APP-12) | planned |

### Wave 2: queue, tracker and token saving

| Suite | What it proves | SPEC area (rows) | Status |
|---|---|---|---|
| `tests/report/test_xlsx.py` | Sheets, columns, the status drop-down and links are present, and importing the same edits twice records each change once. | Excel and Markdown tracker (XLS-2 to XLS-5, XLS-7, XLS-8) | planned |
| `tests/report/test_md.py` | The Markdown tracker is written. | Excel and Markdown tracker (XLS-9) | planned |
| `tests/track/test_track_cli.py` | A manual status can go backward, stats counts are right, and ghosting waits for the set number of days. | Queue and tracking (TRK-6, TRK-9, TRK-10) | planned |
| `tests/queue/test_queue_cli.py` | The `getmeajob queue` commands work (test names not set yet). | Queue and tracking (TRK-1, TRK-4) | planned |
| `tests/tokens/test_status.py` | `getmeajob status` fits in 40 lines. | Token saving (TOK-1) | planned |
| `tests/tokens/test_context.py` | `getmeajob context` stays under 2,000 characters. | Token saving (TOK-2) | planned |
| `tests/tokens/test_estimate.py` | `getmeajob tokens estimate` reports characters divided by 4. | Token saving (TOK-3) | planned |

### Wave 2: agents and MCP

| Suite | What it proves | SPEC area (rows) | Status |
|---|---|---|---|
| `tests/agents/test_assets.py` | Every command file has a `description` in its frontmatter, refers only to real CLI commands, and contains no forbidden words. | Agents and MCP (AGT-10) | planned |
| `tests/mcp/test_server.py` | Tools carry the `getmeajob_` prefix, and `getmeajob_status` on the demo returns under 2,000 characters. Skipped when the `mcp` extra is missing. | Agents and MCP (AGT-6, AGT-8) | planned |

## Review focus

These five failure modes count as bugs even if everything else works. Each is pinned by the tests named here.

| # | Failure mode | What must happen | Pinned by |
|---|---|---|---|
| 1 | Messy API payloads: null or "None" ids, missing fields, a location given as a list or a stringified list, double-escaped HTML, invisible Unicode. | Sources and the planner do not crash. The item is skipped or degraded, with a recorded reason. | `tests/sources/test_greenhouse.py::test_skips_null_ids`, `tests/core/test_textutil.py::test_html_to_text_double_escaped_and_lists`, `tests/core/test_textutil.py::test_strip_invisible`. Planner side: `tests/plan/test_schema.py::test_messy_payload_degrades`. |
| 2 | Running a command twice. | `source` gives no duplicates and an empty diff, `plan` reuses the cached plan, `apply` skips by job key, and `track import-xlsx` writes no duplicate events. | `tests/sources/test_pipeline.py::test_second_run_is_empty_diff`, `tests/plan/test_planner.py::test_second_plan_run_uses_cache`, `tests/apply/test_runner.py::test_idempotent_second_run_skips`, `tests/report/test_xlsx.py::test_roundtrip_import_records_changes_once` |
| 3 | First run on an empty or missing workspace. | Every command prints a friendly message pointing to `getmeajob init`, exits with code 2, and shows no traceback. | `tests/core/test_cli.py::test_unknown_workspace_friendly_error`, `tests/core/test_workspace.py::test_require_missing_raises_with_hint`, and `test_missing_workspace_friendly` in the CLI test of each wave 1 package (`tests/sources/test_cli.py`, `tests/rank/test_cli.py`, `tests/resume/test_cli.py`, `tests/plan/test_cli.py`) |
| 4 | Ambiguous options, such as "Yes, I will require sponsorship" and "Yes, I have sponsorship". | The matcher refuses to guess and returns no match with a reason. | `tests/plan/test_options.py::test_ambiguous_returns_none`, `tests/plan/test_options.py::test_never_first_option` |
| 5 | The person closes the browser window during a hold, or a page crashes. | That job is recorded as `closed_by_user` or `error`, and the run continues with the next job. | `tests/apply/test_runner.py::test_window_closed_continues_next_job` |

## Known gaps

By design:

1. There are no live-network tests. Tests use recorded fixtures and mock transports, so a change in a real ATS API only shows up in real use.
2. Browser tests need Chromium (`playwright install chromium`). The default `pytest -m "not browser"` run skips them.
3. Real ATS pages can change their markup. The mock forms only prove our widget logic, not that real Greenhouse or Ashby pages still match it.
4. CI scans with generic patterns only. Denylist checks run only on a machine where `GETMEAJOB_DENYLIST` is set.
5. MCP tests skip when the `mcp` extra is not installed.

Open items the wave 1 builders named:

1. The live terms pages of the job feeds were not re-checked. The attribution rules in `docs/sources.md` are paraphrased.
2. The Greenhouse education shape and the Ashby form request are checked only against synthetic fixtures, not live APIs.
3. The rendered-page Ashby reader is only unit-tested (its parser). It has not run against a real page.
4. `plan K1 --refresh K2` errors by design, and no test covers that limit.

Not yet covered by the plan:

1. `test_ledger_has_no_answer_text` has no file yet.
2. Test names are not set for `tests/queue/test_queue_cli.py`, `tests/tokens/test_estimate.py` and `tests/report/test_md.py`.
3. Some SPEC rows have no planned test yet. Some of these get checked by hand or by CI. The wave 1 rows were not fully re-audited, so treat this table as a floor.

| SPEC area | Rows with no planned test |
|---|---|
| Setup and workspace | SET-1, SET-3, SET-5, SET-8, SET-9, SET-10, SET-14 |
| Sourcing | SRC-10 |
| Ranking | none known |
| Planning answers | ANS-17 |
| Applying | APP-1, APP-13, APP-14 |
| Queue and tracking | TRK-2, TRK-5 |
| Excel and Markdown tracker | XLS-1, XLS-6 |
| Resumes per role | RES-3 |
| Token saving | TOK-4, TOK-5 |
| Agents and MCP | AGT-1, AGT-2, AGT-3, AGT-4, AGT-5, AGT-7, AGT-9 |
| Privacy guardrails | PRV-1, PRV-2, PRV-7, PRV-8, PRV-9, PRV-10 |
