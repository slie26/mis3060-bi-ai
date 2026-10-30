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

---

## Part E — Relationships and design

**The model I built (Part D):** 13 relationships, one for every foreign key in Part A. All are
many-to-one with single cross-filter direction (dimension filters fact). 12 are active; 1
(`dim_client → dim_advisor`) is inactive. `dim_date` is marked as the date table on `date`.
Row counts in Power BI match the handout for all 8 tables.

**Conformed dimensions:** `dim_client`, `dim_advisor` and `dim_date` are shared by all three fact
tables, so one slicer on any of them filters fees, snapshots and transactions consistently.
`dim_benchmark` is shared by `fact_portfolio_snapshot` and (through `dim_security`)
`fact_transactions`.

**(a) Why do some transactions have no `security_id`? Is it a defect?**
101,528 transactions (34.0%) have a blank `security_id`, and every one of them is a Deposit,
Withdrawal or Advisory Fee. These move cash in or out of the account and don't involve buying or
selling a security, so there is nothing for the key to point to. My script proves it both ways:
0 cash rows carry a security_id and 0 Buy/Sell/Dividend rows lack one. It is not a defect; it is
the structure of the business. In Power BI these rows show up as a single (Blank) row when
transactions are grouped by a security attribute — $3,573,887,227.67 when grouped by
`dim_security[asset_class]`. Any other (Blank) would mean an orphan key, and there are none
(0 orphans on all 13 relationships).

**(b) `advisor_id` is in `dim_client` and on all three facts. Which relationship(s) are active?**
I kept the three **fact → `dim_advisor`** relationships active and made **`dim_client → dim_advisor`
inactive**. Power BI allows only one active path between two tables, and with both active a fact
could reach `dim_advisor` directly and through `dim_client`, which is ambiguous. I chose the direct
path because:
- it keeps the model a star: every fact is one step from every dimension, and an advisor slicer
  filters all three facts directly. I tested it: selecting the West region shows 2 advisors,
  8,639 fees, 9,151 snapshots and 22,291 transactions, which match the CSVs;
- the advisor on each fact row records who handled that fee, snapshot or trade. Today it matches
  the client's advisor on 100% of rows, but if a client is reassigned later, `dim_client` would only
  hold the current advisor, while the facts would still credit history to the right person.

**The trade-off:** an advisor filter does not reach `dim_client`. With West selected, the client
count still shows 2,500, although West has only 181 clients. To count clients by advisor I would
count distinct `client_id` in a fact table, or activate the inactive relationship inside a DAX
measure with `USERELATIONSHIP` in Assignment 6.

**(c) Which column did I join the date dimension on, and why?**
I joined each fact date (`txn_date`, `fee_date`, `snapshot_date`) to **`dim_date[date]`**, not
`dim_date[date_id]`. The facts store calendar dates: they match `dim_date.date` on 100% of rows and
`date_id` on 0% (`date_id` is just a counter from 1 to 1,827). Joining on `date_id` would require
adding a new key column to every fact, which this assignment doesn't allow. `date` is unique in
`dim_date` (1,827 values, one per day), so it can be the "one" side of the relationship. Both sides
are typed as Date (not Date/Time) so the values match exactly, and `date` is the column used to
mark the date table.

**(d) Star or snowflake?**
Two dimensions point to other dimensions: `dim_client → dim_advisor` and
`dim_security → dim_benchmark`. Those links make it technically a snowflake. I kept both, but
differently:
- `dim_security → dim_benchmark` is **active**. It is the only way to group transactions by
  benchmark, and it creates no second path. Note that it means something different from
  `fact_portfolio_snapshot → dim_benchmark`: the snapshot uses the client's *portfolio* benchmark
  (only benchmarks 1, 3 and 8 occur), while a security uses its own *asset-class* benchmark
  (1, 2, 3, 4, 5 and 7). A benchmark slicer therefore answers two different questions for the two facts.
- `dim_client → dim_advisor` is **inactive**, for the reason in (b).

So the model works as a **star with one snowflake branch** (security → benchmark). Flattening the
benchmark into `dim_security` would make it a pure star, but this assignment says not to build new
columns.

---

## Part F — Reflection

**1. Transactions — "How much money did clients deposit and withdraw each quarter in 2024, by advisor region?"**
*Single visual, no DAX: yes, with one condition.* A matrix with `dim_advisor[region]` on rows,
`dim_date[quarter]` on columns, `txn_type` as a filter (Deposit, Withdrawal) and Sum of `amount`
answers it. The condition is that `txn_type` must always be in the visual: every `amount` is stored
as a positive number, so without it Power BI adds deposits, withdrawals, buys and fees together
(the unfiltered total of $16.1 billion is not a real business number). What I *can't* show in one
visual is **net flow** (deposits minus withdrawals). **Schema fix:** add a signed amount (or a
+1/−1 direction column) to `fact_transactions`, so money in and money out cancel correctly when summed.

**2. Fees — "What was total fee revenue by advisor each month in 2024?"**
*Single visual, no DAX: yes.* Fee `amount` is additive across clients, advisors and months, so a
line chart of Sum of `fact_fees[amount]` by `dim_date[month]`, with `dim_advisor` as the legend or a
slicer, is correct as it is. A follow-up question, "what is our average fee rate in bps?", is
*not* answerable by dragging `bps_charged` into a visual: Power BI's Average would weight a $1,000
account the same as an $80 million account. It needs DAX (total fees ÷ total `aum_basis`), or a
schema change that stores the rate's numerator and denominator so it can be summed.

**3. Portfolio snapshots — "What was firm AUM at the end of 2024, by client risk profile?"**
*Single visual, no DAX: no.* `aum` is semi-additive. A monthly line chart works, because each month
has one snapshot per client. But a card or matrix at **year** level sums all 12 monthly balances,
which overstates AUM about 12 times. I would have to remember to filter to December by hand, and a
"by year" matrix can't do that for every year at once. Returns are worse: an Average of `return_ytd`
across clients ignores account size and includes the flagged suspect values. **Schema fix:** add a
period-end flag to `fact_portfolio_snapshot` (e.g. `is_year_end_snapshot`, `is_quarter_end_snapshot`)
so a simple filter picks the closing balance; and store each client's dollar gain alongside the
return, so an AUM-weighted return can be built from additive parts. The other gap the model can't
cover without DAX is **clients per advisor**, because `dim_client → dim_advisor` is inactive (see
Part E b).