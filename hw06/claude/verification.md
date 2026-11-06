# Part D — Verification of Claude's `Top 10 Client Share`

**Workflow:** Draft → Test → Debug → Review. Prompt and Claude's full response: `dax_session.md`.
Metadata given to Claude: `model_metadata.md` (INFO.VIEW.COLUMNS, RELATIONSHIPS and MEASURES).

## Did Claude's measure run as written?
Yes. I ran Claude's DAX test query unchanged in DAX query view. It defines the measure as a query-scoped
`Top 10 Client Share (test)` and returns three results. All three ran without errors on the first try:

| Result | What it returned | Compared with pandas |
|---|---|---|
| A — by `dim_date[year]` + grand total | 2020 0.0704, 2021 0.0638, 2022 0.0553, 2023 0.0604, 2024 0.0616, Total 0.0616 | Identical to about 15 decimal places |
| B — by `dim_client[client_tier]`, 2024 | HNW 0.0314, Retail 0.0183, UHNW 0.0813, Total 0.0616 | Identical |
| C — the actual top 10 clients at the last 2024 snapshot | Clients 1001, 2361, 1331, 2281, 2183, 1245, 1885, 679, 1855, 796 | Same 10 clients, same order, same AUM; they sum to $784,005,019.49 = 6.16% of $12.73bn |

The full result grids are pasted at the end of `dax_session.md`. I did **not** click "Update model with changes",
so the `(test)` measure was never added to the model.

## Which rows of `measure_reconciliation.csv` prove it?
`Top 10 Client Share` at slices **Total**, **2024 HNW**, **2024 Retail** and **2024 UHNW** (file lines 17 and
87–89). All four match, with differences between 8e-12 and 3e-11 (tolerance 0.0001).

## Edge cases I checked
1. **Grand total (no filters).** Returns 6.16%, the same as 2024, because with no filter the last snapshot is
   2024-12-01. This is correct: "today's" concentration.
2. **`dim_date[year]` = 2022.** Returns 5.53%, the lowest of any year. 2022 is the only year with all 2,500 clients
   still active at year-end, so the same top balances are spread over a bigger book. Matches pandas exactly.
3. **The 2024 tier table.** Each tier ranks its *own* top 10: UHNW 8.13%, HNW 3.14%, Retail 1.83%. This shows the
   measure respects the tier filter, as the business definition requires ("within the current filter").
4. **A client who left before the last date.** This is the point of pinning the date, but Claude Code's review found
   that our data can't test it: none of the 175 departed clients was large enough to make a top 10, so pinned and
   unpinned versions give the same numbers. I added a hand-built **self-test** to the reconciliation script, with a
   departed client who has the biggest balance, and it confirms the pinned logic excludes them.
5. **Ties.** Claude added `dim_client[client_id], ASC` as a tie-breaker so TOPN always returns exactly 10 clients.
   No ties occur at the top of the 2024 data, but the measure stays correct if they ever do.

## What I changed, and why
**Nothing in the logic.** I added the measure to `_Measures` exactly as Claude wrote it, only removing the
`(test)` suffix from the name, because it matched pandas on every slice on the first try.

## A claim I refuted, and one I confirmed
- **Refuted:** Claude said that at the grand total the last snapshot is *"probably October or November 2026"*,
  and described *"a partial year like 2026"*. That is wrong. The data covers 2020–2024: the grand-total row of its
  own test query shows Ending AUM $12,729,572,078.86 and 2,325 clients, which are the **2024-12-01** values, and
  `dim_date` ends on 2024-12-31. Claude guessed from today's date instead of reading the data, a reminder
  to check every factual claim, not just the code.
- **Confirmed:** Claude said the denominator (`[Ending AUM]` in the same context) and the ranking date "always agree".
  The test query's Ending AUM column matches the reconciled Ending AUM for every year and tier, so the share is
  always taken against the same snapshot it ranks on.