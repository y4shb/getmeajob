---
description: Check every answer getmeajob would send and answer the open questions yourself
argument-hint: "[KEY ...]"
---

Follow the getmeajob skill and its `POLICY.md`: only the user's own words or their profile, gaps stay gaps, never guess an answer.

Work through `answer-review.md` in the getmeajob skill folder, step by step. The short version:

1. Run `getmeajob plan review $ARGUMENTS --json` and `getmeajob plan unknowns --json`. Read nothing else.
2. Show only the deduplicated `question | answer | from` table, the open questions with their options, and any drafts waiting for approval.
3. Ask the user to confirm or correct each answer and to answer each open question in their own words. Then wait.
4. Write only the confirmed answers into the stub from `getmeajob plan unknowns --stub answers-todo.yaml`, then run `getmeajob plan answer answers-todo.yaml`.
5. Run `getmeajob plan` again and report how many questions are still open.

If the user approves drafted answers, run `getmeajob plan approve KEY` for that job.
