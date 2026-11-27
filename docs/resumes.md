# Resumes per role

In short: you write a fact bank once. For each job, getmeajob picks and orders the facts that fit, and prints a one-page PDF. It never writes or rewords anything.

## The steps

```
getmeajob resume tailor KEY      # choose and order bank text for one job
getmeajob resume render DIR      # make resume.pdf (one Letter page)
getmeajob resume keywords KEY    # which job keywords a resume covers
getmeajob resume list            # the role folders
getmeajob resume pick KEY        # the best existing PDF for a job
getmeajob resume lint [PATH]     # wording warnings
```

`render` needs the browser extra: `pip install "getmeajob[browser]"`, then `playwright install chromium`.

## The truthfulness rule

- Every sentence on a resume is a sentence from your bank, copied word for word.
- Words a job asks for that are not in your bank are reported as gaps in `report.json`. They are never added.
- Skills come only from your `skills` lists. The ones the job names are listed first.
- A check runs before anything is written. If a resume held text that is not in the bank, nothing is written and you get an error.
- The same inputs always give the same files. There are no timestamps.

## The fact bank

The file is `resume/bank.yaml` in your workspace. `config/bank.example.yaml` is the template and `examples/demo/resume/bank.yaml` is a filled example.

| Section | What goes in it |
|---|---|
| `header` | `name` (required), `email`, `phone`, `location`, `links` |
| `summaries` | opening lines, each with an `id`, a `text` and `tags`; the best fit is used |
| `experience` | `company`, `title`, `start`, `end`, and `bullets` |
| `projects` | `name` and `bullets`; shown only when they match the job |
| `skills` | groups such as `languages: [Python, SQL]` |
| `education` | `school`, `degree`, `field`, `start`, `end` |

A bullet has an `id` (unique), a `text`, optional `tags` and an optional `short`. Tags are words that make the bullet fit a job. A tag counts for half as much as the same word in the text. `short` is a shorter wording that you wrote yourself, used only when the page is too full.

Write bullets that start with what you did. Use real numbers only where they are true. `getmeajob resume lint` warns about weak openers ("responsible for"), stock phrases, hidden characters and em dashes.

## How tailoring chooses

1. It lists the job's keywords: known skills, words from your bank that the job contains, and a few acronyms.
2. It scores each bullet by the keywords in its text (1 each) and tags (half each).
3. Each role keeps its best bullets (4 by default, `--max-bullets N`), best first. Ties keep your order.
4. The summary with the best score is used. Projects appear only when a bullet matches.
5. In each skills group, the skills the job names come first. Groups with more matches come first.

## Role folders

```
roles/<company>-<title>/
  jd.txt  resume.md  resume.html  resume.pdf  report.json  meta.yaml
```

`meta.yaml` lists the job keys the folder serves under `job_keys`. Tailoring a second job with the same company and title adds its key to the same folder. `resume pick KEY` chooses the rendered resume that covers the job's keywords best and records the key; the apply step uses that PDF.

`report.json` holds:

- `matched_keywords`: job keywords on the resume
- `unused_in_bank`: job keywords that are in your bank but not on this resume
- `gaps_not_in_bank`: job keywords that are nowhere in your bank
- `bullets_selected`, `bank_hash`, `job_keys`, and `lint` warnings

## One page

`render` measures the page in the browser before printing. If it is too long, it first swaps in your `short` wordings. If it is still too long, it drops the lowest-scoring bullets one at a time, keeping at least two per role. It rewrites `resume.md` and `resume.html` to match the PDF and records what it did under `compaction` in `report.json`. If two bullets per role still do not fit, it stops with an error and tells you what to shorten. `--allow-multipage` skips the check.
