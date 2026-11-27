# Tracking applications

Run `getmeajob status` to see where your search stands on one screen. The rest of this page explains the statuses, the queue of things waiting on you, and the Excel and Markdown trackers.

## The short version

1. `getmeajob status` shows counts, what changed and one suggested next command.
2. `getmeajob queue` lists what getmeajob needs from you, grouped by kind.
3. `getmeajob report` writes `exports/tracker.xlsx` and `exports/tracker.md`.
4. Edit Status, Next action or Notes in the Excel file, save it, then run `getmeajob track import-xlsx exports/tracker.xlsx`.
5. `getmeajob track set KEY applied` records a status straight from the command line.

Every command takes `--json` for agents and prints a short table otherwise.

## Statuses

A job moves up this ladder from the top:

| Status | Meaning |
|---|---|
| discovered | found by `getmeajob source` |
| shortlisted | scored high enough in `getmeajob rank` |
| planned | form read and answers planned |
| ready | every required question has an answer |
| applied | application sent |
| screening | first contact: recruiter call or test |
| interviewing | interviews under way |
| offer | you have an offer |
| accepted | you took the offer |

It can also end in one of these:

| Status | Meaning |
|---|---|
| rejected | the company said no |
| withdrawn | you pulled out |
| closed | the posting closed |
| skipped | you chose not to apply |
| ghosted | no news for weeks after applying |

Every change is one line in `data/events.jsonl`, with the time, the new status, who made it and an optional note. Nothing is ever rewritten, so `getmeajob track show KEY` can always give the full timeline.

## How statuses move

Some changes happen on their own:

- `source` marks new jobs `discovered` and vanished ones `closed`.
- `rank` marks good matches `shortlisted`.
- `plan` marks jobs `planned`, then `ready` once every required question has an answer.
- `track ghost --apply` marks quiet applications `ghosted`.

Automatic changes only ever move a job forward. They never close a job you already applied to, and they never touch a job you moved to a dead end yourself.

You can set any status at any time, forward or back:

- `getmeajob track set KEY interviewing --note "call on Tuesday"`
- or change the Status cell in the Excel file and import it.

When you move a job to applied or later, or to a dead end, its open queue items are resolved for you, since nothing is waiting on you any more.

### The ghost sweep

`getmeajob track ghost` lists jobs that are `applied` or `screening` and have had no status change for 21 days. It writes nothing. Add `--apply` to mark them `ghosted`, or `--days 30` to wait longer.

## The queue

The queue holds things only you can do. The planner and the applier add items and resolve them when the cause goes away. Each kind comes with one line saying what to do:

| Kind | What we need from you |
|---|---|
| needs_email_code | Open the form with `getmeajob apply KEY --mode hold --headed`, then type the code from your email. |
| needs_answers | Answer the open questions: `getmeajob plan unknowns --stub answers-todo.yaml`, fill it in, then `getmeajob plan answer answers-todo.yaml` and `getmeajob plan`. |
| validation_error | Fix the answer the form did not accept in `answers.yaml`, then `getmeajob plan KEY` and apply again. |
| fill_problem | Run `getmeajob apply KEY --mode hold --headed` and finish those fields yourself. |
| captcha | Apply by hand at the link (getmeajob never solves bot checks), then `getmeajob track set KEY applied`. |
| account_required | Apply by hand at the link (getmeajob never creates accounts), then `getmeajob track set KEY applied`. |
| automation_refused | The form asks people not to use automated tools. Apply by hand if you still want the job. |
| manual | Your own reminders. |

Useful commands:

- `getmeajob queue` shows open items; `--kind captcha` shows one kind; `--all` adds resolved ones.
- `getmeajob queue resolve ID --note "applied by hand"` closes an item.
- `getmeajob queue add KEY --kind manual --note "ask about the team"` adds your own reminder.

## The Excel file

`getmeajob report` writes `exports/tracker.xlsx`. It opens in Excel, LibreOffice and Numbers. The sheets, in order:

1. **Read me**: what each sheet holds, how to edit, the export date and live counts per status.
2. **Tracker**: one row per job you are working on. That means shortlisted or further, planned, or anything you touched yourself. This is the sheet you edit.
3. **All jobs**: every job found, best score first, with its flags and link.
4. **Job descriptions**: the full text of each job on the Tracker, cut at 32,000 characters (the rest stays in `data/jd/`).
5. **Queue** and **Questions**: open queue items with what to do, and the form questions your profile could not answer, once per question.

The Tracker columns are Key, Company, Role, Location, Tier, Score, Eligible, Why, Status, Applied on, Next action, Resume used, Plan status, Unknowns, Job link, JD file, Posted, First seen, New/closed since last run and Notes.

Row colours follow the Status cell:

- green: applied or later
- yellow: questions to answer or a queue item open
- grey: rejected, withdrawn, closed, skipped or ghosted

The header row and the Key, Company and Role columns stay in view while you scroll. Every sheet has filters. Job links and JD files are real links (the JD file link works while the file sits in `exports/`).

## Editing the file and importing your edits

1. Change Status with the drop-down list on the Tracker sheet.
2. Write what you like in Next action and Notes.
3. Save the file, keeping the .xlsx format.
4. Run `getmeajob track import-xlsx exports/tracker.xlsx`.

The import records each changed status with the source `xlsx`, and stores Notes and Next action in `data/notes.jsonl`. It finds columns by their header names, so you can move columns around, sort and filter. Leave the Key column as it is, because rows are matched by it.

A few things worth knowing:

- Importing the same file twice records nothing the second time.
- A status getmeajob does not know (a typo like "interviewd") is listed in the output and not recorded.
- Two hidden columns at the right hold what getmeajob wrote in each row. Only cells you changed count as edits, so an old copy of the file never undoes newer changes in rows you left alone.
- Running `getmeajob report` again keeps Notes, Next action and any edits you have not imported yet.

## The Markdown file

`exports/tracker.md` holds the same jobs as the Tracker sheet, grouped by status in ladder order. Each group is one small table with Company, Role, Score, Status and a link. It stays short so you can skim it, or hand it to an agent cheaply.

## Commands for agents

These print little and point at the next step, so an agent spends few tokens:

- `getmeajob status`: at most 40 lines. Counts per status, jobs added and closed in the last source run, open queue items by kind, plans needing answers and one suggested next command.
- `getmeajob context KEY`: under 2,000 characters about one job. Title, company, location and link, a short JD digest, the score with its reasons and flags, the plan status with its open questions, and the resume folder with its keyword gaps.
- `getmeajob tokens estimate FILE...`: characters divided by 4, per file and in total. Every number is labelled as an estimate. It needs no workspace, and relative paths are tried from the current folder first, then from the workspace.
