# Wildcat Capital — Clean Data (HW4)

These eight files are produced by `hw04/scripts/02_clean.py` from `hw04/data/raw/`. The raw files are never modified (the script checks their SHA-256 fingerprints before and after).

**What changed:** no original value was changed and no row was removed. Two flag columns were added at the end of two tables. Every other column holds exactly the same text as the raw extract: the script re-reads each clean file after writing it and asserts this. Files are written with `\n` line endings, so a raw file with Windows `\r\n` endings will not be byte-identical even though every value is. The full audit trail is in `hw04/data/audit/` (`cleaning_log.csv`, `value_changes.csv`, `quarantine_*.csv`).

| File | Rows | Added columns |
|---|---:|---|
| dim_advisor.csv | 25 | — |
| dim_client.csv | 2,500 | — |
| dim_date.csv | 1,827 | — |
| dim_security.csv | 500 | — |
| dim_benchmark.csv | 8 | — |
| fact_fees.csv | 122,197 | — |
| fact_portfolio_snapshot.csv | 129,547 | `is_return_outlier` |
| fact_transactions.csv | 298,572 | `is_non_trading_day` |

*(Row counts are the raw counts; check them against the "raw = clean + quarantined" lines in the script output.)*

---

## 1. Relationships (primary key → foreign key)

All relationships are one-to-many, from the dimension (one) to the other table (many).

**ID-based (10)**

| # | Primary key (one side) | Foreign key (many side) | Note |
|---|---|---|---|
| 1 | dim_advisor.advisor_id | dim_client.advisor_id | client's assigned advisor |
| 2 | dim_advisor.advisor_id | fact_transactions.advisor_id | |
| 3 | dim_advisor.advisor_id | fact_fees.advisor_id | |
| 4 | dim_advisor.advisor_id | fact_portfolio_snapshot.advisor_id | |
| 5 | dim_client.client_id | fact_transactions.client_id | |
| 6 | dim_client.client_id | fact_fees.client_id | |
| 7 | dim_client.client_id | fact_portfolio_snapshot.client_id | |
| 8 | dim_security.security_id | fact_transactions.security_id | blank on cash rows (see §4) |
| 9 | dim_benchmark.benchmark_id | dim_security.benchmark_id | snowflake link |
| 10 | dim_benchmark.benchmark_id | fact_portfolio_snapshot.benchmark_id | |

**Date-based (3)** — join on `dim_date.date` (the calendar date), not `date_id`:

| # | Primary key | Foreign key |
|---|---|---|
| 11 | dim_date.date | fact_transactions.txn_date |
| 12 | dim_date.date | fact_fees.fee_date |
| 13 | dim_date.date | fact_portfolio_snapshot.snapshot_date |

**Modelling notes for Power BI**
- dim_advisor reaches each fact two ways (directly, and through dim_client). Power BI allows only one active path, so keep the direct fact → dim_advisor relationships active and make dim_client → dim_advisor inactive (or the other way round, on purpose).
- dim_benchmark → dim_security → fact_transactions and dim_benchmark → fact_portfolio_snapshot is also two paths; keep one active.
- Fee and snapshot dates are always the 1st of the month, so they only ever match the first day of each month in dim_date.

## 2. BI column-type settings

| Column(s) | Set to | Why |
|---|---|---|
| All `*_id` columns (advisor_id, client_id, date_id, security_id, benchmark_id, fee_id, snapshot_id, txn_id) | **Text** | Identifiers, not quantities; never sum them |
| dim_client.zip_code | **Text** | Keeps leading zeros (e.g. 01234) |
| dim_security.ticker | Text | Some tickers look like words or codes |
| dim_date.date, dim_client.client_since, txn_date, fee_date, snapshot_date | **Date** | Needed for the date relationships |
| is_non_trading_day, is_return_outlier | **Whole number** (0/1) | Flags added by this script; sum = count of flagged rows |
| is_return_suspect, is_post_departure_txn, is_active, is_etf, is_trading_day, is_month_end, etc. | True/False (or Whole number if stored as 0/1) | Kept exactly as delivered |
| amount, aum, aum_basis, initial_aum, price | Decimal / Fixed decimal | Currency |
| return_ytd, benchmark_return_ytd, active_alpha_ytd, cash_pct | Decimal, format as % | Stored as fractions (0.05 = 5%) |
| dim_advisor.certifications | Text — **turn off "treat 'None' as null"** | `None` is a real value: the advisor holds no certifications (6 advisors). If the BI tool converts it to blank, those advisors disappear from "by certification" visuals |

Blank cells in the CSVs are genuine "does not apply" values (see §4). Do not replace them with 0.

## 3. Flag columns

| Table | Column | Origin | Meaning (1 = …) |
|---|---|---|---|
| fact_transactions | `is_non_trading_day` | **Added** (Issue 1) | txn_date falls on a **weekend**. It is set from dim_date.is_trading_day, but dim_date does not mark market holidays (Issue 15: e.g. 2020-01-01 has is_trading_day = 1), so in practice the flag means "weekend-dated only". Trades on holidays such as New Year's Day are **not** flagged. Dates were not moved because the true trading day can't be known |
| fact_transactions | `is_post_departure_txn` | Existing, unchanged (Issue 5) | transaction after the client left. Verified three ways: every flagged row belongs to a client with is_active = False, is dated in a month after that client's last snapshot, and is dated in 2023. Exclude for "active book" reporting; keep for cash totals |
| fact_portfolio_snapshot | `is_return_outlier` | **Added** (Issue 2) | return_ytd is outside 3 × IQR fences. Statistical test only — an outlier is not automatically wrong |
| fact_portfolio_snapshot | `is_return_suspect` | Existing, unchanged (Issues 2–4) | flagged by an earlier, undocumented process. Covers all rows with \|return_ytd\| > 1 |

**Recommended filter for return analysis:** exclude rows where `is_return_suspect = 1`; use `is_return_outlier` as a second view.

## 4. Legitimate blanks and look-alikes (not defects)

- **dim_security.sector** is blank for the 219 non-equity funds; sector only applies to individual companies.
- **dim_security.expense_ratio_bps** is blank for the 281 individual stocks (is_etf = False); expense ratios only apply to funds. Blank ≠ 0 (0 would mean a free fund).
- **fact_transactions.security_id / shares / price** are blank on the 101,528 Deposit, Withdrawal and Advisory Fee rows. Expect ~34% null keys on relationship 8.
- **dim_security.name** repeats for three pairs of different securities (different tickers). Group by `security_id` or `ticker`, never by name.

## 5. Known limitations (chosen not to fix)

| Issue | Limitation | Reason not fixed |
|---|---|---|
| 3 | 474 rows have is_return_suspect = 1 but pass the 3 × IQR test | The original flag probably uses a different rule (sudden jumps, near −100% losses). Not matching my rule doesn't prove it wrong, so analysts can choose which flag to use |
| 4 | 977 rows have \|return_ytd\| > 1 (all flagged suspect) | Dividing by 100 fits neighbouring months only 0.7% of the time, so it isn't a scale typo; values look cumulative rather than resetting each January. The true value can't be recovered without prices. **Always filter on is_return_suspect before averaging returns** |
| 10 | 858 fee and 930 snapshot rows are dated a few days before client_since | Records are dated the 1st of the month they cover; at month level there are 0 violations. Compare at **month** level, not day level |
| 11 | fact_fees and Advisory Fee rows in fact_transactions disagree in every shared client-month | The tables record fees differently and neither can be proven wrong. **fact_fees is the authority for fee revenue**: its amount = aum_basis × bps_charged ÷ 10,000 ÷ 12 on every row (re-verified by the cleaning script) |
| 12 | 7,350 client-months have a snapshot but no fee (72 are the client's joining month; 362 client-months belong to inactive clients) | Could be waivers, partial first months or closings; filling would invent revenue. Fee revenue may be understated if some are truly missing |
| 13 | 75 clients have risk_profile = "Unknown" | Risk profile is a suitability record from the client questionnaire; inferring "Balanced" from the benchmark could misstate a client's risk tolerance. Compliance should collect the real profiles |
| 14 | Row counts differ from the assignment sheet for dim_client (2,500 vs 2,525) and fact_transactions (298,572 vs 298,772). fact_portfolio_snapshot's row count matches (129,547); its only difference is the extra is_return_suspect column. fact_transactions also has the extra is_post_departure_txn column | The extract was partly cleaned upstream; removed rows aren't available to quarantine or reconcile. Instructor confirmed these are the files to use |
| 15 | dim_date does not mark market holidays: only weekends have is_trading_day = 0 (e.g. 2020-01-01 is marked as a trading day) | The source has no holiday calendar, and adding one would bring in outside data the extract doesn't contain. Consequence: `is_non_trading_day` flags weekend-dated transactions only, and any "trading days" count from dim_date includes holidays |
