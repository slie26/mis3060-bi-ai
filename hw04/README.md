# HW4 — Cleaning the Wildcat Capital Data

MIS3060 Business Intelligence with AI · Sarah Lie

## Folder structure

```
hw04/
├── README.md                  ← this file
├── decision_log.md            ← Part B: 15 issues, decided before cleaning code
├── claude_code_review.md      ← full Claude Code reviews for Parts A, C, D
├── scripts/
│   ├── 01_profile.py          ← Part A: generic audit of all 8 tables
│   ├── 02_clean.py            ← Part C: cleaning program with asserts
│   └── 03_validate.py         ← Part D: RI function, rules, reconciliations, scorecard
├── data/
│   ├── raw/                   ← the 8 files as provided (never modified)
│   ├── clean/                 ← 8 clean tables + README_clean.md
│   └── audit/                 ← cleaning_log.csv, value_changes.csv, quarantine_*.csv
└── reports/
    ├── profile_raw.csv, dq_summary_raw.csv          ← Part A
    ├── data_quality_scorecard.csv                   ← Part D (raw vs clean)
    ├── ri_results.csv, rule_results.csv,
    │   reconciliation_results.csv, iqr_outliers.csv ← Part D detail
    └── cleaning_report.md                           ← Part E

## How to run

From the repo root (`C:\MIS3060\mis3060-bi-ai`), with the venv active, in this order:

    python hw04\scripts\01_profile.py     # audit raw data   → reports/profile_raw.csv, dq_summary_raw.csv
    python hw04\scripts\02_clean.py       # clean            → data/clean/, data/audit/
    python hw04\scripts\03_validate.py    # validate raw + clean → reports/data_quality_scorecard.csv

Each script stops with an assertion error if a step does not do what it claims.

## Note on the data

The provided files differ from the assignment sheet: dim_client has 2,500 rows (sheet: 2,525),
fact_transactions has 298,572 rows (sheet: 298,772), and two flag columns
(`is_post_departure_txn`, `is_return_suspect`) were already present. The instructor confirmed
these are the files to use. The extract was partly cleaned upstream, so most decisions are
"flag" or "leave as is" (Decision log, Issue 14).

## Results in one line

0 rows deleted, 0 original values changed, 2 flag columns added (`is_non_trading_day`,
`is_return_outlier`); all 13 relationships match 100%; rule pass 97.8974% → 100% for
fact_transactions and 99.9557% → 100% for fact_portfolio_snapshot.

## What Claude Code flagged and what I did

Full text of each review is in `claude_code_review.md`.

### Part A — 01_profile.py
| Claude Code finding | What I did |
|---|---|
| "Fee/snapshot before client_since" (858 / 930 ERRORs) was a false alarm: fees and snapshots are dated the 1st of the month | Changed the check to month level → 0 violations. Logged as Issue 10, leave as is |
| "Snapshot not on month-end" failed 100% of rows — testing the wrong idea | Downgraded to INFO; month-start is the convention |
| Fee vs transaction reconciliation mismatched ~100% of groups — wrong grain, not 28k defects | Reported as INFO; logged as Issue 11 (known limitation) |
| Blank security_id was WARN although the row rule proves they're cash rows | Downgraded to INFO; Issue 8 |
| Row-count differences tagged ERROR | Changed to INFO; Issue 14 |
| txn_type matching was case/space sensitive; date lookups joined on raw text; NaN handled inconsistently | Fixed: trim + case-insensitive matching, parsed-date joins, NaN flagged consistently |
| date_id YYYYMMDD rule could never fire; empty filters looked like passes; cash_pct range 0–100; hard-coded years | Removed the rule; empty filters go to SKIPPED; cash_pct 0–1; years from dim_date |
| Result | ERRORs went from 4 to 0 |

### Part C — 02_clean.py
| Claude Code finding | What I did |
|---|---|
| Clean files had Windows CRLF line endings; "byte-for-byte identical" claim was untested | Added `lineterminator="\n"`; script re-reads each written file and asserts original columns match raw |
| Decision-log mismatches only printed, never stopped the script | Now collected and asserted before any file is written |
| Issues 10–12 used hard-coded numbers | Now re-measured from the data |
| Sign rule only printed; Issue 8 checked one way; Issue 5 only partly verified | Asserted amount > 0; Issue 8 both directions; Issue 5 also checks "after last snapshot month" and "all in 2023" |
| dim_date marks 2020-01-01 as a trading day — no market holidays | **New finding:** added Issue 15 to the decision log; README_clean.md says `is_non_trading_day` means weekend-dated only |
| Wording errors in Issue 12 and 14 notes | Fixed |

### Part D — 03_validate.py
| Claude Code finding | What I did |
|---|---|
| `check_referential_integrity` broke on a normal `pd.read_csv` load (45.0 vs 45, NaN keys) — important because HW5 reuses it | Treats NaN and blanks as null, normalises whole-number floats; added a self-test comparing a text load with a plain load |
| Nothing failed when clean data was bad | Reports are written first, then asserts: 0 orphans, 100% rule pass, 100% on reconciliations (a)(c)(d) on clean |
| Max diff displayed as $0.01 (really $0.0050) | Shows 4 decimals |
| Reconciliation (b) left unmatched fees out of the denominator | Now counted as not matching |
| Missing rules (dim_benchmark, advisor ranges, snapshot year/month, dim_date fields, reverse post-departure) | Added; 65 rules on clean, all pass |
| "Issue handled" rules are circular | Kept, with comments, and stated as a limitation in the report |

### Problem caught outside Claude Code
When Claude Desktop merged fixes into 03_validate.py, it reverted the confirmed allowed-value
lists to old guesses and dropped the issue-handled rules. I caught this by checking the file
before running it, restored the confirmed lists and rules, and re-ran before committing.

## AI use

Claude Desktop drafted every script and the cleaning report. I ran and debugged each script in
VS Code. Claude Code reviewed each script before I committed it. Every number in
cleaning_report.md was checked against the script output.