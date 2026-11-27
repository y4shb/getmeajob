# Token efficiency

In short: scripts do the reading, parsing and clicking, and the model reads short summaries. On the synthetic demo the summaries came out about 2 to 100 times smaller than the files behind them. Every number on this page is an estimate (characters divided by 4), measured with `getmeajob tokens estimate`.

## The pattern

| Habit | What it means in practice | Where you see it |
|---|---|---|
| Scripts do the I/O | Network calls, HTML parsing, file writes and form filling happen in Python. The model does not need to read a form page or a raw API reply. | `source`, `plan`, `apply` |
| Compact summaries | Every command prints a short table and ends with one `next:` line. `--json` gives the same facts as one line of JSON. | `status` (at most 40 lines), `context KEY` (under 2,000 characters) |
| Rules answer most questions | Your saved answers come first, then answer rules, which are data and take facts only from your profile. In the demo they filled 21 questions across the 2 forms and left 2 for the candidate. | `plan`, `plan review` |
| Each unknown asked once | Open questions are deduplicated by label and options across all jobs, so one answer covers every job that asks it. | `plan unknowns --stub FILE`, `plan answer FILE` |
| Diffs, digests and caches | `source` prints only new, changed and closed jobs. Job text is read as a digest of 12 lines or fewer, or searched with `--grep`. Board replies, form questions, plans and AI drafts are cached. | `source`, `jd KEY`, `jd KEY --grep RE` |

The caches, in numbers:

1. Board lists and feeds: 6 hours. Discovery lookups: 7 days.
2. Form questions: 24 hours, in `data/schemas/`.
3. Plans: reused while the form, the profile, the answers for that job and the rules stay the same. A second `plan` with nothing changed writes no files and marks the job `reused`.
4. AI drafts: cached by prompt in `cache/llm/`, so running `plan draft` again costs nothing.

## Measured on the demo

Each row compares a file an agent would otherwise read in full with the command that replaces it.

| An agent reads in full | Tokens (estimate) | It runs instead | Tokens (estimate) | Smaller by (estimate) |
|---|---|---|---|---|
| The 4 recorded board replies | ~3,074 | `getmeajob source` | ~345 | about 9x |
| The same 4 replies, on a second run | ~3,074 | `getmeajob source` again ("no changes") | ~29 | about 100x |
| Both mock form pages (HTML) | ~8,644 | `getmeajob plan review` | ~666 | about 13x |
| Both mock form pages (HTML) | ~8,644 | `getmeajob apply --mode dry` | ~146 | about 59x |
| Both plans, before the open question was answered | ~2,105 | `getmeajob plan unknowns` | ~85 | about 24x |
| `data/jobs.jsonl` (8 jobs) | ~2,083 | `getmeajob status` | ~106 | about 20x |
| One job's stored record, ranking and plan | ~1,673 | `getmeajob context greenhouse:examplecorp:1001` | ~194 | about 9x |
| One job's text, as HTML from the board API | ~227 | `getmeajob jd greenhouse:examplecorp:1001` | ~102 | about 2x |
| One job's text, as plain text | ~144 | `getmeajob jd greenhouse:examplecorp:1001 --grep kubernetes` | ~57 | about 2.5x |

Eight of the quick start's outputs (`source`, `rank`, `plan`, `plan unknowns`, `plan review`, `apply`, `report` and `status`) add up to about 1,700 tokens (estimate).

The job text rows save little because the demo job text is only 574 characters. The digest stays at 12 lines or fewer however long the text is, so the gap grows with longer postings. That growth was not measured here.

## How this was measured

1. Make a fresh demo workspace and run the README quick start in it: `init --demo`, `source`, `rank`, `plan`, `plan unknowns --stub`, `plan answer`, `plan`, `plan review`, `apply --mode dry`, `report`, `status`. `bash scripts/quickstart.sh` runs the same steps.
2. Save each command's printed output to a text file. The workspace path in the output was written as `./workspace`, so a long folder name does not count.
3. Collect the files an agent would read instead: the recorded replies in `examples/fixtures/http/`, the mock forms in `examples/mock_forms/`, and `data/jobs.jsonl`, `data/ranked.jsonl` and `data/plans/` from the workspace. The plans were copied before the open question was answered.
4. Run `getmeajob tokens estimate FILE...` on all of them. It counts characters and divides by 4.
5. Round each ratio.

## Limits of these numbers

1. Characters divided by 4 is a rough rule. A real tokenizer gives different counts.
2. The demo is small: 8 jobs, 2 forms and short job texts. Real boards and real form pages were not measured.
3. The mock forms were written for this repo. They are not copies of real Greenhouse or Ashby pages.
4. The "reads in full" column assumes the agent reads the whole file. An agent could read part of a file instead, which would cost less than shown.

To check a file yourself: `getmeajob tokens estimate path/to/file`.
