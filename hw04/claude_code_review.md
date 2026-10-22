## Part A review (01_profile.py)
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

## Part C review (02_clean.py)
Clean vs raw
I compared all 8 tables byte by byte and field by field:

Line endings: raw files use LF (\n), but every clean file uses CRLF (\r\n). pandas 3.0.5 to_csv defaults to os.linesep, which is CRLF on Windows. This accounts for all the extra bytes. For example, dim_advisor has 26 lines and is exactly 26 bytes larger.
Everything else is identical: no BOM in either set, the same quote characters in the same places, the same row counts, and every original field matches once the CRs are removed. fact_transactions and fact_portfolio_snapshot differ only by the appended ,0/,1 column. Their byte counts match exactly once the header and the CRs are included.
The docstring is wrong as a result: 02_clean.py:19-20 claims the output is "byte-for-byte the same", which isn't true. The final check at line 538 compares DataFrames in memory, not the files written, so it can't catch this. The fix is lineterminator="\n" on the to_csv calls at lines 544–545, 550 and 554. Re-reading the written file and comparing it to raw would also catch quoting changes in future.
Places where the script could silently do the wrong thing
compare_to_log only prints and never stops the script (line 113). If the data or logic drifts, the run still ends with "DONE - all assertions passed", and a "DIFFERS" line is easy to miss in a long output. All counts match today (checked against cleaning_log.csv). Consider counting the mismatches and failing at the end.
Issues 10, 11 and 12 use hard-coded numbers (lines 473-481): 858+930, 28,746 and 7,350. The docstring says every leave-as-is issue is re-measured, but these three are not. If the raw data changed, the audit log would still show the old numbers.
Issue 1's evidence total isn't checked. The decision log quotes 84,946 flagged rows across all types, but LOG_EVIDENCE only covers the 40,630 Buy/Sell figure. It matches today, but nothing would warn you if it changed.
"Non-trading day" means weekend only. In dim_date, is_trading_day=1 on market holidays (2020-01-01 is marked as a trading day), so holiday trades are never flagged. The decision log says "weekend-dated", so the script is consistent with it, but the column name is_non_trading_day suggests more than it checks. Worth one sentence in README_clean.md.
Step 5b compares absolute values (line 377). A Buy or Sell recorded with the wrong sign would still pass. The sign breakdown is printed, but no rule is enforced.
Issue 8 is only checked one way. CASH_TYPES is defined at line 83 but never used. The script reports which transaction types have blank security fields, but doesn't assert that they are all cash types, or the reverse: that no cash row has a security. I checked by hand and found 0 violations either way.
Low risk, for future quarantine use: pd.concat onto an empty DataFrame with all-object columns (line 514) can trigger pandas warnings or dtype surprises once rows are actually quarantined. No rows are quarantined now, so it has no effect.
Mismatches with decision_log.md
Issue 14, fact_portfolio_snapshot: the script logs it with the same note as the other two tables: "partly cleaned upstream; removed rows unavailable" (line 496). But this table's raw row count equals the sheet's (129,547, diff 0). Its only difference is the extra is_return_suspect column, so the note is misleading for this table.
Issue 12 wording: the decision log says 362 client-months belong to inactive clients, but the script's note says "362 inactive clients" (line 480).
Issue 5: the decision log also says all flagged rows are dated 2023 and fall after the client's last snapshot. The script only checks that the clients are inactive. That's acceptable if you treat those two points as a one-off follow-up, but the log entry for this issue says "Verified", which implies more was checked.
Issue 4's "0.7%" figure is only repeated in the note, not recalculated. That's fine as long as the log entry is clear it's a one-off finding.
Everything else matches the decision log: the counts for Issues 1–9 and 13, the names in Issue 6 (still 3 after normalizing case and punctuation), the 219/281 split in Issue 7, and Issue 14's 2,500 and 298,572 rows. No rows are deleted, and is_return_suspect and is_post_departure_txn are left unchanged.

   ## Part D review (03_validate.py)
I reviewed 03_validate.py and the five CSVs it wrote, and ran a couple of read-only tests. No files were changed.

Part D requirements: all met.

Requirement	Status
One reusable check_referential_integrity	✅ line 221, but see bug 1 below
All 13 relationships	✅ Matches README_clean.md §1 exactly (10 on IDs, 3 on dates)
Rule checks	✅ 50 rules on raw, 53 on clean
2+ reconciliations	✅ Five checks, labelled (a) to (e)
IQR on 2 columns	✅ fact_transactions.amount and fact_portfolio_snapshot.aum
Raw vs clean scorecard	✅ 16 rows: 8 tables × 2 stages
Bugs
check_referential_integrity gives wrong results, or crashes, when it gets normally loaded DataFrames. This matters because the docstring says to reuse it in HW5. Your pandas is 3.0.5. I passed it frames loaded with a plain pd.read_csv(...):

fact_transactions.security_id loads as float, so its values become "45.0" while dim_security has "45". 0 of 197,044 rows matched.
Under pandas 3, missing values stay as NaN rather than "". So is_null (line 271) finds 0 nulls, and the 101,528 cash rows get counted as orphans.
Then sorted(orphan_values.unique()) (line 290) mixes NaN with text and raises TypeError.
It only works today because load_stage reads every column as text with keep_default_na=False. Fix: treat isna() as null too, normalise whole-number floats (45.0 → 45) or document that inputs must be read as text, and drop NaN before sorting.

The fee reconciliation detail is misleading. It prints "max diff $0.01", but the real maximum is $0.0050000000000000044 (half a cent): the :,.2f format rounds it up. The check itself is fine, but anyone reading the CSV will think some fees are off by a full cent. Show 4 decimals.

Checks that pass by construction
Both "ISSUE HANDLED" rules are circular.

ISSUE_RETURN (line 484) recomputes the same 3 × IQR on return_ytd that 02_clean used to create is_return_outlier.
ISSUE_NON_TRADING and the rule at line 464 recompute 1 - dim_date.is_trading_day, which is exactly how 02_clean set is_non_trading_day.
So on clean they can only score 100%. They show the flag column exists and matches its own formula, not that the issue is solved. Also, dim_date doesn't mark holidays (Issue 15), so "non-trading day" really means weekend. Holiday trades pass silently, and the rule name claims more than it checks.

On raw, pct_rule_pass and pct_issues_flagged are 0% or lower partly by design. On raw, is_non_trading_day doesn't exist yet, and flag_or_zero treats it as all 0s. So fact_transactions scores 0% flagged and 97.89% rule pass mainly because cleaning hadn't added a column yet. That's a documented choice, but explain it in your write-up, or the raw-vs-clean gap looks like quality cleaning didn't produce. Clean also has 3 more flag-format rules than raw, so the rule sets aren't identical.

Nothing fails the run when clean data is bad. The only asserts are the hard-coded issue counts (lines 745-752). If clean had orphans, rule failures or a reconciliation below 100%, the script would still exit normally. Consider asserting 0 orphans and 0 rule failures for the clean stage. Also, those asserts run before the CSVs are written, so a failed assert leaves you with no reports to debug from.

Reconciliation (b) only counts fees that have a matching snapshot. Fees with no snapshot that month are left out of pct_matching, so it can show 100% while some fees have nothing to compare against. The count is reported in detail (0 for same month), but not in the percentage.

Gaps in rule coverage (not bugs)
dim_benchmark has no rules at all, so its pct_rule_pass is blank in the scorecard. dim_advisor has only one (region); years_experience and aum_target_mm have no range checks.
Columns that repeat the date aren't checked against it:
fact_portfolio_snapshot.year and .month aren't checked against snapshot_date.
dim_date checks year, month, quarter and is_month_end against the date, but not day_of_week, week_of_year, month_name, is_quarter_end or is_year_end.
The post-departure rule checks one direction only (flagged rows → inactive client), not the reverse.
Small edge case: if no dim_date.date value parses, f"{dmin:%Y-%m-%d}" at line 359 fails on NaT before any rule runs.
The current numbers look consistent: 100% referential match everywhere, the expected 34% null security_id on cash rows, and the issue counts reproduce (40,630 and 576 on raw, 0 and 0 on clean). The things I'd fix before submitting are #1 (since HW5 reuses the function) and the wording around #3 and #4 in your write-up.