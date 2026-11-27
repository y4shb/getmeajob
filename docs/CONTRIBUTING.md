# Contributing

In short: set up a virtual environment with every extra, install the git hook once, and run the checks below before each commit. Use synthetic data only, keep each commit to one reviewable change, and your work is shared under Apache-2.0.

## Set up

You need Python 3.11 or newer and git. Setup takes about 3 minutes on a typical connection, mostly the Chromium download.

1. Make and activate a virtual environment.
   ```sh
   python3 -m venv .venv && source .venv/bin/activate
   ```
2. Install getmeajob in editable mode with every extra.
   ```sh
   pip install -e ".[dev,browser,llm,mcp]"
   ```
3. Install the browser that the form filler and resume PDFs use.
   ```sh
   playwright install chromium
   ```
4. Install the pre-commit hook, which runs the privacy scanner on staged files.
   ```sh
   bash scripts/install-git-hooks.sh
   ```
5. Check that it all works. The script runs the quick start on the demo and ends with the paths of the Excel tracker and the screenshots.
   ```sh
   bash scripts/quickstart.sh
   ```

## Checks before a commit

Run these from the repo root. CI runs the first four on Python 3.11 and 3.12, the browser tests in a separate job, and the scanner on the full history.

1. Lint: `ruff check .`
2. Format: `ruff format --check .` (lines up to 100 characters)
3. Types: `mypy` (strict, on `src/`)
4. Tests without a browser: `pytest -m "not browser"`. Then the browser tests: `pytest -m browser`. The `slow` marker covers tests that take more than a few seconds, such as `tests/test_quickstart.py`.
5. Privacy: `python scripts/scan_sensitive.py --tree --history`. Set `GETMEAJOB_DENYLIST` first if you keep a private list of terms.

If you change what getmeajob does, update `docs/SPEC.md` (the behaviour), `docs/TESTS.md` (which test proves it) and `docs/DECISIONS.md` (why, and what you rejected) in the same change.

## Add a job source plugin

A plugin is its own small Python package. It needs one class that follows the `Source` protocol in `src/getmeajob/sources/base.py`: a `name` and three methods. This example reads a made-up board API:

```python
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from getmeajob.http import HttpClient
from getmeajob.models import Board, Job
from getmeajob.sources.base import ProbeResult, SourceResult

API = "https://api.myboard.example/v1/boards/{slug}/jobs"


class MyBoardSource:
    name = "myboard"  # the `ats` value people write in companies.yaml

    def list_jobs(self, board: Board, client: HttpClient) -> SourceResult:
        resp = client.get(API.format(slug=board.slug), ttl=6 * 3600)
        if resp.status == 404:
            return SourceResult(found=False, jobs=[])
        if resp.status != 200:
            return SourceResult(found=False, jobs=[], error=f"HTTP {resp.status}")
        data = resp.json()
        jobs: list[Job] = []
        skipped: list[str] = []
        for item in data.get("jobs", []):
            job = self._job(board, item)
            if isinstance(job, str):
                skipped.append(job)
            else:
                jobs.append(job)
        return SourceResult(True, jobs, data.get("name"), skipped=skipped)

    def probe(self, slug: str, client: HttpClient) -> ProbeResult:
        resp = client.get(API.format(slug=slug), ttl=7 * 86400)
        if resp.status != 200:
            return ProbeResult(found=False, board_name=None, count=0)
        data = resp.json()
        return ProbeResult(True, data.get("name"), len(data.get("jobs", [])))

    def parse_url(self, url: str) -> str | None:
        parts = urlsplit(url)
        path = [p for p in parts.path.split("/") if p]
        if parts.hostname == "jobs.myboard.example" and path:
            return path[0]
        return None

    def _job(self, board: Board, item: dict[str, Any]) -> Job | str:
        job_id = str(item.get("id") or "").strip()
        if job_id in ("", "None", "null"):
            return "no usable id"
        if not item.get("title"):
            return f"job {job_id}: no title"
        return Job(
            key=Job.make_key(self.name, board.slug, job_id),
            ats=self.name,
            board=board.slug,
            job_id=job_id,
            company=board.company,
            title=str(item["title"]),
            url=str(item.get("url") or f"https://jobs.myboard.example/{board.slug}/{job_id}"),
            location=str(item.get("location") or ""),
            description=str(item.get("text") or ""),
        )
```

Then register it in the plugin's `pyproject.toml`:

```toml
[project.entry-points."getmeajob.sources"]
myboard = "my_board.source:MyBoardSource"
```

After `pip install -e .` in the plugin folder, a board with `ats: myboard` in `companies.yaml` works with `getmeajob source`. Keep to these rules:

1. Fetch only through the `client` you are given, so the pacing, caching, retry and bot-check rules apply.
2. Return `found=False` for a board that does not exist, and set `error` when a fetch fails. Neither closes stored jobs.
3. Skip a record with no usable id or title, and say why in `skipped`. A messy record must never stop the run.
4. Do not reuse a built-in name (greenhouse, ashby, lever, smartrecruiters, workable, recruitee). A plugin that does is refused, and the problem shows up in `getmeajob source`.
5. Test it with `httpx.MockTransport` passed to `HttpClient(transport=...)`, or with recorded files. Never with the network.

A source only reads boards. Form filling exists for Greenhouse and Ashby only, in `src/getmeajob/apply/`.

## Add an answer rule

Rules are YAML data. To try one on your own search, put it in `rules.yaml` in your workspace. It is tried before the built-in rules, and a rule with the same `id` replaces a built-in one.

```yaml
rules:
  - id: personal_blog
    match: ['\bblog\b', 'personal (site|website)']   # regular expressions, any one fits
    exclude: ['company blog']                         # optional
    types: [text, url]                                # optional; no types means any type
    answer: {kind: field, field: links.website}       # the value comes from profile.yaml
```

Patterns are checked against the normalised label: lower case, with no `*`, "(required)" or trailing `?`. The answer kinds are listed in `KINDS` in `src/getmeajob/plan/rules.py`, and [planning.md](planning.md) explains them.

To add a rule for everyone:

1. Add it to `src/getmeajob/plan/rules_default.yaml`, in the section where it belongs. Order matters: the first rule that fits wins.
2. Take the answer from a profile field. If the field is empty, the question must stay unknown.
3. Add a test in `tests/plan/test_rules.py` that the rule answers the labels it should, and one that it leaves a similar but different label alone.
4. Never add a rule that answers questions about AI or automation use, or that picks an option when the match is unclear.

## Test rules

1. No network. `tests/conftest.py` blocks every connection except to 127.0.0.1 and ::1, so a test that goes online fails.
2. Use fixtures: `FixtureTransport` with recorded replies under `examples/fixtures/http/`, `httpx.MockTransport`, the `demo_ws` and `tmp_ws` workspace fixtures, and the mock forms in `examples/mock_forms/`.
3. Synthetic data only. Emails end in `example.com`, `example.org` or `example.net`. Phone numbers are `+1 555 01xx`. Web addresses are on those domains or the `.example` top-level domain, apart from the public job board hosts.
4. No real person and no real company as an employer or target. Use the demo universe: Alex Example, Example Corp, Sample Systems, Demo Widgets and Placeholder Labs.
5. Mark tests that need Chromium with `@pytest.mark.browser`, and long ones with `@pytest.mark.slow`.

## Commit style

1. One meaningful, reviewable unit per commit: a feature with its tests and docs, or one fix. Do not mix unrelated changes.
2. Write the subject line as what the commit does, for example "Add a Workable discovery probe". Use the body for why.
3. Run the checks above first. The hook blocks a commit that contains personal data or secrets.
4. Never commit a workspace, a `.env` file, screenshots, trackers or resumes. `.gitignore` covers them, so do not force-add them.

## Licence

getmeajob is licensed under Apache-2.0. Unless you say otherwise, a contribution you submit is licensed under the same terms (section 5 of the licence). Keep the `NOTICE` file in any copy or derived work you share. It holds the credit to the original author that section 4(d) asks you to keep. See [LICENSE](../LICENSE) and [NOTICE](../NOTICE).
