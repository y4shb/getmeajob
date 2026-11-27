# How ranking works

In short: `getmeajob rank` gives every job a score from 0 to 100 and a short list of reasons. Flags can make a job ineligible, whatever its score. Everything comes from your `preferences.yaml`. Nothing about you or your home is built into the code.

## The commands

```
getmeajob rank              # best eligible jobs, 25 rows
getmeajob rank --all        # ineligible jobs too
getmeajob rank --min-score 70 --limit 10
getmeajob explain KEY       # reasons and flags for one job
```

`KEY` can be a part of the key if only one job matches ("1001" is enough).

`rank` writes every result to `data/ranked.jsonl` and prints a table: score, eligible, tier, company, title, key. Eligible jobs at or above `thresholds.shortlist` get a `shortlisted` status. Running it twice changes nothing.

## How the score is built

Four parts, each from 0 to 1, multiplied by your weights. The weights are scaled so they always add up to 100.

| Part | What it measures |
|---|---|
| experience | the years the job asks for, against yours |
| title | how well the title fits one of your tracks |
| location | your score for the job's location tier |
| skills | how many of your weighted skills the job names, minus gaps |

Experience in detail, with `years_experience: 4` and `stretch_years: 2`:

- asks 1 year or less: 0.45 ("below your level")
- asks 2 to 4: 1.0 ("fits")
- asks 5: 0.8, asks 6: 0.5 ("a stretch")
- asks more than 6 (`too_senior_over`): 0, and the job is flagged too senior

The parser reads "3-5 years", "5+ years", "at least five years", "between 3 and 5 years" and "7 yrs". It ignores company-age phrases ("founded 20 years ago") and numbers above 25. When "required" and "nice to have" years both appear, the required ones win. The largest minimum wins.

Skills: a skill counts when the job names it. Naming half of your weighted skills earns the full skills score. Each gap (a skill in `skills.lack` that the job names) takes 0.25 off, down to 0.5 off at most. A description under 200 characters scores 0.5, because it says too little to judge.

## Reasons

Each job gets four reasons, one short line each:

```
needs 3-5 yrs (you: 4): fits
title matches track backend
location: remote worldwide
skills: python, postgres; gaps: go
```

## Flags

A flag has a code and a plain reason. A hard flag makes `eligible` false. A soft flag is a warning.

| Code | Hard when |
|---|---|
| `too_senior` | the job asks for more than `too_senior_over` years, or the title has a `too_senior` word and asks for more years than you have |
| `title_excluded` | the title has a word from `title.exclude` |
| `off_track` | you set tracks and the title fits none of them |
| `region_restricted` | the job is limited to a region you cannot use ("US only", "must be based in X", "authorized to work in X", "Remote - X") |
| `no_sponsorship` | the text says no visa sponsorship and the job is in a country where you need one |
| `clearance_required` | a security clearance, ITAR or export-control status is required and you set `has_clearance: false` |
| `citizenship_required` | a citizenship is required and it is not in your `citizenships` |
| `company_excluded` | the company is in `exclude_companies` |

Soft flags: a time zone lock ("PST hours"), a very large years ask below the hard limit, a staff or principal title on a job that asks for no more years than you have.

## Location tiers

Each job lands in one tier, and your preferences give each tier a score from 0 to 1:

1. `remote_worldwide`: remote, and global or open to your region
2. `remote_home_country`: remote in your country or an allowed region
3. `hybrid_home_city`: hybrid in your city
4. `onsite_home_city`: on site in your city
5. `home_country_other`: elsewhere in your country
6. `other`: everywhere else, and remote jobs limited to a region you cannot use

A bare "Remote" counts as worldwide only when the description names your region, an allowed region or "worldwide". Otherwise it is `other` with the reason "region not stated". A job listed in several places gets the best tier among them.

## Every field in preferences.yaml

| Field | Meaning |
|---|---|
| `candidate.years_experience` | your years of experience (required) |
| `candidate.home` | `city`, `region`, `country`, `city_aliases`, `country_aliases` |
| `tracks` | a list of `{name, title_any, jd_any, weight}`; the title must contain a `title_any` word; `jd_any` words in the description raise the score a little; `weight` is 0 to 1 |
| `title.exclude`, `.too_senior`, `.junior` | title words. Junior titles lower the title score and say so in the reasons |
| `experience.stretch_years` | extra years a job may ask for and still be a stretch (default 2) |
| `experience.too_senior_over` | above this many years a job is too senior (default: your years plus 3) |
| `locations.tiers` | a list of `{name, kind, score}`, one per kind above |
| `locations.allowed_regions` | regions a remote job may be limited to and still suit you |
| `locations.region_aliases` | extra names for a region, such as `{united kingdom: [uk, britain]}` |
| `skills.have` | skills with a weight, such as `{python: 3, postgres: 2}` |
| `skills.lack` | skills you want flagged as gaps |
| `eligibility.needs_sponsorship_in` | countries where you would need a visa sponsor |
| `eligibility.authorized_in` | countries where you may work today |
| `eligibility.has_clearance`, `.citizenships` | clearance and citizenships you hold |
| `weights` | `experience`, `title`, `location`, `skills` |
| `thresholds.shortlist` | the score at which an eligible job is shortlisted |
| `exclude_companies` | company names or slugs to skip |

The `apply:` block in the same file belongs to the apply step, not to ranking.

## Skill names

`rank/skills_default.yaml` maps about 60 common skills to patterns with safe word boundaries. "Go" counts as the language only in a programming context ("Python, Go, Rust", "experience in Go", "Golang"). "Go to market" and "go-getter" do not count. A name that is not in the list is searched for as plain text, so you can add your own to `skills.have` or `skills.lack`.

## What it will not do

It does not read minds. Wording it does not know will slip through, and a reason can be wrong. Read `explain` before you apply.
