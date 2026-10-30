# HW5 — Wildcat Capital Star Schema in Power BI

MIS3060 Business Intelligence with AI · Sarah Lie

## Folder structure

```
hw05/
├── README.md                ← this file
├── star_design.md           ← Parts A, B, C, E and F
├── claude_code_review.md    ← Claude Code review of the script
├── data/                    ← the 8 Wildcat Capital Clean CSVs, as provided
├── scripts/
│   └── 01_keys_and_grain.py ← proves keys, relationships and grain (Parts A, B, E)
├── reports/
│   └── keys_and_grain.csv   ← output of the script
└── powerbi/
    ├── hw05.pbix            ← Part D model (21.8 MB, under GitHub's 100 MB limit)
    └── model_view.png       ← Model view: 8 tables, 13 relationships
```

## How to run

From the repo root (`C:\MIS3060\mis3060-bi-ai`), with the venv active:

    python hw05\scripts\01_keys_and_grain.py

It reads the 8 CSVs in `hw05/data/` as text, changes nothing, and writes `hw05/reports/keys_and_grain.csv`.
It exits with an error if any check fails. Current result: 46 PASS, 0 FAIL — row counts match the
handout, 8 unique primary keys, 13 relationships with 0 orphans and 0 blank required keys, fact dates
join on `dim_date.date` (100%) not `date_id` (0%), and all three fact grains are unique.

The Power BI model was built in Power BI Desktop on the Apporto virtual desktop, following
`powerbi_guide.md`. Open `powerbi/hw05.pbix` to see it.

## Power BI model summary

- 8 tables loaded as provided; column types set in Power Query (`zip_code` changed to Text to keep
  leading zeros; `expense_ratio_bps` changed to Decimal)
- 13 relationships, all many-to-one, single direction: 12 active, 1 inactive (`dim_client → dim_advisor`, see star_design.md Part E b)
- Fact dates joined to `dim_date[date]`; `dim_date` marked as the date table
- Row counts in Power BI match the handout for all 8 tables
- Checks done in the report view: the only (Blank) row is the cash transactions with no security;
  an advisor-region slicer filters all three fact tables

## What Claude Code flagged and what I did

Full review in `claude_code_review.md`.

| Claude Code finding | What I did |
|---|---|
| Blank foreign keys (other than `security_id`) never caused a FAIL | Required keys and fact dates now FAIL if any are blank; `security_id` stays allowed-blank on cash rows only |
| Blank `txn_date` was never checked; the date check compared a rounded % to 100 | Date checks now require 0 orphans and 0 blanks |
| Key normalisation ("45.0" → "45") could hide dirty keys that wouldn't join in Power BI | The script counts keys that only matched after normalising and FAILs if there are any |
| The final `assert` disappears under `python -O` | Replaced with `sys.exit(1)` when there are failures |
| PK check was text-only; placeholder text ("NULL", "None") counted as real keys | PKs must be plain whole numbers (dates must be YYYY-MM-DD); placeholders count as blank |
| Grain blanks were ignored; skipped numeric columns disappeared silently | Blank grain columns now give NOT UNIQUE; skipped columns are listed with the reason (only `account_type`, which is text) |
| Closing message overstated what was enforced | It now says exactly what is enforced and what is only reported |

Re-running after the fixes gave the same results: no data problems were hiding, but the script now
fails loudly if one ever appears.

## AI use

Claude Desktop drafted the script. I ran it in VS Code. Claude Code reviewed it before I committed.
I built the Power BI model myself on Apporto and checked the row counts, (Blank) row and slicer
results against the CSVs.