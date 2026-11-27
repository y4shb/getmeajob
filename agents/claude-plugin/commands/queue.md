---
description: What is waiting on you, grouped by kind, with what to do for each
argument-hint: "[--all] [--kind KIND]"
---

Follow the getmeajob skill and its `POLICY.md`: never invent facts, never get past a bot check, never create an account.

1. Run `getmeajob queue $ARGUMENTS --json`.
2. For each group in `groups`, show the kind, its `need` line, and up to five items as `id: company, role (key)`.
3. Say how many items are open in total.
4. Help with one item at a time. For `needs_answers`, suggest `/getmeajob:review-answers`. For `needs_email_code` or `fill_problem`, suggest `/getmeajob:hold-run KEY`. For `captcha`, `account_required` or `automation_refused`, the user applies by hand at the link.
5. Mark an item done only when the user says it is: `getmeajob queue resolve ID --note TEXT`.

When the user applied by hand, record it with `getmeajob track set KEY applied` after they confirm.
