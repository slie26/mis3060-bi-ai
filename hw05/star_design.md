# HW5 — Wildcat Capital Star Schema

MIS3060 Business Intelligence with AI · Sarah Lie

Evidence for every key, relationship and grain below comes from `scripts/01_keys_and_grain.py`
(output: `reports/keys_and_grain.csv`): 8 unique primary keys, 13 relationships with 0 orphan rows,
0 blank required keys, and every grain tested for uniqueness.

---

## Part A — Keys

| Table | Type | Primary key | Foreign keys (column → table[column]) |
|---|---|---|---|
| dim_advisor | Dimension | `advisor_id` | — |
| dim_benchmark | Dimension | `benchmark_id` | — |
| dim_client | Dimension | `client_id` | `advisor_id` → dim_advisor[advisor_id] |
| dim_date | Dimension | `date_id` | — (the facts join on `date`, which is also unique: 1,827 values) |
| dim_security | Dimension | `security_id` | `benchmark_id` → dim_benchmark[benchmark_id] |
| fact_transactions | Fact | `txn_id` | `client_id` → dim_client[client_id]<br>`advisor_id` → dim_advisor[advisor_id]<br>`security_id` → dim_security[security_id] *(blank on cash rows, see below)*<br>`txn_date` → dim_date[date] |
| fact_fees | Fact | `fee_id` | `client_id` → dim_client[client_id]<br>`advisor_id` → dim_advisor[advisor_id]<br>`fee_date` → dim_date[date] |
| fact_portfolio_snapshot | Fact | `snapshot_id` | `client_id` → dim_client[client_id]<br>`advisor_id` → dim_advisor[advisor_id]<br>`benchmark_id` → dim_benchmark[benchmark_id]<br>`snapshot_date` → dim_date[date] |

**Notes**
- **Legitimately blank key:** `fact_transactions.security_id` is blank on 101,528 rows (34.0%). All of them are
  Deposit, Withdrawal or Advisory Fee rows, which move cash and involve no security; 0 cash rows carry a
  security_id and 0 Buy/Sell/Dividend rows lack one. Every other key has 0 blanks.
- **Dates join on `dim_date[date]`, not `date_id`:** the fact date columns match `dim_date.date` 100% and
  `dim_date.date_id` 0% (`date_id` is a surrogate number 1–1,827).
- **Conformed dimensions:** `dim_client`, `dim_advisor` and `dim_date` are shared by all three fact tables;
  `dim_benchmark` is shared by `fact_portfolio_snapshot` and `dim_security`.

---

## Part B — Grain

- **fact_transactions:** One row represents one transaction — a trade (Buy/Sell), a dividend, a deposit,
  a withdrawal or an advisory-fee debit — for one client on one date. *(Unique on `txn_id`: 298,572 rows.)*
- **fact_fees:** One row represents one client's fee charge for one calendar month, dated the 1st of that
  month. *(Unique on `client_id` + `fee_date`: 122,197 rows; each client has exactly one fee row per month,
  and `fee_type` describes that charge rather than splitting it.)*
- **fact_portfolio_snapshot:** One row represents one client's account position for one calendar month,
  dated the 1st of that month. *(Unique on `client_id` + `snapshot_date`: 129,547 rows; each client has one
  account type and one benchmark per month.)*

---

## Part C — Measures

**Additive** = can be summed across every dimension (clients, advisors, securities, and time).
**Semi-additive** = can be summed across some dimensions (e.g. clients) but **not across time**; for a period,
take the value at one point in time (e.g. the latest month).
**Non-additive** = can never be summed; it must be recalculated or averaged with the right weights.

### fact_transactions
| Column | Type | What that means |
|---|---|---|
| `amount` | Additive | Dollar flows can be summed across clients, advisors, securities and days — **but only within one `txn_type`**: every amount is stored positive, so summing Deposits and Withdrawals together adds money in to money out. Always filter or group by `txn_type`. |
| `shares` | Additive (within one security) | Shares can be summed over time and clients for a single security; summing shares of different securities is meaningless (100 shares of a $10 fund ≠ 100 shares of a $500 stock). Blank on cash rows. |
| `price` | Non-additive | A per-share price; summing prices means nothing. Use an average weighted by `shares` (or `amount ÷ shares`). |

### fact_fees
| Column | Type | What that means |
|---|---|---|
| `amount` | Additive | Fee revenue sums correctly across clients, advisors and months (e.g. total 2024 fee revenue). |
| `aum_basis` | Semi-additive | A balance: it equals that month's snapshot AUM. Sum across clients for one month (firm AUM billed), but never across months — 12 monthly balances added together is not a real amount. |
| `bps_charged` | Non-additive | A rate. Summing basis points is meaningless; use an average weighted by `aum_basis` (= total fee ÷ total AUM × 10,000 × 12). |

### fact_portfolio_snapshot
| Column | Type | What that means |
|---|---|---|
| `aum` | Semi-additive | A month-start balance. Sum across clients/advisors for one month; across time take the last (or average) month, never the sum. |
| `return_ytd` | Non-additive | A ratio, and already cumulative for the year. Never sum across months (take the latest month) or across clients (use an AUM-weighted average). |
| `benchmark_return_ytd` | Non-additive | A ratio that is identical for every client on the same benchmark and date; averaging it over client rows over-weights benchmarks with more clients. Read it per benchmark and month. |
| `active_alpha_ytd` | Non-additive | `return_ytd − benchmark_return_ytd`, so it inherits both rules: never summed, AUM-weighted across clients, latest month across time. |
| `cash_pct` | Non-additive | A percentage of the account. Never sum; average weighted by `aum` across clients. |

### Numeric columns that are not measures
- **Keys:** `txn_id`, `fee_id`, `snapshot_id`, `client_id`, `advisor_id`, `security_id`, `benchmark_id` — identifiers; summing or averaging them means nothing.
- **Date parts:** `fact_portfolio_snapshot.year` and `.month` — they repeat `snapshot_date`; use them to group, never to add.
- **Flags:** `is_post_departure_txn`, `is_return_suspect` — 0/1 markers for filtering. Summing a flag only counts flagged rows; it is not a business amount.
- **Text that looks numeric:** `fact_portfolio_snapshot.account_type` contains "529" (a college-savings plan type) next to "Taxable", "IRA" and so on — it is a text category, so the script correctly skipped it.

### Numeric attributes in the dimension tables that should never be summed
- **dim_client:** `age` (average it instead), `zip_code` (a text code), `initial_aum` (a one-time starting balance per client — summing it through a fact relationship would repeat it once per fact row)
- **dim_advisor:** `years_experience` (average instead), `aum_target_mm` (a target per advisor — repeated on every fact row if summed through a fact)
- **dim_security:** `expense_ratio_bps` (a rate; average, weighted by holdings)
- **dim_date:** `date_id`, `year`, `quarter`, `month`, `week_of_year` (labels for grouping), and the `is_*` flags
- **All dimensions:** the ID columns