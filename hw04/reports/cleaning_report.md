# Wildcat Capital — Data Cleaning Report (HW4)

**Audience:** Portfolio committee
**Sources:** decision_log.md, cleaning_log.csv, data_quality_scorecard.csv, ri_results.csv, reconciliation_results.csv, claude_code_review.md

---

## 1. Executive summary

The data extract arrived already partly cleaned upstream. It has 25 fewer clients and 200 fewer transactions than the assignment sheet lists, and two flag columns (`is_return_suspect`, `is_post_departure_txn`) had been added before we received it. We examined 15 data-quality issues. Most turned out to be legitimate structure or dating conventions rather than errors. The real concerns are weekend-dated transactions, extreme or implausible returns, and fee records that don't reconcile between two tables. We added 2 flag columns (`is_non_trading_day` on fact_transactions and `is_return_outlier` on fact_portfolio_snapshot), deleted 0 rows and changed 0 original values. The data is ready for Power BI, provided users apply the filters and source-of-truth rules in Section 6.

## 2. Cleaning summary

| # | Issue | Rows affected | Decision | Reason |
|---|---|---|---|---|
| 1 | Buys/Sells on non-trading days | 84,946 (40,630 Buy/Sell) | Flag (`is_non_trading_day`) | Weekend dates appear evenly across all transaction types; the true date can't be determined, so dates were not moved. |
| 2 | Extreme returns not flagged | 3,977 (576 not already suspect) | Flag (`is_return_outlier`) | Adds our 3× IQR test alongside the original flag without overwriting it. |
| 3 | Returns flagged but not extreme | 474 | Leave as is | The original flag likely uses a different test (sudden jumps, near −100%); not proven wrong. |
| 4 | Returns above 100% | 977 | Leave as is (already flagged) | The "wrong scale" theory was tested and failed; the true values can't be recovered. |
| 5 | Post-departure transactions | 2,410 (131 clients) | Flag (existing flag kept) | Verified against client status and last snapshot; these are real money movements. |
| 6 | Securities sharing a name | 6 | Leave as is | Each pair has a different ticker; they are different securities. |
| 7 | Blank sector and expense ratio | 500 (219 + 281) | Leave as is | Blank means "does not apply" (no sector for funds, no expense ratio for stocks). |
| 8 | Blank security fields on cash rows | 101,528 | Leave as is | Deposits, withdrawals and fees don't involve a security. |
| 9 | Advisor certifications = "None" | 6 | Leave as is | "None" is a real answer: the advisor holds no certifications. |
| 10 | Fees/snapshots dated before client_since | 1,788 (858 fee + 930 snapshot) | Leave as is | Records are dated the 1st of the month they cover; 0 violations at month level. |
| 11 | Fees don't reconcile with transaction fee debits | 28,746 | Leave as is (known limitation) | The tables record fees differently; fact_fees is internally consistent and is the authority. |
| 12 | Snapshot months with no fee | 7,350 | Leave as is (known limitation) | Could be waivers or partial months; filling would invent revenue. |
| 13 | Unknown risk profile | 75 | Leave as is | A risk profile is a suitability record and shouldn't be inferred. |
| 14 | Row/column counts differ from assignment sheet | 25 clients; 200 transactions; 0 snapshots | Leave as is; document | Rows were removed upstream and aren't available to recover. |
| 15 | dim_date ignores market holidays | 9 | Leave as is (known limitation) | No holiday calendar exists in the source data. |

## 3. Data quality scorecard: before vs after

| Table | Measure | Raw | Clean |
|---|---|---|---|
| fact_transactions | pct_rule_pass | 97.8974 | 100.0 |
| fact_transactions | pct_issues_flagged | 0.0 | 100.0 |
| fact_portfolio_snapshot | pct_rule_pass | 99.9557 | 100.0 |
| fact_portfolio_snapshot | pct_issues_flagged | 85.5167 | 100.0 |

The raw figures are lower partly by design: `is_non_trading_day` and `is_return_outlier` did not exist before cleaning, so issue rows could not yet be flagged (see the circular-rules limitation in Section 5).

All 13 relationships between tables matched 100% in both the raw and clean stages, with 0 orphan rows. The only null keys are the 101,528 cash transactions with no security_id (34.0045%), which is expected (Issue 8).

## 4. Key judgment calls

**Issue 4: not converting returns above 100%.**
*Decision:* leave the 977 rows unchanged; all are already flagged `is_return_suspect = 1`.
*Justification:* if these were percent-scale typos, dividing by 100 would line them up with the client's neighboring months. It did so only 0.7% of the time, so the "wrong scale" theory is disproven. The values instead build smoothly month to month (e.g. client 1003: 1.00 → 1.05 → 1.07 → 1.15 → 1.30), which looks like returns that never reset each January. The correct values can't be recovered without underlying prices.
*Risk:* any average of return_ytd that doesn't exclude flagged rows will be badly inflated.

**Issue 10: "before client_since" is a month-start convention, not an error.**
*Decision:* leave the 858 fee and 930 snapshot rows unchanged.
*Justification:* fees and snapshots are dated the 1st of the month they cover, so a client who joined on March 15 correctly has a March record dated March 1. The initial audit labelled these as errors; the Claude Code review showed the check itself was flawed (exactly one row per affected client, median 15 days early). At month level there are 0 violations.
*Risk:* a future day-level comparison would wrongly flag these rows again.

**Issue 13: not filling "Unknown" risk profiles.**
*Decision:* keep "Unknown" for the 75 clients (48 Retail, 18 HNW, 9 UHNW).
*Justification:* their snapshots all use the 60/40 Blend benchmark used by Balanced clients, which suggests they are probably Balanced. But a risk profile is a regulatory suitability record from the client questionnaire, and inferring it could misrepresent a client's risk tolerance.
*Risk:* risk-profile charts will show an "Unknown" group of 75 clients (3%). Compliance should collect the real profiles.

**Issue 1: flagging weekend dates rather than moving them.**
*Decision:* flag all 84,946 weekend-dated transactions (40,630 of them Buy/Sell); dates unchanged.
*Justification:* weekend dates appear in about 28% of every transaction type, including deposits and withdrawals, which points to how the source system stamps dates rather than a few bad trades. There's no way to know whether the true date is the Friday before or the Monday after.
*Risk:* if these are posting dates, the flag is noise but nothing is lost. Shifting dates on a wrong guess would move totals into the wrong period near month-ends.

## 5. Limitations

- **Issue 3:** 474 rows are flagged suspect by the original process but pass our test. If that flag is too broad, some normal returns are excluded from analysis.
- **Issue 11:** fee revenue from fact_transactions will not match fact_fees. All 28,746 client-months present in both tables differ, and 93,451 client-months exist only in fact_fees.
- **Issue 12:** 7,350 client-months have a snapshot but no fee (72 are the client's joining month; 362 belong to inactive clients). If these fees are genuinely missing, revenue is understated by up to about 6% of client-months.
- **Issue 14:** row counts won't match the assignment sheet (dim_client 2,500 vs 2,525; fact_transactions 298,572 vs 298,772). The removed rows aren't available. fact_portfolio_snapshot matches the sheet (129,547).
- **Issue 15:** dim_date marks only the 522 weekend days as non-trading. 9 weekday holidays (e.g. 2020-01-01) are marked as trading days, so trades on market holidays are not flagged.
- **`is_non_trading_day` means weekend-dated only**, not "market closed", for the reason above.
- **The "issue handled" scorecard rules are circular by design.** They recompute the same tests used to create the flags, so on clean data they can only score 100%. They prove every known issue row is flagged, not that the underlying values are correct.

## 6. Recommendations for Power BI users

- **Filter returns before averaging:** exclude rows where `is_return_suspect = 1` and/or `is_return_outlier = 1` before averaging return_ytd.
- **Use fact_fees as the source of truth for fee revenue**, not Advisory Fee debits in fact_transactions.
- **Group securities by ticker (or security_id), not by name:** three names are shared by two different securities each.

---

`AI-assisted report — reviewed for factual accuracy on 2026-10-22 by Sarah Lie`
