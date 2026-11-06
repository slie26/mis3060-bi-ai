# HW6 — DAX Measure Library: AUM & Performance

MIS3060 Business Intelligence with AI · Sarah Lie

All measures live in the `_Measures` table of `powerbi/hw06.pbix`. Every value below was reconciled to
an independent pandas calculation (`scripts/01_reconcile_measures.py` → `reports/measure_reconciliation.csv`:
91 of 91 rows match).

**Additivity patterns used (from Assignment 5 Part C):**
- **SUM** — additive flows (fees, deposits/withdrawals) can be summed across every dimension
- **Last balance** — `aum` is semi-additive: sum across clients, but across time take the *last* snapshot
- **Recompute-and-weight** — ratios are never summed or averaged row by row; recompute them from additive parts, weighting by `aum`

---

## Part A — Measure library

### Base measures (from the ICEs)
```DAX
Total Fees = SUM ( fact_fees[amount] )

Net Flows =
CALCULATE ( SUM ( fact_transactions[amount] ), fact_transactions[txn_type] = "Deposit" )
    - CALCULATE ( SUM ( fact_transactions[amount] ), fact_transactions[txn_type] = "Withdrawal" )
```
*Pattern:* SUM. Every transaction amount is stored positive, so Net Flows must subtract withdrawals explicitly.

### 0 · AUM (naive SUM) — ⚠️ WRONG ON PURPOSE, never put on a report
```DAX
AUM (naive SUM) = SUM ( fact_portfolio_snapshot[aum] )
```
*Pattern:* plain SUM applied to a balance — the trap. *Format:* currency.
With no filters it returns **$566.68 billion**, about **45× the real $12.73 billion**, because it adds 60 monthly
balances together. It is kept only to show what goes wrong, and pandas makes exactly the same mistake.

### 1 · Ending AUM
```DAX
Ending AUM =
CALCULATE (
    SUM ( fact_portfolio_snapshot[aum] ),
    LASTNONBLANK ( dim_date[date], CALCULATE ( SUM ( fact_portfolio_snapshot[aum] ) ) )
)
```
*Pattern:* last balance. *Format:* currency.
How much money Wildcat manages at the most recent snapshot in whatever period, tier or advisor is selected.

### 2 · Ending Clients
```DAX
Ending Clients =
CALCULATE (
    DISTINCTCOUNT ( fact_portfolio_snapshot[client_id] ),
    LASTNONBLANK ( dim_date[date], CALCULATE ( SUM ( fact_portfolio_snapshot[aum] ) ) )
)
```
*Pattern:* last balance (a count at one date). *Format:* whole number.
How many clients have an account at that last snapshot — clients who left earlier are not counted.

### 3 · Avg AUM per Client
```DAX
Avg AUM per Client = DIVIDE ( [Ending AUM], [Ending Clients] )
```
*Pattern:* recompute (ratio of two last balances). *Format:* currency.
The typical account size today; it tells a manager whether a segment is made of small or large relationships.

### 4 · Ending AUM LY and AUM YoY %
```DAX
Ending AUM LY = CALCULATE ( [Ending AUM], SAMEPERIODLASTYEAR ( dim_date[date] ) )

AUM YoY % =
VAR CurrentAUM = [Ending AUM]
VAR PriorAUM = [Ending AUM LY]
RETURN DIVIDE ( CurrentAUM - PriorAUM, PriorAUM )
```
*Pattern:* last balance, shifted one year; then recompute. *Format:* currency / percentage.
How much bigger the book is than a year ago (blank for 2020, which has no prior year).

### 5 · Ending AUM PM and AUM MoM %
```DAX
Ending AUM PM = CALCULATE ( [Ending AUM], DATEADD ( dim_date[date], -1, MONTH ) )

AUM MoM % =
VAR CurrentAUM = [Ending AUM]
VAR PriorAUM = [Ending AUM PM]
RETURN DIVIDE ( CurrentAUM - PriorAUM, PriorAUM )
```
*Pattern:* last balance, shifted one month; then recompute. *Format:* currency / percentage.
Month-over-month growth of the book; December 2024 grew **4.25%** over November.

### 6 · Avg Monthly AUM
```DAX
Avg Monthly AUM =
DIVIDE (
    SUM ( fact_portfolio_snapshot[aum] ),
    DISTINCTCOUNT ( fact_portfolio_snapshot[snapshot_date] )
)
```
*Pattern:* average balance (sum of balances ÷ number of months). *Format:* currency.
The average size of the book across the months selected — the fair base for anything earned over a whole period.

### 7 · Fee Yield (bps)
```DAX
Fee Yield (bps) =
DIVIDE ( [Total Fees] * 12 * 10000, SUM ( fact_portfolio_snapshot[aum] ) )
```
*Pattern:* recompute-and-weight, across **two fact tables** (fees ÷ AUM, both filtered by the shared dimensions). *Format:* decimal, 2 places.
Annualized fees earned per dollar managed, in basis points — about **43 bps** firm-wide.

### 8 · Organic Growth Rate
```DAX
Organic Growth Rate = DIVIDE ( [Net Flows], [Ending AUM LY] )
```
*Pattern:* recompute (a flow ÷ last year's balance). *Format:* percentage.
How much the book grew from net new client money alone, as a share of where it started the year.

### 9 · AUM-Weighted Alpha
```DAX
AUM-Weighted Alpha =
VAR LastSnapshot =
    LASTNONBLANK ( dim_date[date], CALCULATE ( SUM ( fact_portfolio_snapshot[aum] ) ) )
RETURN
    CALCULATE (
        DIVIDE (
            SUMX (
                fact_portfolio_snapshot,
                fact_portfolio_snapshot[aum] * fact_portfolio_snapshot[active_alpha_ytd]
            ),
            SUM ( fact_portfolio_snapshot[aum] )
        ),
        LastSnapshot,
        fact_portfolio_snapshot[is_return_suspect] = 0
    )
```
*Pattern:* recompute-and-weight at the last balance. *Format:* percentage.
How much clients beat their benchmarks, weighted by account size, using only trustworthy returns.
(The variable was first named `LastDate`, which failed because `LASTDATE` is a DAX function name.)

### 10 · Alpha Signal
```DAX
Alpha Signal =
VAR Alpha = [AUM-Weighted Alpha]
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( Alpha ), BLANK (),
        Alpha >= 0.02, "Outperforming",
        Alpha <= -0.02, "Lagging",
        "In line"
    )
```
*Pattern:* a label on top of a recomputed ratio. *Format:* text.
A plain-English flag a manager can scan: only **2022** and the **2024 Retail** tier are "Outperforming".

### 11 · Top 10 Client Share *(drafted by Claude — see `claude/`)*
```DAX
Top 10 Client Share =
VAR LastSnapshotDate =
    LASTNONBLANK ( dim_date[date], CALCULATE ( SUM ( fact_portfolio_snapshot[aum] ) ) )
VAR TotalAUM = [Ending AUM]
VAR Top10Clients =
    CALCULATETABLE (
        TOPN ( 10, VALUES ( dim_client[client_id] ), [Ending AUM], DESC, dim_client[client_id], ASC ),
        LastSnapshotDate
    )
VAR Top10AUM = CALCULATE ( [Ending AUM], Top10Clients, LastSnapshotDate )
RETURN DIVIDE ( Top10AUM, TotalAUM )
```
*Pattern:* last balance, ranked and recomputed. *Format:* percentage.
How concentrated the book is: the 10 largest clients hold **6.16%** of AUM firm-wide but **8.13%** within UHNW.

### The Measures report page
- **Cards:** Ending AUM, Ending Clients, Avg AUM per Client, Top 10 Client Share (the cards rendered blank on the
  Apporto virtual desktop, so a one-row table beside them shows the same four values)
- **Table by `dim_date[year]`:** Ending AUM, AUM YoY %, Avg Monthly AUM, Fee Yield (bps), Organic Growth Rate,
  AUM-Weighted Alpha, Alpha Signal
- **Table by `dim_client[client_tier]`**, visual-level filter `dim_date[year]` = 2024: Ending AUM, Avg AUM per Client,
  AUM YoY %, Fee Yield (bps), Organic Growth Rate, AUM-Weighted Alpha, Alpha Signal, Top 10 Client Share

---

## Part C — Design questions

Evidence: `scripts/02_part_c_evidence.py` → `reports/part_c_evidence.csv`.

### (a) `Ending AUM` vs `SUMX ( VALUES ( dim_client[client_id] ), [Ending AUM] )`
With no filters, **Ending AUM = $12,729,572,078.86**. The SUMX version gives **$13,149,297,713.80**, which is
**$419,725,634.94 more**. SUMX evaluates `[Ending AUM]` once per client, so `LASTNONBLANK` finds *each client's own*
last snapshot. For the 2,325 clients still with Wildcat that is 2024-12-01, but for the **175 clients who left**, it
is their final month (between December 2022 and November 2023). Their last balances total exactly
**$419,725,634.94** — the whole difference. SUMX therefore adds money that walked out the door up to two years ago.
**`Ending AUM` answers "How much do we manage today?"** — it pins one date for everyone, so only current balances count.

### (b) Why 2024 `Fee Yield (bps)` is lower than ICE 9 `Effective Fee Rate (bps)`
For 2024, **Fee Yield = 43.15 bps** and **Effective Fee Rate = 45.53 bps**    (ICE 9 definition: `DIVIDE ( [Total Fees] * 12 * 10000, SUM ( fact_fees[aum_basis] ) )`; 45.6 bps firm-wide in ICE 9 Checkpoint 6).
Both use the same **$48,714,005.93** of fees, so the difference is entirely in the denominator:
Σ snapshot `aum` = **$135.46 billion**, Σ fee `aum_basis` = **$128.39 billion**, a gap of **$7.07 billion**.
pandas shows why: wherever a client-month has both a snapshot and a fee row, `aum` equals `aum_basis` on **100%** of the
26,216 pairs, and there are **0** fee rows without a snapshot. But **1,684 snapshot client-months in 2024 have no
fee row at all**, and their AUM is exactly **$7,074,540,256.63** — the whole gap. Fee Yield counts that AUM in the
denominator with no fee on top; Effective Fee Rate leaves it out.
**Data limitation:** `fact_fees` does not cover every month a client holds assets — **7,350 client-months
($28.19 billion of AUM)** across 2020–2024 have no fee (HW4 decision log, Issue 12). The data can't tell whether those
are fee waivers, first or last partial months, or fees missing from the extract. If fees are missing, both rates are
understated in revenue; if they are genuine waivers, the Effective Fee Rate overstates what Wildcat really earns per
dollar managed, and Fee Yield is the more honest number.

### (c) Why `AUM-Weighted Alpha` is read at the last snapshot only, and why suspects are excluded
`active_alpha_ytd` is **year-to-date**: January's value covers one month, December's covers the whole year. Averaging
across months mixes 1-month and 12-month results, and `aum` is a balance that must not be added across months either.
Over all 12 months of 2024 the weighted alpha would be **0.32%**, versus the correct **1.45%** at the last snapshot.
At 2024-12-01, **148 rows are flagged `is_return_suspect = 1`, all of them Retail**. These are the implausible returns
from HW4 (e.g. returns above 100% that keep compounding). The evidence:

| At 2024-12-01 | Suspects excluded | Suspects included |
|---|---:|---:|
| AUM-weighted alpha | **1.45%** (the measure) | 1.67% |
| Simple mean of `active_alpha_ytd` | 0.88% | **15.56%** |

Included in a simple mean, the suspects inflate alpha to an absurd 15.56%. Weighting by AUM limits their damage
(they hold only $15.5 million), but still adds 0.22 points. The simple mean without suspects (0.88%) is lower than the
weighted value (1.45%), which means larger accounts beat their benchmarks by more than small ones — so the weighted
number is the right one for "how did the money we manage perform?".

### (d) Organic Growth Rate by client tier in 2024

| Tier | Net flows 2024 | Organic Growth | AUM YoY % | YoY − Organic |
|---|---:|---:|---:|---:|
| Retail | $44.18M | **9.87%** | 19.13% | 9.26 pts |
| HNW | $25.23M | 1.18% | 19.64% | 18.46 pts |
| UHNW | $8.10M | **0.10%** | 19.59% | 19.49 pts |
| Firm | — | 0.73% | 19.58% | 18.85 pts |

All three tiers grew about **19–20%**, but almost none of it came from new money: firm-wide, net flows explain
**0.73 points** of 19.58% growth. The rest came from market performance. **Retail is the only tier where clients
are adding meaningful money** (about half its growth), while UHNW — which holds 76% of AUM — grew almost entirely
because markets rose. That makes Wildcat's growth fragile: a flat market year would leave UHNW, and the firm, nearly flat.
What Organic Growth **does not** tell you: whether the money came from **new clients or existing ones**, the
**timing** of flows within the year, how much of the market gain is **alpha versus the benchmark**, or the **dollar
size** — Retail's high rate sits on a small $448M base, so its $44M of net flows is still small next to UHNW's book.
It also says nothing about **fees**, since flows are measured before them.