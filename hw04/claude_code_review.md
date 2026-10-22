I read all 1,379 lines of 01_profile.py and compared the code against the raw CSVs and the dq_summary_raw.csv it last produced. I changed no files.

The most important point is that several ERROR/WARN findings in the current report come from how the checks are written, not from defects in the data. Fix these before the report is used in Part B.

A. Checks that give misleading results now (confirmed in the current report)
"Fee/Snapshot before client_since" (ERROR, 858 and 930 rows) — L452-457. fee_date and snapshot_date are always the 1st of the month (period start), but client_since is a real calendar day. A client who joined on 2020-03-15 gets a March fee dated 2020-03-01, which is "15 days early". The detail line shows a median of 15 days early, and "clients affected" equals rows (858/858, 930/930), so it is exactly one row per client: their joining month. This is a dating convention, not a defect. The check should compare at month level.
"Snapshot not on a calendar month-end" (WARN, 129,547 of 129,547 rows) — L490-493. It fails every row for the same reason: snapshots use month-start dates. The INFO rule "fee_date not a month-end" (L366) fires on all fee rows too. A rule that fails 100% of rows is testing the wrong idea.
Fee reconciliation (WARN, 28,742 of 28,746 and 7,653 of 7,653) — L525-535. Under both readings, almost every client-month mismatches, and most groups exist on only one side. That suggests the assumed grain (client × calendar month) or the mapping is wrong; it doesn't give a usable list of bad rows. Treat it as "the tables don't reconcile at this grain", not as 28k defects. Also, abs: True hides any sign errors.
"Dominant sign of shares" INFO — L932. For Deposit, Withdrawal and Advisory Fee, where shares is blank, it reports 'neg'. (NaN > 0).mean() is 0, so "all missing" is shown as "negative". Zeros also count as negative there.
Blank security_id (WARN, 101,528 rows) — L761. Almost all of these are legitimate cash transactions. Your own row rule shows 0 Buy/Sell/Dividend rows without a security, so this WARN overstates the problem.
Row/column count ERRORs may come from stale expected numbers. The script expects dim_client = 2,525 but the file has 2,500. It expects fact_transactions = 298,772 (your HW2 count) but the file has 298,572. The comment at L286 assumes "2,525 = 2,500 + 25 duplicates", which the data doesn't support (the natural-key checks find 0 duplicates). Expected columns 9 and 13 don't count the flag columns. Check these numbers against the assignment sheet; they might belong to a different extract.
B. Bugs and logic errors
txn_type rules match exact text only — L427-437. d.txn_type.isin(SECURITY_TXN) doesn't trim or ignore case, while filter_mask and sign_by do. A value like "buy" or " Buy " would skip every security rule and silently pass. The values are clean today, but this is the file you'll rerun after cleaning.
rounding_tol uses the finest decimals; it should use the coarsest — L152-159. If the inputs are rounded to 4 dp and the target to 6 dp, the tolerance is 1.5e-6 when it should be about 1.5e-4, which causes false failures. It also only looks at the longest value in each column, and it ignores scientific notation like 1e-05.
Date lookups join on raw text — L1160-1166, and _lookup at L1082. The trading-day and month-end rules match txn_date text to dim_date.date text. A date in another format (e.g. 03/15/2021) gets no match, drops out of "testable", and is never flagged. They should join on parsed dates, as the RI check already does at L1035-1049.
NaN is handled differently from rule to rule. Rules using != flag NaN rows as wrong: year/month vs date, and benchmark mode at L401 (an all-blank group gives NaN != NaN, which is True). Rules using <, > or <= let NaN rows pass: client under 18, the future-date check, price ≤ 0. So an unparseable date is an error in one rule and invisible in the next.
The date_id (YYYYMMDD) rule can never fire — L318-320. date_id holds 1, 2, 3… (a surrogate key), so the 8-digit pattern never matches and the rule always reports 0. It looks like a passed check, but nothing was tested.
A wrong filter value is reported as a clean pass, not a CONFIG problem.
rule_reconcile_totals returns INFO with 0/0 when a filter matches nothing (L1218-1221).
rule_recompute with an empty filter gives fit = 0 and INFO with 0 rows.
Neither goes into SKIPPED, so the screen summary never warns you.
Picking the best of several formulas can overfit — L1148. It's harmless today (the /12 formula fits 100%), but in general picking the best of N inflates the pass rate. It would help to fail loudly when the best fit is low.
Age rule uses calendar years only — L298. age - (2024 - year(client_since)) can be off by up to one year.
A blank certifications value is counted twice — L839-840. "".split(",") gives [""], so the row is reported as a bad token as well as a blank. Similarly, a required column holding a null word like NULL is only a WARN (L770), because the ERROR check uses blank() and not missing().
Unparseable dates in _period_totals merge into one "NaT" period per client — L1203. This creates fake mismatches or matches in the reconcile and exists-in rules.
The flag-crosstab "advisor differs" condition doesn't normalise IDs — L561. It compares raw text, while rule_same_as_dim uses canon_id, so "22" vs "22.0" behave differently between the two.
Error handling is narrow. Rules only catch KeyError and AttributeError (L941, L1260). A TypeError or ValueError in one rule crashes the whole run instead of being logged.
Ambiguous dates silently use US order — L64-67. %m/%d/%Y is tried before %d/%m/%Y, so 03/04/2021 becomes March 4 with no warning. It would be better to count how many ambiguous values there are.
C. Hard-coding
The data's time window is written into 5+ places: AS_OF_YEAR = 2024, LAST_MONTH = "2024-12-01", coverage 2020–2024, and the year ranges in dim_date and the snapshot table. These should come from dim_date's min and max so they can't drift apart.
cash_pct range of (0, 100) — L383. The data is on a 0–1 scale, so a value of 1.5 (150%) passes. The bound doesn't fit the data's scale.
minority_scale uses a |v| > 1 cut-off. A real 120% return (1.2) gets flagged, while a percent-scale 0.8 (meaning 0.8%) gets through. It's fine as a heuristic, but say so in the report.
Expected row/column counts (see item 6).
Reference lists: REGIONS, SECTORS, FEE_TYPES, TXN_TYPES, the benchmark mapping (it matches the current dim_benchmark), and US_STATES. Make sure they come from the data dictionary rather than being guessed.
Unexplained thresholds: 2% type-inference tolerance, 90% dominant shape, 3× IQR, 0.8 sign share, 5% aum_basis tolerance, and the fee tolerances.
D. Minor or cosmetic
dt() re-parses the same date column on every rule call. It's only slow, not wrong.
The calendar-coverage finding is filed under group "1 Column", but other dim_date and cross-table checks use different groups.
The flag-value check accepts "" as a valid flag value, so blank flags only show up in the detail text.
Priorities: fix items 1–3 (they are what put most of the false ERROR/WARN volume in the report), then 7–10 (they could hide real defects after cleaning). Also confirm the expected counts in item 6 before treating them as defects.