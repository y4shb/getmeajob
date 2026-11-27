# Responsible use

In short: getmeajob is for your own job search, on sites that allow it. It reads job boards slowly, stops at every bot check, never creates accounts and never invents an answer. Submitting stays your decision. You are responsible for following each site's terms.

## Before you point it at a site

1. Read the site's terms of use. If they forbid automated access or automated applications, do not use getmeajob there. Apply by hand.
2. Know what getmeajob checks for you. It reads robots.txt before it fetches a web page: careers pages in `discover`, job pages in `check-live`, and the Ashby page fallback in `plan`. If robots.txt says no, it skips the page.
3. Know what it does not check. The JSON board APIs in `source` are not checked against robots.txt. The form filler opens the application page you asked it to open, as your own browser would, and does not read robots.txt either. The site's terms are your guide for both.
4. Keep the polite defaults below. Raising a number is fine. Lowering one makes getmeajob less polite.

## Polite defaults

Every request goes through one HTTP client with the user agent `getmeajob/<version> (+personal job search tool)`.

| Setting | Default | Change it in `settings.yaml` |
|---|---|---|
| Time between two requests to the same site | at least 1 second | `min_interval` |
| Time to wait for a reply | 10 seconds to connect, 25 seconds to read | `timeout` (the read time) |
| Retries | 3 extra tries on 429, 5xx and timeouts, with growing waits and jitter. `Retry-After` is honoured, and a wait over 60 seconds stops with an error. 404 and 410 are never retried. | `retries` |
| Requests at the same time | at most 4 | `max_workers` |
| Caching | board lists and feeds 6 hours, discovery lookups 7 days, form questions 24 hours | not configurable |

When applying, getmeajob waits 4 to 8 seconds between two real attempts.

## Bot checks and CAPTCHAs

getmeajob stops. It never tries to get past one.

1. While reading boards, a bot wall (a 403 or 503 with a challenge page) stops that site for the rest of the run, with no retry.
2. While filling a form, a CAPTCHA or bot check stops that job. getmeajob takes a screenshot, adds a `captcha` item to `getmeajob queue`, and never tries that job again on its own.
3. If you still want the job, apply by hand at the link, then run `getmeajob track set KEY applied`.

Do not add a CAPTCHA solving service, and do not change the code to get around a bot check.

## Accounts

getmeajob never creates accounts. An account wall, such as a password field or "create an account to apply", stops that job and adds an `account_required` item to the queue. Apply by hand if you want the job.

## Honest answers

1. Answers come only from your `profile.yaml` and `answers.yaml`. A missing fact becomes a question for you, never a guess.
2. A choice question with no clear match is left for you. getmeajob never falls back to the first option.
3. Questions about your use of AI or automated tools are never answered by a rule. A form that asks people not to use automated tools blocks the plan, and the filler does not touch it.
4. AI drafting is off unless you run `getmeajob plan draft`. Every draft is marked for review. `--mode submit` refuses a job with unreviewed drafts, and `--click-submit` in a hold run does not click. Run `getmeajob plan approve KEY` only after you have read and corrected the draft.
5. Resumes reuse your own fact bank sentences word for word. Job keywords missing from your bank are reported as gaps, never added.

## You stay in the loop

| Mode | What happens | Who clicks Submit |
|---|---|---|
| `dry` (default) | Fills the form, takes a screenshot, closes it | Nobody |
| `hold` | Fills the form in a window you can see, then waits up to 15 minutes for you | You, or getmeajob once with `--click-submit` |
| `submit` | Fills the form and clicks Submit once | getmeajob, only for boards you list |

Submit mode is off for every board until you list the board in `apply.submit_boards` in `preferences.yaml` and also pass `--mode submit`. A good order for a new board:

1. Run `getmeajob apply --mode dry` and open each screenshot in `shots/`.
2. Run `getmeajob plan review` and check every answer.
3. Use `getmeajob apply --mode hold --headed` for your first applications on that board.
4. Switch on submit mode for that board only after hold runs went as you expected.

## The per-company cap

By default getmeajob sends at most 2 applications per company in 30 days. It counts jobs that were submitted, or may have been (`awaiting_human`, `needs_email_code`). Dry runs do not count. Change it with `apply.per_company_cap` in `preferences.yaml`; `0` turns it off. Keep it on: many applications to one company in a short time help nobody. `apply.exclude` lists companies getmeajob must never apply to.

## Feeds and their attribution rules

Feeds are off until you name them with `getmeajob source --feeds remotive,remoteok,hn`. Each sends one list request per run, and the replies are cached for 6 hours. HN sends one more request to find the current thread, cached for a day. Every feed job keeps its attribution link in its `source` field, and its link points back to the feed's own page.

| Feed | What the feed asks of you |
|---|---|
| Remotive | Link back to the job's page on Remotive and name Remotive as the source. Do not call the API often; once every few hours is enough. |
| Remote OK | Link back to the job's page on Remote OK and name it as the source. |
| HN "Who is hiring" | Link to the comment on Hacker News. The text belongs to the person who posted it. |

If you share or publish feed jobs, for example in a tracker, keep those links. These rules can change, so read each feed's own terms first. [sources.md](sources.md) has the details.

## When not to use getmeajob

1. On sites whose terms forbid automated access or automated applications.
2. On a form that asks applicants not to use automated tools, even if getmeajob did not catch the wording.
3. On sites that need you to log in. getmeajob has no login support and never creates accounts.
4. To apply in bulk to roles you would not take or do not qualify for. The cap and the ranking flags are there to stop that.
5. For anyone but yourself, or with answers you have not checked.
