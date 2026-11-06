# HW6 — DAX Measure Library: AUM & Performance

MIS3060 Business Intelligence with AI · Sarah Lie

## Folder structure

```
hw06/
├── README.md                     ← this file
├── claude_code_review.md         ← Claude Code review of the reconciliation script
├── data/                         ← the 8 Wildcat Capital Clean CSVs (pandas side)
├── powerbi/
│   ├── hw06.pbix                 ← posted Wildcat_Star_Model + _Measures table + Measures page (21.9 MB)
│   └── measures.md               ← Part A documentation and Part C answers
├── scripts/
│   ├── 01_reconcile_measures.py  ← Part B: recomputes every measure in pandas and compares
│   └── 02_part_c_evidence.py     ← Part C: pandas evidence for questions (a)–(d)
├── reports/
│   ├── powerbi_values.csv        ← 91 values exported from Power BI (DAX query view)
│   ├── measure_reconciliation.csv← Part B result: 91 of 91 match
│   └── part_c_evidence.csv       ← Part C numbers
└── claude/
    ├── model_metadata.md         ← Part D: INFO.VIEW columns, relationships, measures
    ├── dax_session.md            ← Part D: my prompt, Claude's response, test-query results
    └── verification.md           ← Part D: how I verified Claude's measure
```

## How to run

From the repo root (`C:\MIS3060\mis3060-bi-ai`), with the venv active:

    python hw06\scripts\01_reconcile_measures.py
    python hw06\scripts\02_part_c_evidence.py

`01_reconcile_measures.py` first runs a self-test on hand-built rows, then recomputes all measures from the
CSVs without reading Power BI, then compares them with `reports/powerbi_values.csv`. It exits with an error if
any row fails. Current result: **91 of 91 match** (88 with values plus 3 expected blanks for 2020, which has no
prior year). The largest differences are $0.00009 on currency (tolerance $0.01) and 5e-11 on ratios (tolerance 0.0001).

`powerbi_values.csv` was produced by one DAX query in DAX query view that returns `measure, slice, value` for
every required slice: all 16 measures at the grand total, the year measures for 2020–2024, the tier measures for
2024, and the month measures for December 2024.

## Power BI

`powerbi/hw06.pbix` starts from the posted `Wildcat_Star_Model.pbix`. I added a `_Measures` table with 16 measures
(Total Fees, Net Flows, AUM (naive SUM) and measures 1–11) and a **Measures** page; the file is saved with that page open.
It is 21.9 MB, under GitHub's 100 MB limit.

**Note on the cards:** the four card visuals rendered blank on the Apporto virtual desktop, although the same measures
display correctly in tables. I kept the four cards on the page and added a one-row table beside them showing
Ending AUM, Ending Clients, Avg AUM per Client and Top 10 Client Share.

## Mismatches and fixes

The reconciliation matched on the first run, so neither side had to be corrected. Two problems came up while
building, both caught before reconciling:
- **`AUM-Weighted Alpha` failed to compile** with "The syntax for 'LastDate' is incorrect". `LastDate` is reserved
  because `LASTDATE` is a DAX function, so I renamed the variable to `LastSnapshot`.
- **Blank expected values:** `Ending AUM LY`, `AUM YoY %` and `Organic Growth Rate` are blank for 2020 in both tools.
  This is correct (there is no 2019), so the script keeps a list of expected blanks and fails on any other blank.

## What Claude Code flagged and what I did

Full review in `claude_code_review.md`.

| Claude Code finding | What I did |
|---|---|
| The date-pinning in Top 10 Client Share isn't tested: no departed client is big enough to reach a top 10, so pinned and unpinned versions match | Added a self-test with a hand-built departed client who has the biggest balance; it must be excluded. Explained in `claude/verification.md` |
| Suspect exclusion isn't tested for HNW and UHNW (all 148 suspects at the last date are Retail) | The self-test includes a large HNW suspect row that must be excluded from alpha |
| A blank on both sides always counted as a match | Added a list of expected blanks (only the three 2020 rows); any other blank now fails, and blank matches are printed separately |
| Ratio tolerance 0.0001 is loose compared with the real differences | Kept the assignment's tolerance, but the script now prints the largest actual difference per measure type (5e-11) |
| Net Flows assumes withdrawals are positive; the Total slice was clipped to dim_date | Script now asserts every withdrawal is positive and that no fact date falls outside dim_date |
| Fee Yield divides by snapshot AUM, but about 7,350 client-months have AUM and no fee; both tools make the same choice | Not a code bug; investigated it in Part C (b) as the data limitation behind the gap with the Effective Fee Rate |
| txn_type comment didn't say it trims whitespace | Comment corrected |
| **02_part_c_evidence.py:** no code bugs; confirmed (a)–(d) independently | — |
| Some numbers in measures.md (Firm row, UHNW's 76% share, Retail's $448M base) weren't produced by the script | Added a Firm row, tier shares of AUM and starting balances to the script so every number is traceable |
| (d) compares Dec-to-Dec AUM growth with calendar-year flows | Script also computes organic growth on the snapshot window (2023-12-01 to 2024-11-30); added a sentence to measures.md: the conclusions don't change |
| Couldn't confirm the ICE 9 Effective Fee Rate formula | Confirmed from the ICE 9 handout: `DIVIDE ( [Total Fees] * 12 * 10000, SUM ( fact_fees[aum_basis] ) )`, 45.6 bps firm-wide; cited in Part C (b) |
| Ratios printed as raw decimals in the console | Console now prints percentages; the CSV keeps raw decimals |

## AI use

Claude Desktop drafted both scripts and, for Part D, the `Top 10 Client Share` measure. I built the other measures
and the report page in Power BI, ran everything myself, and checked every measure against pandas before
committing. Claude Code reviewed the reconciliation script.