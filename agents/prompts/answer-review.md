# Answer review

Use this when the user checks the answers getmeajob would put into their application forms. Follow `POLICY.md` the whole time: only the user's own words or their profile, gaps stay gaps.

## 1. Get the two compact lists

Run these and read only their output:

```sh
getmeajob plan review --json
getmeajob plan unknowns --json
```

- `plan review` gives `rows` (one per question label: `label`, `answer`, `source`, `count`), `unknowns` and `needs_review` (drafted answers nobody approved yet).
- `plan unknowns` gives each open question once, however many jobs ask it, with `type`, `options`, `jobs` and `required`.

Do not open plan files, form pages or job texts. These two lists are all you need.

## 2. Show the user three short tables

1. Answers to check: `question | answer | from`. Shorten `source` to plain words: `rule:email` is "your profile", `override:global` is "your answers file". Group obvious ones (name, email, phone) into one line if the table is long.
2. Questions only you can answer: `question | type | options | jobs`. Mark required ones.
3. Drafts waiting for approval, if any: `job | question | draft`.

Keep each answer cell under about 60 characters. Say how many rows you left out, if any.

## 3. Ask, then wait

Ask the user to do three things:

1. Confirm the first table, or say which answers are wrong and what they should be.
2. Answer each open question in their own words. For choice questions, they pick one of the listed options exactly.
3. Approve or reject each draft.

Rules while you wait:

- Never answer an open question for the user. Not even an "obvious" one.
- If the user asks you to suggest wording for a free-text question, use only what they told you and facts from their profile. Show it as a suggestion. Save it only after they approve the exact text.
- If an answer does not match any listed option, say so and ask again. Do not pick the closest option.

## 4. Save what the user confirmed

1. Write the stub file: `getmeajob plan unknowns --stub answers-todo.yaml`. With no open questions it writes nothing; then create the file yourself with a `global:` section.
2. Put each confirmed answer between the quotes after its question. Leave anything unconfirmed empty.
3. For a corrected answer from the first table, add the exact question label under `global:` with the new value.
4. Save the answers: `getmeajob plan answer answers-todo.yaml`.
5. Re-plan and show the new counts: `getmeajob plan`, then `getmeajob plan review --json` again.

For approved drafts, run `getmeajob plan approve KEY` once per job. For rejected drafts, ask the user for their own text and save it as in step 4.

The file name `answers-todo.yaml` matches the repo's `.gitignore`, so it stays out of git. The user may delete it once the answers are saved.

## 5. Finish

Tell the user in one or two lines: how many answers were saved, how many questions are still open, and the next step (`getmeajob apply --mode dry` when nothing is open).
