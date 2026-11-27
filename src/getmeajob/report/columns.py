"""Sheet layout for the Excel tracker: column names, widths and the Read me text.

Columns are matched by these header names when your edits are read back, so renaming
one here is a change to the file format.
"""

from __future__ import annotations

from getmeajob.report.xlsx_read import KEY, NEXT, NOTES, QUEUE, STATUS, SYNC

TRACKER_HEADERS = [
    KEY,
    "Company",
    "Role",
    "Location",
    "Tier",
    "Score",
    "Eligible",
    "Why",
    STATUS,
    "Applied on",
    NEXT,
    "Resume used",
    "Plan status",
    "Unknowns",
    "Job link",
    "JD file",
    "Posted",
    "First seen",
    "New/closed since last run",
    NOTES,
    QUEUE,
    SYNC,
]
HIDDEN = (QUEUE, SYNC)
TRACKER_WIDTHS = {
    KEY: 30,
    "Company": 18,
    "Role": 30,
    "Location": 22,
    "Tier": 18,
    "Score": 7,
    "Eligible": 9,
    "Why": 50,
    STATUS: 14,
    "Applied on": 12,
    NEXT: 30,
    "Resume used": 26,
    "Plan status": 14,
    "Unknowns": 36,
    "Job link": 34,
    "JD file": 30,
    "Posted": 12,
    "First seen": 12,
    "New/closed since last run": 12,
    NOTES: 40,
    QUEUE: 8,
    SYNC: 10,
}
TRACKER_WRAP = ("Why", NEXT, "Unknowns", NOTES)
ALL_HEADERS = [
    "Key",
    "Company",
    "Role",
    "Location",
    "Score",
    "Eligible",
    "Flags",
    "Status",
    "Posting",
    "Job link",
    "First seen",
]
ALL_WIDTHS = {"Key": 30, "Company": 18, "Role": 32, "Location": 24, "Score": 7, "Flags": 50}
JD_HEADERS = ["Key", "Company", "Role", "Job link", "Job description"]
QUEUE_HEADERS = [
    "ID",
    "Kind",
    "What we need from you",
    "Key",
    "Company",
    "Role",
    "Detail",
    "Link",
    "Since",
]
QUESTION_HEADERS = ["Question", "Type", "Required", "Jobs", "Companies", "Options", "Why unknown"]
SHEETS = (
    ("Read me", "This page: what each sheet holds, how to edit, and counts."),
    (
        "Tracker",
        "One row per job you are working on (shortlisted or further, planned, or set by "
        "you). Edit Status, Next action and Notes here.",
    ),
    ("All jobs", "Every job getmeajob has found, best score first, with flags and links."),
    ("Job descriptions", "The full text of each job on the Tracker (cut at 32,000 characters)."),
    ("Queue", "Things waiting on you, each with what getmeajob needs you to do."),
    ("Questions", "Form questions your profile could not answer, once per question."),
)
HOW_TO = (
    "1. Change Status with the drop-down list on the Tracker sheet.",
    "2. Write anything you like in Next action and Notes.",
    "3. Save the file as .xlsx.",
    "4. Run: getmeajob track import-xlsx exports/tracker.xlsx",
    "5. Leave the Key column alone; getmeajob matches rows by it. Two hidden columns at "
    "the right are for getmeajob too.",
    "Running `getmeajob report` again keeps edits you have not imported yet.",
)
