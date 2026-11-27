# Planning form answers

`getmeajob plan` reads each job's application form and decides an answer for every question before any browser opens. Answers come only from two files you control: `profile.yaml` and `answers.yaml`. When those files do not settle a question, getmeajob asks you instead of guessing.

## The short version

1. `getmeajob plan` plans your shortlisted jobs (or `getmeajob plan KEY ...` for chosen ones).
2. `getmeajob plan unknowns --stub answers-todo.yaml` writes the open questions to a file, once per question.
3. Fill in `answers-todo.yaml` with true answers, then run `getmeajob plan answer answers-todo.yaml`.
4. Run `getmeajob plan` again. Jobs with every required question answered become `ready`.
5. `getmeajob plan review` shows one table of every answer that will be sent.

Plans live in `data/plans/<key>.json`. Running `plan` again with nothing changed reuses them and writes no files.

## How an answer is chosen

For each question, in this order:

1. Your saved answer in `answers.yaml`: `by_job` (question id, then label), then `by_company`, then `global`.
2. The first rule that fits the question (your `rules.yaml` first, then the built-in rules).
3. Nothing fits: a required question becomes an **unknown** and the plan is `needs_answers`. An optional question is left blank (source `skip`).

A saved answer for a choice question must match one of the options. If it does not, the question is treated as unknown and the reason says why.

Plan status is one of:

- `ready`: every required question has an answer.
- `needs_answers`: some required questions are unknown.
- `blocked`: the form or the job description asks applicants not to use automated tools (reason `automation_refused`).
- `schema_unavailable`: the form questions could not be read. The reason is stored with the plan.

## Truthfulness rules

These hold for every plan and each has a test.

- A missing profile field gives an unknown, never a guess.
- Choice questions never fall back to the first option. If two options both fit ("Yes, I will require sponsorship" and "Yes, I have sponsorship"), the matcher refuses and says why.
- A near match never flips the meaning: "I am a protected veteran" never picks "I am not a protected veteran".
- Questions about AI or automated tools are never answered by a rule. Text in a label or description telling candidates not to use bots, automated tools or AI agents blocks the plan. So does a job description that tells applicants not to use AI or automated tools to apply; the queue item quotes the sentence.
- Consent boxes are ticked only when `consent.privacy_notice: true` is in your profile.
- Voluntary self-ID questions (gender, race, veteran, disability) use your profile value if you set one, otherwise the "decline" option. Without a decline option, a required one becomes unknown and an optional one is left blank.

A few more cautious choices:

- Work permit and sponsorship answers use only the countries in `eligibility.authorized_countries` and `eligibility.needs_sponsorship_countries`. When the question names no country, the job location is used. When that names no country either, as with most remote jobs, the question stays open for you.
- A file answer must sit inside the workspace, or be your `files.resume` or `files.cover_letter`. Any other path is refused when planning and again when filling.
- "Have you worked for X?" compares whole company names, so "Initech Example Ltd" does not count as "Example Corp".
- Years questions about one skill ("years with Kubernetes") stay unknown. Only total experience comes from `experience.total_years`.
- Pay questions are left blank when optional. Current pay is shared only with `compensation.share_current: true`.

## The answers file

```yaml
global:
  "Were you referred by a current employee?": "No"
by_company:
  examplecorp:
    "Why do you want to join Example Corp?": "..."
by_job:
  "greenhouse:examplecorp:1001":
    question_2005: "..."
```

Labels are matched loosely: case, `*`, "(required)" and a trailing `?` do not matter. For multi-choice questions write a list. Blank values count as "not answered yet", so a half-filled stub is safe to merge.

## Unknowns, once per question

`getmeajob plan unknowns` prints one row per distinct question across all jobs: label, type, up to 6 options, how many jobs ask it, and whether it is required. Two questions with the same label but different options stay separate.

The stub file puts a question under `by_company` when only one company asks it, and under `global` otherwise. Comments above each entry list the type and the options.

## Rules file format

Rules are data. Add your own in `rules.yaml` in the workspace; they are tried before the built-in rules in `src/getmeajob/plan/rules_default.yaml`, and a rule with the same `id` replaces the built-in one.

```yaml
rules:
  - id: notice_or_start
    match: ['notice period', 'when can you start']   # regular expressions
    exclude: ['manager']                              # optional
    types: [text, select]                             # optional; default is any type
    answer: {kind: field, field: experience.notice_period}
automation_refusal:                                   # optional extra blocking patterns
  - 'this form must be completed by hand'
```

Patterns are checked against the normalised label (lower case, no `*`). Useful answer kinds:

- `field`: a profile value. `a|b` means "a, else b". For choices, `<field>_aliases` in the profile is tried too.
- `yes_no`: a true/false profile value, mapped onto Yes/No options.
- `choice_from`: a profile value mapped through `options_pref` entries such as `'careers page=career|company website'`.
- `eeo`, `consent`, `years`, `years_threshold`, `sponsorship`, `work_authorization`: the special cases described above.
- `skip_optional` and `never`: no automatic answer (blank when optional, unknown when required).

The full list of kinds is `KINDS` in `src/getmeajob/plan/rules.py`. A bad pattern or an unknown kind gives a clear error naming the rule.

## Drafting free-text answers (optional)

`getmeajob plan draft` can ask a language model for a first draft of free-text questions such as "Why do you want to join?". It is off unless you run it.

- Only `text` and `textarea` unknowns that are not factual are drafted. Questions about legal status, pay, self-ID, years, dates, contact details or AI are never drafted.
- The prompt holds the question, the job title and company, the start of the job description, and a few profile facts. The model must reply `ASK_HUMAN` if those facts are not enough.
- Every draft is saved under `by_job` with `needs_review: true`. Read it, edit `answers.yaml` if needed, then run `getmeajob plan approve KEY`. Submitting refuses jobs with unreviewed drafts.
- A reply cut off at the token limit is not saved; the question stays open for you.
- Answers an agent saves through the MCP server are marked `needs_review: true` and `source: agent` too. `getmeajob plan approve --all` approves every waiting answer, in every section of `answers.yaml`.
- `--budget N` caps the estimated tokens: characters divided by 4, plus 1024 kept for each reply. The default, 10000, fits about five drafts. Replies are cached in `cache/llm/`, so running it again costs nothing.

Providers:

- `--provider anthropic` uses Claude through the optional `anthropic` package (`pip install 'getmeajob[llm]'`). The SDK reads its key from `ANTHROPIC_API_KEY`.
- `--provider command` runs the command in `GETMEAJOB_LLM_COMMAND` with the prompt on stdin and reads the answer from stdout. Any command line tool works.

## Where form questions come from

- Greenhouse: the public job board API, including location, compliance, demographic and education questions.
- Ashby: the same form request the public application page makes. If it fails and Playwright is installed, getmeajob reads the rendered page instead. That fallback never runs in offline mode.
- Each form is cached in `data/schemas/` for 24 hours. `getmeajob plan --refresh` fetches it again.
- Odd payloads (missing labels, strange field types, invisible characters) never stop a run. An unreadable field becomes type `unknown`: required ones become unknowns for you, optional ones are left blank.
