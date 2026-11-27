---
description: Open a visible browser, fill one form, and let you check it and click Submit yourself
argument-hint: "KEY"
disable-model-invocation: true
---

Follow the getmeajob skill and its `POLICY.md`: never fill a form yourself, never get past a bot check, never submit without the user's clear opt-in.

The job key is `$ARGUMENTS`. If it is empty, ask the user which job (run `getmeajob status` or `getmeajob queue --json` to help them find the key).

1. Explain what happens: a browser window opens and getmeajob fills the form. The user checks every field, fixes anything, clicks Submit, and types any security code the board emails them. Closing the window skips the job.
2. Ask the user to confirm they are at the screen and ready. Wait for a yes.
3. Run `getmeajob apply $ARGUMENTS --mode hold --headed`. It waits up to 15 minutes for the user, so run it in the background or with a long timeout, or ask the user to run it in their own terminal.
4. Do not click, type or read the page yourself while it runs.
5. Report the final line for the job: `submitted`, `closed_by_user`, `timeout` or a problem. Suggest `/getmeajob:queue` for anything left open.

Only add `--click-submit` when the user explicitly asks getmeajob to click Submit for them on this job.
