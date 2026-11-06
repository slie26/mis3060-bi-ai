"""
HW6 Part C - Evidence for the four design questions.

Reads only the Wildcat Capital Clean CSVs in hw06/data/ (nothing from
Power BI), prints the numbers behind each answer, and saves them to
hw06/reports/part_c_evidence.csv with columns (question, item, value).

Run from the repo root (C:\\MIS3060\\mis3060-bi-ai):
    python hw06/scripts/02_part_c_evidence.py

  (a) Ending AUM vs SUMX over clients of each client's own last balance
  (b) Fee Yield (bps) vs Effective Fee Rate (bps) for 2024, and why they differ
  (c) AUM-weighted alpha: last snapshot only, with and without suspect rows
  (d) Organic Growth Rate vs AUM YoY % by client tier, 2024
"""

from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# File locations, built from this script's own location (same as script 01).
# ---------------------------------------------------------------------------
HW_DIR = Path(__file__).resolve().parent.parent          # .../hw06
DATA_DIR = HW_DIR / "data"
REPORTS_DIR = HW_DIR / "reports"
OUT_FILE = REPORTS_DIR / "part_c_evidence.csv"

YEAR = 2024
MONEY_TOL = 0.01   # "aum equals aum_basis" means within one cent

# Every number printed is also stored here, then written to the CSV.
evidence = []


def record(question, item, value, pct=False):
    """Print one piece of evidence and keep it for the CSV.
    pct=True prints a ratio as a percentage (0.014480 -> 1.4480%); the CSV
    always keeps the raw decimal so it can be reused in other calculations."""
    evidence.append({"question": question, "item": item, "value": value})
    if pct and isinstance(value, (int, float)) and not isinstance(value, bool):
        shown = f"{value * 100:.4f}%"
    elif isinstance(value, float):
        shown = f"{value:,.6f}" if abs(value) < 10 else f"{value:,.2f}"
    else:
        shown = value
    print(f"  {item}: {shown}")


def heading(text):
    print("\n" + "=" * 72 + f"\n{text}\n" + "=" * 72)


def to_flag(series):
    """0/1 or True/False column -> True/False. Missing counts as 0."""
    return series.astype(str).str.strip().str.lower().isin(["1", "1.0", "true"])


def weighted_alpha(rows):
    """Σ(aum × alpha) ÷ Σ aum, the same way the DAX measure works: a blank
    alpha adds nothing to the top but its aum still counts in the bottom."""
    numerator = (rows["aum"] * rows["active_alpha_ytd"]).sum(min_count=1)
    denominator = rows["aum"].sum(min_count=1)
    if pd.isna(numerator) or pd.isna(denominator) or denominator == 0:
        return None
    return float(numerator / denominator)


def simple_mean(series):
    """Plain average that skips blanks, like DAX AVERAGE."""
    value = series.mean()
    return None if pd.isna(value) else float(value)


# ===========================================================================
# Load the data
# ===========================================================================
def load_data():
    snap = pd.read_csv(DATA_DIR / "fact_portfolio_snapshot.csv")
    fees = pd.read_csv(DATA_DIR / "fact_fees.csv")
    txns = pd.read_csv(DATA_DIR / "fact_transactions.csv")
    clients = pd.read_csv(DATA_DIR / "dim_client.csv", usecols=["client_id", "client_tier"])

    if "aum_basis" not in fees.columns:
        raise SystemExit("fact_fees.csv has no 'aum_basis' column, which part (b) needs.")

    # Calendar dates only (no time of day), plus a year-month key for joins.
    snap["snapshot_date"] = pd.to_datetime(snap["snapshot_date"]).dt.normalize()
    fees["fee_date"] = pd.to_datetime(fees["fee_date"]).dt.normalize()
    txns["txn_date"] = pd.to_datetime(txns["txn_date"]).dt.normalize()
    snap["month"] = snap["snapshot_date"].dt.to_period("M")
    fees["month"] = fees["fee_date"].dt.to_period("M")

    # Attach each client's tier to every fact row (the dim_client relationship).
    tier_lookup = clients.set_index("client_id")["client_tier"]
    for df in (snap, fees, txns):
        df["client_tier"] = df["client_id"].map(tier_lookup)

    snap["is_suspect"] = to_flag(snap["is_return_suspect"])
    # Trim spaces and ignore upper/lower case, as in script 01.
    txns["txn_type_clean"] = txns["txn_type"].astype(str).str.strip().str.lower()
    return snap, fees, txns


# ===========================================================================
# (a) One total vs the sum of each client's own last balance
# ===========================================================================
def part_a(snap):
    heading("(a) Ending AUM vs SUMX(VALUES(dim_client[client_id]), [Ending AUM])")
    q = "a"

    # Ending AUM with no filters: everything on the single latest date.
    latest = snap["snapshot_date"].max()
    ending_aum = float(snap.loc[snap["snapshot_date"] == latest, "aum"].sum())

    # The SUMX version: for EACH client, [Ending AUM] is evaluated with that
    # client as the filter, so it finds that client's own last date. A client
    # who left in 2022 contributes their 2022 balance.
    # A client could have several rows on their last date; add them all up.
    last_dates = snap.groupby("client_id")["snapshot_date"].max().rename("last_date")
    on_last = snap.merge(last_dates, left_on="client_id", right_index=True)
    on_last = on_last[on_last["snapshot_date"] == on_last["last_date"]]
    per_client = on_last.groupby("client_id").agg(last_aum=("aum", "sum"),
                                                  last_date=("last_date", "first"))
    sumx_total = float(per_client["last_aum"].sum())

    # The clients who explain the gap: their last snapshot is before the latest date.
    gone = per_client[per_client["last_date"] < latest]

    record(q, "latest snapshot date", str(latest.date()))
    record(q, "Ending AUM (no filters)", ending_aum)
    record(q, "SUMX over clients of each client's last AUM", sumx_total)
    record(q, "difference (SUMX - Ending AUM)", sumx_total - ending_aum)
    record(q, "clients whose last snapshot is before the latest date", int(len(gone)))
    record(q, "total last AUM of those clients", float(gone["last_aum"].sum()))
    if not gone.empty:
        record(q, "earliest of those last dates", str(gone["last_date"].min().date()))
        record(q, "latest of those last dates", str(gone["last_date"].max().date()))
    record(q, "check: difference equals their total last AUM",
           bool(abs((sumx_total - ending_aum) - gone["last_aum"].sum()) <= MONEY_TOL))


# ===========================================================================
# (b) Fee Yield vs Effective Fee Rate, and the snapshot/fee coverage gap
# ===========================================================================
def coverage(snap, fees, q, label):
    """Join snapshots to fees on (client_id, month) and count what lines up."""
    snap_keys = snap[["client_id", "month"]].drop_duplicates()
    fee_keys = fees[["client_id", "month"]].drop_duplicates()

    # Snapshot rows with no fee row for the same client and month.
    s = snap.merge(fee_keys, on=["client_id", "month"], how="left", indicator=True)
    no_fee = s[s["_merge"] == "left_only"]

    # Fee rows with no snapshot row for the same client and month.
    f = fees.merge(snap_keys, on=["client_id", "month"], how="left", indicator=True)
    no_snap = f[f["_merge"] == "left_only"]

    # Where both exist, does the snapshot aum equal the fee's aum_basis?
    pairs = snap.merge(fees, on=["client_id", "month"], how="inner",
                       suffixes=("_snap", "_fee"))
    if pairs.empty:
        share_equal = None
    else:
        share_equal = float(((pairs["aum"] - pairs["aum_basis"]).abs() <= MONEY_TOL).mean())

    dup_fee_months = int(fees.duplicated(["client_id", "month"]).sum())

    record(q, f"[{label}] snapshot rows", int(len(snap)))
    record(q, f"[{label}] fee rows", int(len(fees)))
    record(q, f"[{label}] snapshot rows with no fee row", int(len(no_fee)))
    record(q, f"[{label}] total aum of snapshot rows with no fee row",
           float(no_fee["aum"].sum()))
    record(q, f"[{label}] snapshot-fee pairs (same client and month)", int(len(pairs)))
    record(q, f"[{label}] share of pairs where aum = aum_basis (within $0.01)", share_equal,
           pct=True)
    record(q, f"[{label}] fee rows with no snapshot row", int(len(no_snap)))
    record(q, f"[{label}] extra fee rows in an already-billed client-month", dup_fee_months)


def part_b(snap, fees):
    heading(f"(b) Fee Yield (bps) vs Effective Fee Rate (bps), {YEAR}")
    q = "b"

    snap_y = snap[snap["snapshot_date"].dt.year == YEAR]
    fees_y = fees[fees["fee_date"].dt.year == YEAR]

    total_fees = float(fees_y["amount"].sum())
    sum_aum = float(snap_y["aum"].sum())             # every client-month that has a balance
    sum_basis = float(fees_y["aum_basis"].sum())     # only client-months that were billed

    fee_yield = total_fees * 12 * 10_000 / sum_aum
    effective_rate = total_fees * 12 * 10_000 / sum_basis

    record(q, f"total fees {YEAR}", total_fees)
    record(q, f"Σ snapshot aum {YEAR}", sum_aum)
    record(q, f"Σ fee aum_basis {YEAR}", sum_basis)
    record(q, "Σ aum - Σ aum_basis", sum_aum - sum_basis)
    record(q, "Fee Yield (bps)", fee_yield)
    record(q, "Effective Fee Rate (bps)", effective_rate)
    record(q, "gap (Effective Fee Rate - Fee Yield, bps)", effective_rate - fee_yield)

    print("\n  Coverage, matching snapshots to fees by client and month:")
    coverage(snap_y, fees_y, q, str(YEAR))
    print("\n  Same counts for all years:")
    coverage(snap, fees, q, "all years")


# ===========================================================================
# (c) AUM-weighted alpha: why the last snapshot only, and why drop suspects
# ===========================================================================
def part_c(snap):
    heading("(c) AUM-Weighted Alpha at the last snapshot")
    q = "c"

    latest = snap["snapshot_date"].max()
    last = snap[snap["snapshot_date"] == latest]
    clean = last[~last["is_suspect"]]
    suspects = last[last["is_suspect"]]

    record(q, "latest snapshot date", str(latest.date()))
    record(q, "rows on that date", int(len(last)))
    record(q, "weighted alpha, suspects excluded (the measure)", weighted_alpha(clean),
           pct=True)
    record(q, "simple mean alpha, suspects excluded", simple_mean(clean["active_alpha_ytd"]),
           pct=True)
    record(q, "weighted alpha, suspects included", weighted_alpha(last), pct=True)
    record(q, "simple mean alpha, suspects included", simple_mean(last["active_alpha_ytd"]),
           pct=True)
    record(q, "rows with a blank alpha (suspects excluded)",
           int(clean["active_alpha_ytd"].isna().sum()))
    record(q, "suspect rows on that date", int(len(suspects)))
    record(q, "aum of suspect rows", float(suspects["aum"].sum()))
    for tier, count in suspects["client_tier"].fillna("(no tier)").value_counts().sort_index().items():
        record(q, f"suspect rows in tier {tier}", int(count))

    # Wrong on purpose: weighting a year-to-date number across all 12 months
    # mixes January's 1-month alpha with December's 12-month alpha.
    year_rows = snap[(snap["snapshot_date"].dt.year == YEAR) & ~snap["is_suspect"]]
    record(q, f"weighted alpha over all 12 months of {YEAR}, suspects excluded (invalid)",
           weighted_alpha(year_rows), pct=True)


# ===========================================================================
# (d) Organic growth vs total growth by tier
# ===========================================================================
def part_d(snap, txns):
    heading(f"(d) Organic Growth Rate vs AUM YoY % by client tier, {YEAR}")
    q = "d"

    # Snapshots are taken on the 1st of the month, so the Dec 2023 snapshot
    # (2023-12-01) to the Dec 2024 snapshot (2024-12-01) covers money that
    # moved from 2023-12-01 to 2024-11-30. The calendar-year version (what
    # the DAX measure does) uses Jan-Dec 2024 flows instead; both are shown.
    window_start = pd.Timestamp(YEAR - 1, 12, 1)
    window_end = pd.Timestamp(YEAR, 11, 30)

    def ending_aum(year, tier=None):
        """aum on the last snapshot date in that year, for one tier or the
        whole firm (tier=None). Also returns that date."""
        rows = snap[snap["snapshot_date"].dt.year == year]
        if tier is not None:
            rows = rows[rows["client_tier"] == tier]
        if rows.empty:
            return None, None
        last_date = rows["snapshot_date"].max()
        return float(rows.loc[rows["snapshot_date"] == last_date, "aum"].sum()), last_date

    def flows(start, end, tier=None):
        """Deposits, withdrawals and net flows between two dates (inclusive)."""
        t = txns[(txns["txn_date"] >= start) & (txns["txn_date"] <= end)]
        if tier is not None:
            t = t[t["client_tier"] == tier]
        deposits = float(t.loc[t["txn_type_clean"] == "deposit", "amount"].sum())
        withdrawals = float(t.loc[t["txn_type_clean"] == "withdrawal", "amount"].sum())
        return deposits, withdrawals, deposits - withdrawals

    # The firm's ending balance, used for each tier's share of AUM.
    firm_ending, firm_date = ending_aum(YEAR)

    tiers = sorted(snap["client_tier"].dropna().unique())
    for tier in tiers + [None]:          # None = the Firm row (all tiers together)
        name = "Firm" if tier is None else tier

        deposits, withdrawals, net_flows = flows(pd.Timestamp(YEAR, 1, 1),
                                                 pd.Timestamp(YEAR, 12, 31), tier)
        _, _, net_flows_window = flows(window_start, window_end, tier)

        ending, _ = ending_aum(YEAR, tier)
        ending_ly, _ = ending_aum(YEAR - 1, tier)
        if not ending_ly:
            print(f"  {name}: no {YEAR - 1} balance, skipped")
            continue
        organic = net_flows / ending_ly
        organic_window = net_flows_window / ending_ly
        yoy = (ending - ending_ly) / ending_ly

        print(f"\n  {name}")
        record(q, f"{name}: deposits {YEAR}", deposits)
        record(q, f"{name}: withdrawals {YEAR}", withdrawals)
        record(q, f"{name}: net flows {YEAR}", net_flows)
        record(q, f"{name}: net flows {window_start.date()} to {window_end.date()}",
               net_flows_window)
        record(q, f"{name}: Ending AUM end of {YEAR - 1}", ending_ly)
        record(q, f"{name}: Ending AUM end of {YEAR}", ending)
        if tier is not None:
            record(q, f"{name}: share of firm Ending AUM at {firm_date.date()}",
                   ending / firm_ending, pct=True)
        record(q, f"{name}: Organic Growth Rate (calendar-year flows)", organic, pct=True)
        record(q, f"{name}: Organic Growth Rate (snapshot-window flows)", organic_window,
               pct=True)
        record(q, f"{name}: AUM YoY %", yoy, pct=True)
        # Whatever growth net new money does not explain: mostly market
        # returns, minus fees, plus any clients moving in or out of the tier.
        record(q, f"{name}: YoY minus organic (growth not from net new money)",
               yoy - organic, pct=True)


def main():
    snap, fees, txns = load_data()
    part_a(snap)
    part_b(snap, fees)
    part_c(snap)
    part_d(snap, txns)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(evidence, columns=["question", "item", "value"]).to_csv(OUT_FILE, index=False)
    print(f"\nSaved {len(evidence)} rows to {OUT_FILE}")


if __name__ == "__main__":
    main()
