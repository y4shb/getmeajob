# Filling application forms

Start here: `getmeajob apply --mode dry`. It fills every ready form in a browser you cannot see, takes a screenshot of each one, and never clicks Submit. Look at the pictures in `shots/` before you do anything else.

getmeajob fills Greenhouse and Ashby forms from your plans (see [planning.md](planning.md)). The answers come only from your plan files. A script does the clicking, so an AI agent never fills a form by itself.

## The short version

1. `getmeajob apply --mode dry` fills each form and saves a screenshot. It never clicks Submit.
2. Open the screenshots in `shots/` and check every answer.
3. `getmeajob apply --mode hold --headed` opens a real window, fills the form, and waits for you. You click Submit.
4. `getmeajob queue` lists anything that needs you, such as a code from your email.

Add job keys to work on chosen jobs only: `getmeajob apply greenhouse:examplecorp:1001 --mode dry`.

## The three modes

### dry (the default)

Fills the form, saves `shots/dry-<job>-<status>.png`, and closes it. It never clicks Submit. Run it as often as you like; dry runs never stop a later run.

A dry run is not invisible to the site. Some sites upload an attachment, such as your resume, as soon as it is added to the form, and some save fields as you type.

### hold

Opens a window you can see (`--headed` is required). getmeajob fills the form, then hands it to you:

1. Check the answers in the window and fix anything you want.
2. Click Submit.
3. If the board emails you a security code, type it in the window.
4. When the thank-you page shows, getmeajob notes the job as applied and moves to the next one.

getmeajob waits up to 15 minutes per job (`--hold-timeout SECONDS` changes this). Closing the window skips that job; the run goes on with the next one.

Add `--click-submit` if you want getmeajob to click Submit once for you after filling. It still waits for you to type any emailed code. It will not click when a field could not be filled or when an answer is waiting for your review. If no thank-you page shows after its click, the job is recorded as `awaiting_human` and getmeajob never clicks Submit for it again.

### submit

getmeajob fills the form and clicks Submit once by itself. This is off until you switch it on for a board (see below). It also refuses any job whose plan has answers waiting for your review: drafts, and answers an agent saved (`getmeajob plan approve KEY` or `--all` after you check them). After the click it reads the page and records one of:

- `submitted`: the thank-you page appeared.
- `awaiting_human`: anything else, such as an emailed code, a rejected field, a bot check, or no answer within 30 seconds. The application may have gone through, so getmeajob never clicks Submit for that job again. The result says what the page showed; check your email or the careers site.

## Switching on submit mode

Submit mode is off for every board until you list the board in `preferences.yaml`:

```yaml
apply:
  submit_boards: [greenhouse]   # boards where --mode submit may click Submit
  per_company_cap: 2            # applications per company in 30 days (0 turns it off)
  exclude: []                   # companies never to apply to
```

With `submit_boards: []`, `getmeajob apply --mode submit` stops with a message and does nothing.

## Hard stops

getmeajob stops on these, takes a screenshot, and adds a task to `getmeajob queue`. It never tries to get past them, and it does not try that job again in a later run. Bot check and account wall wording counts only inside the form, so a job description that mentions bots does not stop a run. A notice asking applicants not to use automated tools counts anywhere on the page.

- A bot check or CAPTCHA: getmeajob never solves one. Apply by hand if you still want the job.
- An account wall (a password field, or "create an account to apply"): getmeajob never creates accounts.
- A request not to use automated tools ("please do not use bots or AI agents"): getmeajob respects it and does not fill the form.
- A field it could not fill: getmeajob never submits a form with a problem. The queue says which field; fix the answer, then run a dry run again.

While filling, getmeajob never clicks a button that would submit the form (a submit button, or a button without a type inside the form). It attaches only files inside the workspace, or the `files.resume` and `files.cover_letter` named in your profile.

## What getmeajob skips, and why

Each run prints one line per job. These jobs are skipped without opening a browser:

- `skipped_duplicate`: already submitted, already marked applied in your tracker, or waiting for you (a bot check, an account wall, a Submit click with no confirmation). A job waiting for an emailed code after your own Submit click is still picked up by a hold run.
- `skipped_excluded`: the company matches `apply.exclude` or `exclude_companies`, you marked the job skipped, withdrawn, rejected, closed or ghosted, or the board closed it. An exclusion entry can be the board name in the job key (`examplecorp`), the whole job key, or part of the company name.
- `skipped_cap`: you already sent `per_company_cap` applications to this company in the last 30 days. Dry runs are never capped.
- `skipped_not_ready`: the plan still has open questions, the plan is out of date (you changed your profile, answers or rules since planning: run `getmeajob plan`), the plan has unreviewed answers (submit mode), or the board is not in `submit_boards`.

`--limit N` stops after N jobs that were really tried. Skipped jobs do not count. Between real jobs getmeajob waits 4 to 8 seconds.

## Screenshots and the ledger

- Screenshots go to `shots/<mode>-<job>-<status>.png`, for example `shots/dry-greenhouse__examplecorp__1001-dry_ok.png`.
- Every attempt adds one line to `data/ledger.jsonl`: the job, mode, result, problems, screenshot and plan file.
- The ledger never holds your answers. It keeps a fingerprint of them (`answers_digest`) and the path of the plan file that has them.
- A `submitted` result marks the job `applied` in your tracker and closes its open queue tasks.

## When a form changed

`getmeajob inspect URL` lists a form's fields, their labels, whether they are required, and the options of each dropdown. It only reads the page: it types nothing and clicks only to open a closed dropdown. Compare its output with `getmeajob plan show KEY` to see what moved.

## Trying it offline

The demo workspace (`getmeajob init --demo`) never opens a real job site. `examples/fixtures/forms.json` points each demo form link at a local mock form in `examples/mock_forms/`, and every other web request is blocked. Your real workspace uses real links unless `settings.yaml` sets `fixtures`.

## If something is missing

- "Filling forms needs Playwright": run `pip install -e ".[browser]"`, then `playwright install chromium`.
- "A hold run needs a visible browser window": add `--headed`, and run it on a computer with a screen.

Next: run `getmeajob apply --mode dry` and open the first screenshot in `shots/`.
