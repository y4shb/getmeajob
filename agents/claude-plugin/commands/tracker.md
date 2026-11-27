---
description: Write the Excel and Markdown trackers and show your application funnel
argument-hint: "[KEY STATUS]"
---

Follow the getmeajob skill and its `POLICY.md`: never invent facts, record only what the user tells you.

1. If the user gave a job key and a status (`$ARGUMENTS`), confirm them, then run `getmeajob track set KEY STATUS` with those values.
2. Run `getmeajob report --json` and name the two files it wrote (`xlsx` and `md`) and the row counts.
3. Run `getmeajob track stats --json` and show the counts per status in one or two lines.
4. Tell the user they can edit Status, Next action and Notes in the Excel file. After they save it, run `getmeajob track import-xlsx exports/tracker.xlsx` from the workspace folder, or pass the full path from step 2.
5. To find applications with no news for three weeks, offer `getmeajob track ghost`. Add `--apply` only if the user agrees.
