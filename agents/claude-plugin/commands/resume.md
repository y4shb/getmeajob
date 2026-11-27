---
description: Build a one-page resume for one job from your own fact bank
argument-hint: "KEY"
---

Follow the getmeajob skill and its `POLICY.md`: every resume line comes from the user's `resume/bank.yaml`. Never add a skill, number or achievement they did not write.

The job key is `$ARGUMENTS`. If it is empty, ask the user which job.

1. Run `getmeajob resume tailor $ARGUMENTS --json` and report the role folder it made and which bank items it picked.
2. Run `getmeajob resume keywords $ARGUMENTS --json` and list the job keywords the resume does not cover.
3. For each gap, ask the user whether it is true for them. If it is, they add it to `resume/bank.yaml` in their own words. Never add it yourself.
4. Run `getmeajob resume render $ARGUMENTS` to make the PDF, and `getmeajob resume lint` to check the wording.
5. Tell the user where the PDF is and suggest they read it once before using it.
