# HW4 Decision Log — Wildcat Capital

Decisions written before the cleaning code. Evidence comes from `reports/dq_summary_raw.csv` (01_profile.py, after the Claude Code review fixes), plus follow-up checks noted in each entry.

Decision options: convert / standardize / fill / flag / quarantine / leave as is

**Guiding rule:** these files were already partly cleaned. I only change a value when another column or table proves what the right value is. Otherwise I flag the row or leave it, because filling in a guess would be inventing data.

---

### Issue 1 — Buys/Sells on non-trading days
- **Table / column:** fact_transactions.txn_date (joined to dim_date.is_trading_day)
- **Evidence:** 40,630 of 143,218 Buy/Sell rows fall on a weekend (20,481 Saturday, 20,149 Sunday). Weekend dates appear in about 28% of every txn_type, including Deposits and Withdrawals, which is the 2-in-7 share you'd expect if dates were spread evenly across the week.
- **Dimension violated:** Accuracy/Plausibility
- **Decision:** flag — add `is_non_trading_day` (0/1) to fact_transactions for every weekend-dated row (84,946 rows across all types; 40,630 of them Buy/Sell)
- **Justification:** markets are closed on weekends, so a trade can't really settle on a Saturday. Because the pattern hits every transaction type equally, it looks like how the source system stamps dates, not a few bad trades. I can't tell whether the true date was the Friday before or the Monday after, so moving dates would be a guess.
- **Risk:** if these are posting dates rather than trade dates, the flag is noise, but nothing is lost. If I shifted them and guessed wrong, daily or monthly totals near month-ends would move into the wrong period.

### Issue 2 — Extreme returns not flagged
- **Table / column:** fact_portfolio_snapshot.return_ytd, is_return_suspect
- **Evidence:** 3,977 rows are extreme by the 3× IQR rule; 576 of them have is_return_suspect = 0
- **Dimension violated:** Accuracy/Plausibility
- **Decision:** flag — add a separate `is_return_outlier` (0/1) column; do not change is_return_suspect
- **Justification:** the existing flag was set by an earlier process whose rule isn't documented, so I don't overwrite it. A second flag shows exactly what my statistical test found, so the committee can see both views.
- **Risk:** an IQR outlier isn't automatically wrong, since a strong year for one client is real. If we exclude flagged rows from averages, we may understate genuinely good performance.

### Issue 3 — Returns flagged but not extreme
- **Table / column:** fact_portfolio_snapshot.is_return_suspect
- **Evidence:** 474 rows have is_return_suspect = 1 but pass the 3× IQR rule. Many flagged rows sit near -99% (min -0.994), and some show sudden jumps compared with the client's previous and next month (max jump 23.2).
- **Dimension violated:** none confirmed
- **Decision:** leave as is
- **Justification:** the earlier flag probably uses a different test, such as sudden month-to-month jumps or near-total losses, not just extreme size. Not matching my rule doesn't make it wrong.
- **Risk:** if the original flag is too broad, some normal returns get excluded from analysis. Documented in README_clean.md so analysts can choose which flag to use.

### Issue 4 — Returns above 100% (suspected wrong scale)
- **Table / column:** fact_portfolio_snapshot.return_ytd
- **Evidence:** 977 rows have |return_ytd| > 1; all 977 are already flagged is_return_suspect = 1. Follow-up check: these values move smoothly from month to month (e.g. client 1003: 1.00 → 1.05 → 1.07 → 1.15 → 1.30). Dividing by 100 brings the value close to its neighboring months only 0.7% of the time.
- **Dimension violated:** Accuracy/Plausibility
- **Decision:** leave as is (already flagged); do not convert
- **Justification:** if these were percent-scale typos, dividing by 100 would make them line up with the months around them. It doesn't, so the "wrong scale" theory is disproven. They look like returns that keep building up instead of resetting each January. That's a real problem, but I can't recover the correct value without the underlying prices.
- **Risk:** reports that average return_ytd without excluding flagged rows will be badly inflated. README_clean.md tells BI users to filter on is_return_suspect.

### Issue 5 — Post-departure transactions
- **Table / column:** fact_transactions.is_post_departure_txn
- **Evidence:** 2,410 rows flagged across 131 clients, all dated in 2023. Every flagged row belongs to a client with dim_client.is_active = False, and 100% are dated after that client's last portfolio snapshot.
- **Dimension violated:** Consistency (activity after the account closed)
- **Decision:** flag — keep the existing flag and keep the rows
- **Justification:** I checked the flag against two other sources and it holds up: the clients are inactive, and the transactions come after their last snapshot. These are real money movements (closing trades, final fee debits, withdrawals), so deleting them would break cash totals. Flagging lets analysts exclude them from "active book" reporting.
- **Risk:** if some of these are booking errors, they still count in totals unless filtered. Quarantining them instead would hide real final withdrawals.

### Issue 6 — Securities sharing a name
- **Table / column:** dim_security.name
- **Evidence:** three names appear twice: "Jones Inc Fund" (ID 38 OLAB, Alternative / ID 62 YXPS, Fixed Income), "Davis PLC Fund" (317 RONV, Fixed Income / 371 YMS, Alternative), "Graham Group Inc." (388 PPJV / 395 UFA, both Equity but different sectors). The profile reported 2 duplicates; a manual check found 3.
- **Dimension violated:** none — legitimate structure
- **Decision:** leave as is
- **Justification:** each pair has a different ticker, and most have different asset classes or sectors, so they're different securities. Ticker is the real business key, and all 500 tickers are unique. Merging them would lose holdings.
- **Risk:** a report grouped by name instead of ticker would combine two securities. README_clean.md says to use security_id or ticker.

### Issue 7 — Blank sector and expense ratio
- **Table / column:** dim_security.sector, dim_security.expense_ratio_bps
- **Evidence:** sector is blank in 219 rows, which is exactly the 219 non-equity funds (Fixed Income, Alternative, Cash Equivalent). expense_ratio_bps is blank in 281 rows, which is exactly the 281 Equity stocks (is_etf = False).
- **Dimension violated:** none — legitimate structure
- **Decision:** leave as is
- **Justification:** "sector" only applies to individual companies, and an expense ratio only applies to funds. A blank here means "doesn't apply", not "missing". Filling it with "Unknown" or 0 would be wrong: an expense ratio of 0 would look like a free fund.
- **Risk:** a BI tool may show these as "(Blank)" in a sector chart. Documented in README_clean.md.

### Issue 8 — Blank security fields on cash transactions
- **Table / column:** fact_transactions.security_id, shares, price
- **Evidence:** 101,528 rows are blank in all three. All of them are Deposit, Withdrawal or Advisory Fee; the row rule finds 0 Buy/Sell/Dividend rows missing a security_id.
- **Dimension violated:** none — legitimate structure
- **Decision:** leave as is
- **Justification:** cash movements and fee debits don't involve a security, so these fields correctly have no value.
- **Risk:** the security_id join will show about 34% "null keys". That's expected, and the RI check reports null-key rate separately from orphans.

### Issue 9 — dim_advisor.certifications = "None"
- **Table / column:** dim_advisor.certifications
- **Evidence:** 6 of 25 advisors have the text value "None" (profile: null-like token, 6 rows)
- **Dimension violated:** none — legitimate structure
- **Decision:** leave as is
- **Justification:** "None" means the advisor holds no certifications, which is a real answer. Turning it into a blank would make it look like we don't know, when we do. Reading the file with keep_default_na=False keeps it as text.
- **Risk:** if a BI tool reads it with default settings it becomes blank, and those 6 advisors drop out of a "by certification" chart. Noted in README_clean.md.

### Issue 10 — Fees and snapshots dated before client_since
- **Table / column:** fact_fees.fee_date, fact_portfolio_snapshot.snapshot_date vs dim_client.client_since
- **Evidence:** 858 fee rows and 930 snapshot rows; exactly one row per affected client, median 15 days early. All fee and snapshot dates are the 1st of the month (Claude Code review finding). At month level there are 0 violations.
- **Dimension violated:** none — dating convention
- **Decision:** leave as is
- **Justification:** fees and snapshots are dated to the start of the month they cover. A client who joined on March 15 correctly has a March record dated March 1. My first audit called this an ERROR; Claude Code's review showed it was a flaw in the check, which I fixed to compare at month level.
- **Risk:** a day-level comparison in a future report would wrongly flag these again. The convention is documented in README_clean.md.

### Issue 11 — Fees don't reconcile with transaction fee debits
- **Table / column:** fact_fees.amount vs fact_transactions.amount (txn_type = Advisory Fee)
- **Evidence:** at client × month level, 28,746 of 28,746 groups present on both sides mismatch (all fee types); 7,653 of 7,653 mismatch (Advisory only); 93,451 groups exist only in fact_fees.
- **Dimension violated:** Consistency (cross-table)
- **Decision:** leave as is; known limitation
- **Justification:** a near-100% mismatch means the two tables record fees differently (different timing, grouping or fee types), not that every fee is wrong. Neither table can be shown to be correct, so changing either would be a guess. fact_fees is internally consistent (amount = aum_basis × bps ÷ 10,000 ÷ 12 holds for every row), so I treat it as the source of truth for fee revenue.
- **Risk:** a report that totals fee revenue from fact_transactions will disagree with one built from fact_fees. README_clean.md names fact_fees as the authority.

### Issue 12 — Snapshot months with no fee
- **Table / column:** fact_portfolio_snapshot vs fact_fees (client × month)
- **Evidence:** 7,350 client-months have a snapshot but no fee row (72 are the client's joining month, 362 belong to inactive clients; the rest are spread across 2020–2024). fact_fees has exactly one fee per client-month wherever one exists.
- **Dimension violated:** Completeness (possible)
- **Decision:** leave as is; known limitation
- **Justification:** months with no fee can be real (fee waivers, a first partial month, account closing), and there's no way to tell which. Filling in a fee would create revenue that was never charged.
- **Risk:** if fees really are missing, fee revenue is understated by up to about 6% of client-months. Documented in README_clean.md.

### Issue 13 — Unknown risk profile
- **Table / column:** dim_client.risk_profile
- **Evidence:** 75 clients have risk_profile = "Unknown" (48 Retail, 18 HNW, 9 UHNW). Their snapshots all use benchmark_id 3 (60/40 Blend), the same benchmark used by Balanced clients.
- **Dimension violated:** Completeness
- **Decision:** leave as is
- **Justification:** the benchmark pattern suggests these clients are probably Balanced, but a risk profile is a regulatory suitability record that comes from the client questionnaire. Inferring it from the benchmark could misrepresent a client's risk tolerance. "Unknown" is honest and already standardized.
- **Risk:** risk-profile charts show an "Unknown" group of 75 clients (3%). The compliance team should collect the real profiles.

### Issue 14 — Row and column counts differ from the assignment sheet
- **Table / column:** dim_client, fact_transactions, fact_portfolio_snapshot
- **Evidence:** dim_client has 2,500 rows (sheet: 2,525); fact_transactions has 298,572 rows (sheet: 298,772); extra flag columns is_post_departure_txn and is_return_suspect. The instructor confirmed these are the files to use.
- **Dimension violated:** none — documentation difference
- **Decision:** leave as is; document
- **Justification:** the provided extract was already partly cleaned (about 25 duplicate clients and 200 transactions removed upstream, 2 flags added). The removed rows aren't available, so they can't be quarantined or reconciled.
- **Risk:** row counts in my reports won't match the assignment sheet. Explained in README.md and the cleaning report.

### Issue 15 — dim_date ignores market holidays
- **Table / column:** dim_date.is_trading_day
- **Evidence:** is_trading_day = 0 on exactly the 522 weekend days and nothing else; market holidays such as 2020-01-01 (New Year's Day) are marked 1 (found in the Claude Code review of 02_clean.py)
- **Dimension violated:** Accuracy
- **Decision:** leave as is; known limitation
- **Justification:** a holiday calendar isn't in the provided data, and adding one from outside would change a dimension table without a source in this extract. The is_non_trading_day flag therefore means "weekend-dated", which matches Issue 1.
- **Risk:** trades dated on market holidays aren't flagged, so the flag undercounts implausible trade dates. Documented in README_clean.md.