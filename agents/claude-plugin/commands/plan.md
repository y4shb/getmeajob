---
description: Plan form answers from your profile; list what only you can answer
argument-hint: "[KEY ...] [--min-score N] [--refresh]"
---

Follow the getmeajob skill and its `POLICY.md`: never invent facts, gaps stay gaps, never submit without the user's clear opt-in.

1. Run `getmeajob plan $ARGUMENTS --json`. With no keys it plans the shortlisted jobs.
2. Show a short table from `plans`: key, status, answered, unknowns. List `skipped` jobs with their reason in one line each.
3. If `ranked_missing` is true, say that nothing is ranked yet and suggest `getmeajob rank`.
4. A `blocked` plan means the form refused automated tools or similar. Show the reason. Never try to get around it.
5. If any plan needs answers, suggest `/getmeajob:review-answers`. If every plan is ready, suggest `/getmeajob:apply-dry`.

Never fill an unknown question yourself, here or in any later step.
