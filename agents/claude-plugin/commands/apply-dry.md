---
description: Fill your planned forms in a hidden browser and save screenshots, never submitting
argument-hint: "[KEY ...] [--limit N]"
---

Follow the getmeajob skill and its `POLICY.md`: never fill a form yourself, never get past a bot check, never submit without the user's clear opt-in.

1. Run `getmeajob apply $ARGUMENTS --mode dry --json`. This command does all the filling; you only read its result.
2. Show a table from `results`: job key, status, detail, screenshot path.
3. Ask the user to open the screenshots (in the workspace `shots/` folder) and check every answer before anything else.
4. For `fill_problem`, `captcha`, `account_required` or `automation_refused`, point to `/getmeajob:queue`. Never try to work around them.
5. When the user is happy with a job, suggest `/getmeajob:hold-run KEY`. Do not submit anything.

If the result says Playwright is missing, show its hint: `pip install "getmeajob[browser]"`, then `playwright install chromium`.
