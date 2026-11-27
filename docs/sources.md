# Job sources

In short: `getmeajob source` reads the public job boards listed in `companies.yaml`, saves the jobs, and prints only what changed since the last run. Run it twice and the second run says "no changes".

## The commands

```
getmeajob source                          # every enabled board in companies.yaml
getmeajob source --board lever:demowidgets
getmeajob source --company "Example Corp"
getmeajob source --feeds remotive,hn      # also read feeds (they are off by default)
getmeajob boards                          # the boards you follow, with open job counts
getmeajob discover names.txt              # find boards from names or URLs (--write saves them)
getmeajob import-portals portals.yml      # read a career-ops-style file (--write saves boards)
getmeajob check-live                      # are the stored jobs still open?
getmeajob jd KEY                          # a 12-line digest (--grep RE, --full)
```

Every command takes `--json` for agents. Lists stop at `--limit` rows (25 or 40 by default).

## What `source` does

1. Fetches each enabled board. Boards on the same job board site run one after another; different sites run side by side.
2. Saves jobs to `data/jobs.jsonl` and each job's text to `data/jd/<key>.txt` (plain text, at most 20,000 characters). New jobs get a `discovered` status.
3. Marks a job closed when its board answered in full and the job is gone. A board that failed this time closes nothing.
4. Writes a run summary to `data/runs/<time>.json`, with every skipped job and its reason.
5. Prints the counts, then a table of new, changed and closed jobs (company, title, location, key).

A job key looks like `greenhouse:examplecorp:1001`: the board kind, the board name and the job id.

## The boards it reads

| `ats` | What getmeajob reads |
|---|---|
| greenhouse | `boards-api.greenhouse.io/v1/boards/<slug>/jobs?content=true`, and the board name from `/v1/boards/<slug>`. If the full list times out, it reads the list without job text. |
| ashby | `api.ashbyhq.com/posting-api/job-board/<slug>?includeCompensation=true`. Unlisted jobs are left out. |
| lever | `api.lever.co/v0/postings/<slug>?mode=json`, then the EU host `api.eu.lever.co` if the board is not found. Set `region: eu` to go to the EU host straight away. |
| smartrecruiters | `api.smartrecruiters.com/v1/companies/<slug>/postings`, 100 at a time, up to 1,000. Job text comes from each job's own record (at most 25 new ones per board per run). |
| workable | `apply.workable.com/api/v1/widget/accounts/<slug>` |
| recruitee | `<slug>.recruitee.com/api/offers/`. Only published offers count. |

## Polite by default

- One shared HTTP client sends every request, with the user agent `getmeajob/<version> (+personal job search tool)`.
- Requests to the same site start at least 1 second apart. At most 4 run at once.
- Replies are cached: board lists for 6 hours, discovery lookups for 7 days, feeds for 6 hours, SmartRecruiters job records for 7 days.
- A bot check stops that site for the rest of the run. getmeajob never tries to get past one.
- Careers pages and job pages are only read when the site's robots.txt allows it.

## Feeds and their attribution rules

Feeds are lead lists, not boards. They run only when you name them with `--feeds`, send one list request per run, and never close jobs. Every feed job keeps its attribution link in its `source` field (for example `feed:remotive (https://remotive.com)`) and its `url` points back to the feed's own page for the job.

| Feed | What it reads | What the feed asks of you |
|---|---|---|
| `remotive` | `https://remotive.com/api/remote-jobs?category=software-dev` | Link back to the job's page on Remotive and name Remotive (https://remotive.com) as the source. Do not call the API often; once a few hours is plenty. |
| `remoteok` | `https://remoteok.com/api` (the first item is a legal notice and is skipped) | Link back to the job's page on Remote OK (https://remoteok.com) and name it as the source. |
| `hn` | The newest "Ask HN: Who is hiring?" thread, through the Algolia HN Search API (https://hn.algolia.com/api) | Each job links to its comment on https://news.ycombinator.com. The text belongs to the person who posted it. |

For `hn`, getmeajob reads top-level comments whose first line looks like `Company | Role | Place`. Finding the current thread is one extra request, cached for a day. These rules can change, so read each feed's own terms before you lean on it.

Feeds often link to company job boards. `source` lists the ones you do not follow yet, so you can add them.

## Messy data

Real boards send odd records. None of these stop a run:

- Ids that are empty, `null`, or the words "None" or "null": the job is skipped.
- A job with no title, a record that is not a job, or the same id twice: skipped.
- Locations sent as a list, or as a list written out as text: joined with ` | `.
- Job text escaped twice, no-break spaces and invisible characters: cleaned.

Each skipped job gets a one-line reason in the run summary.

## Discovery

`getmeajob discover FILE` reads one company per line. A line can be a board URL, a careers page URL, a name, or a name and a URL ("Example Corp, https://...").

- A board URL is read directly, with no network request.
- A careers page is fetched and scanned for job board links. If it has none, a few of its own careers or jobs links are tried.
- A name gives up to 8 slug guesses, tried on Greenhouse, Ashby, Lever, SmartRecruiters and Workable.
- A guess counts only if the board has open jobs and its name matches the company (similarity of 0.7 or more, or one name contains the other). A board with no name to compare is kept with `verified: false`.

Discovery never sends your company list to a third-party lookup service. It changes `companies.yaml` only with `--write`, and never adds a board you already have.

## Checking that jobs are still open

`getmeajob check-live` asks each job's board first. A job that is gone from a board that answered in full is closed. Otherwise it reads the job page: a 404 or 410, a redirect back to the board, or "this position has been filled" style text (with no apply button) means closed. A 403, 406, 429, a bot check or a network error gives `unknown`, which never closes a job.

## Adding a source plugin

A plugin is a small Python package. It needs one class with a `name` and three methods:

```python
from getmeajob.sources.base import ProbeResult, SourceResult


class MyBoardSource:
    name = "myboard"  # the `ats` value people put in companies.yaml

    def list_jobs(self, board, client):  # every open job on the board
        resp = client.get(f"https://jobs.myboard.example/api/{board.slug}", ttl=6 * 3600)
        ...
        return SourceResult(found=True, jobs=jobs, board_name=name)

    def probe(self, slug, client):  # used by discovery
        return ProbeResult(found=True, board_name=name, count=len(jobs))

    def parse_url(self, url):  # the slug from a board URL, else None
        return None
```

Register it in the plugin's `pyproject.toml`:

```toml
[project.entry-points."getmeajob.sources"]
myboard = "my_package.my_module:MyBoardSource"
```

Some rules:

1. Use the `client` you are given, so the pacing, caching and bot-check rules apply.
2. Return `found=False` for a board that does not exist, and set `error` for a failed fetch. Both keep stored jobs open.
3. Build keys with `Job.make_key(ats, slug, job_id)` and skip records with no usable id.
4. A plugin cannot take the name of a built-in source. Problems loading a plugin show up as warnings in `getmeajob source`.
5. Test with `httpx.MockTransport` or recorded files; tests must not use the network.
